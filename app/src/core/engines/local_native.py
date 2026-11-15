"""The two native ASR adapters. They share process ownership, not parsers."""
import json
import math
from pathlib import Path
import re
import wave

from .base import TranscriptionEngine
from .asr_resource import model_use
from .native_process import run_native, NativeProcessError
from ..models import Segment, Transcript


class IncompleteTranscription(RuntimeError):
    safe_user_message = True
    code = 'CORE_ASR_MOSS_INCOMPLETE'
    def __init__(self, message, text='', raw_text=''):
        self.partial_text = text
        self.raw_text = raw_text
        super().__init__(message)


def moss_preflight(duration):
    """Pinned Q5 metadata + upstream prompt bound; no memory-size extrapolation."""
    import subprocess
    # 12.5 audio tokens/sec, 15+71 prompt tokens, 256 reserved by this runtime.
    # Round up to a complete 30-second encoder window as a conservative bound.
    tokens = math.ceil(duration / 30) * 375
    if tokens > 131072:
        raise ValueError('录音超过 MOSS 工具的整段处理范围，请选择 Q8 或 Whisper。')
    markers = sum(len(str(sec)) for sec in range(5, int(tokens / 12.5) + 1, 5))
    if tokens + markers + 86 + 256 > 131072:
        raise ValueError('录音超过 MOSS 工具的整段处理范围，请选择 Q8 或 Whisper。')
    try:
        state = subprocess.run(['/usr/sbin/sysctl', '-n', 'kern.memorystatus_vm_pressure_level'],
                               capture_output=True, text=True, timeout=2, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError('无法检查当前内存状态，MOSS 未开始转录；请重试或选择 Q8、Whisper。') from exc
    if state != '1':
        raise RuntimeError('当前内存压力较高，MOSS 未开始转录；请关闭其他占用内存的应用，或选择 Q8、Whisper。')


def parse_moss(stdout, source, duration):
    rows = []
    header_seen = False
    try:
        for line in stdout.splitlines():
            value = json.loads(line)
            if type(value) is not dict: raise ValueError()
            if value.get('type') == 'batch_header':
                if set(value) != {'type', 'load_ms'} or rows or header_seen: raise ValueError()
                header_seen = True
                continue
            rows.append(value)
        if len(rows) != 1 or rows[0].get('file') != str(source): raise ValueError()
    except (ValueError, TypeError) as exc:
        raise IncompleteTranscription('MOSS 返回的结果无法完整核对，原文件保留。') from exc
    row = rows[0]
    text = row.get('text')
    raw = row.get('raw_text')
    recovery_raw = raw if type(raw) is str else ''
    if type(text) is not str: raise IncompleteTranscription('MOSS 正文无效。', raw_text=recovery_raw)
    if row.get('error'):
        raise IncompleteTranscription('MOSS 提前停止，部分文字未作为完整文稿保存。', text, recovery_raw)
    segments = row.get('segments')
    if not text.strip() or not isinstance(segments, list) or not segments:
        raise IncompleteTranscription('MOSS 没有返回有效的分段结果，请换用其他本地模型。', text, recovery_raw)
    result = []
    try:
        for item in segments:
            if (type(item) is not dict or set(item) - {'text', 't0_ms', 't1_ms', 'speaker_id'}
                    or type(item.get('text')) is not str): raise ValueError()
            a, b, speaker = item.get('t0_ms'), item.get('t1_ms'), item.get('speaker_id')
            if (type(a) is not int or type(b) is not int or not 0 <= a <= b): raise ValueError()
            if speaker is not None and (type(speaker) is not int or not 0 < speaker <= 2147483647): raise ValueError()
            if item['text'].strip(): result.append(Segment(item['text'].strip(), a/1000, b/1000, speaker))
        # Verify that a renderer will not drop part of the clean transcript.
        if re.sub(r'\s+', '', text) != re.sub(r'\s+', '', ''.join(s.text for s in result)): raise ValueError()
        if not result or not all(s.end > s.start for s in result): raise ValueError()
        if re.search(r'\[S\d+\]|<\|[^>]*\|>', text): raise ValueError()
        # The upstream parser fills missing boundaries. Accept timed results only
        # when every turn is present with its own boundaries in the raw output.
        if type(raw) is not str: raise ValueError()
        matches = list(re.finditer(r'\[(\d+(?:\.\d+)?)\]\[S(\d+)\](.*?)\[(\d+(?:\.\d+)?)\]', raw, re.S))
        position = 0
        for match in matches:
            if raw[position:match.start()].strip(): raise ValueError()
            position = match.end()
        if raw[position:].strip(): raise ValueError()
        # The native parser intentionally omits whitespace-only speaker turns.
        # They contain no words to preserve and must not look like lost speech.
        turns = [match.groups() for match in matches if match.group(3).strip()]
        if len(turns) != len(result): raise ValueError()
        for (start, speaker, body, end), segment in zip(turns, result):
            if (abs(float(start) - segment.start) > .001 or abs(float(end) - segment.end) > .001
                    or (segment.speaker_id is not None and int(speaker) != segment.speaker_id)
                    or re.sub(r'\s+', '', body) != re.sub(r'\s+', '', segment.text)):
                raise ValueError()
    except (ValueError, TypeError) as exc:
        raise IncompleteTranscription('MOSS 的时间或发言人结果不完整，部分文字已保留。', text, recovery_raw) from exc
    transcript = Transcript(text.strip(), result, None, 'local_moss_q5')
    if any(s.end > duration + max(5., duration * .02) for s in result):
        raise IncompleteTranscription('MOSS 输出超出片段时长，可能出现重复解码，部分文字仅供恢复参考。', text, recovery_raw)
    if any(s.end > duration + .1 for s in result):
        # Keep verified complete words and speaker labels, never publish invented
        # or out-of-media subtitle times. A downstream exporter sees no timings.
        transcript.segments = [Segment(s.text, speaker_id=s.speaker_id) for s in result]
        transcript.meta['timestamp_warning'] = '正文与发言人已保留；模型时间戳超出录音范围，未采用字幕时间轴。'
    return transcript


def moss_audio_chunks(source, directory, *, seconds=600, tail_seconds=0):
    """Partition PCM at quiet boundaries without dropping/duplicating a frame."""
    import audioop
    with wave.open(str(source), 'rb') as audio:
        rate, width, total = audio.getframerate(), audio.getsampwidth(), audio.getnframes()
        if audio.getnchannels() != 1 or rate != 16000 or width != 2:
            raise ValueError('MOSS 分段需要 16k 单声道 PCM 音频。')
        start, number = 0, 0
        while start < total:
            end = min(total, start + int(seconds * rate))
            if total - end < int(tail_seconds * rate):
                end = total
            if end < total:
                # Search the last twenty seconds for a quiet 200 ms window.
                probe_start = max(start + rate, end - 20 * rate)
                audio.setpos(probe_start)
                block = audio.readframes(end - probe_start)
                step = rate // 5
                choices = [(audioop.rms(block[n * width:(n + step) * width], width), n)
                           for n in range(0, len(block) // width - step + 1, step)]
                if choices:
                    _, offset = min(choices, key=lambda item: (item[0], -item[1]))
                    end = probe_start + offset + step // 2
            number += 1
            path = Path(directory) / f'part-{number:04d}.wav'
            audio.setpos(start)
            with wave.open(str(path), 'wb') as part:
                part.setparams((1, width, rate, 0, 'NONE', 'not compressed'))
                remaining = end - start
                while remaining:
                    count = min(remaining, rate * 10)
                    data = audio.readframes(count)
                    if len(data) != count * width:
                        raise ValueError('录音分段读取未完成，原文件保留。')
                    part.writeframesraw(data)
                    remaining -= count
            yield path, start / rate, (end - start) / rate
            # Only the current chunk is retained in temporary storage.
            path.unlink()
            start = end


class NativeASREngine(TranscriptionEngine):
    requires_network = False

    def __init__(self, model_id):
        from .local_models import LOCAL_MODELS
        self.name = model_id
        self.display_name = LOCAL_MODELS[model_id].display_name

    def _moss_part(self, source, duration, model, cancelled, progress):
        moss_preflight(duration)
        def args(work):
            (work/'input.txt').write_text(str(source)+'\n')
            return ['-m', str(model/'MOSS-Transcribe-Diarize-Q5_K_M.gguf'), '--backend', 'metal',
                    '--threads', '8', '--timestamps', 'segment', '--diarize',
                    '--batch', str(work/'input.txt'), '--batch-jsonl']
        try:
            stdout, version = run_native('moss', args, is_cancelled=cancelled, progress=progress)
        except NativeProcessError as exc:
            partial, raw_partial = '', ''
            try:
                partial = parse_moss(exc.stdout, source, duration).text
            except IncompleteTranscription as incomplete:
                partial, raw_partial = incomplete.partial_text, incomplete.raw_text
            raise IncompleteTranscription(str(exc), partial, raw_partial) from exc
        return parse_moss(stdout, source, duration), version

    def _moss_resolved_parts(self, source, duration, model, cancelled, progress,
                             *, offset=0., depth=0):
        """Retry only an invalid span with the same model and exact PCM frames.

        At most two binary refinements: a 10-minute span becomes roughly five,
        then two-and-a-half minutes. Invalid parent output is never appended to
        successful child output. Cancellation and native resource failures do
        not trigger recursive retries.
        """
        if cancelled():
            raise InterruptedError('转录已取消')
        failure = None
        try:
            part, version = self._moss_part(source, duration, model, cancelled, progress)
        except IncompleteTranscription as exc:
            if isinstance(exc.__cause__, NativeProcessError):
                raise
            failure = exc
        else:
            if not part.meta.get('timestamp_warning') or depth >= 2 or duration <= 120:
                yield part, version, offset
                return
            failure = IncompleteTranscription('MOSS 时间戳越界，缩短片段后重新核对。', part.text)
        if depth >= 2 or duration <= 120:
            raise failure
        import tempfile
        progress(f'MOSS 片段输出异常，按约 {duration/2/60:.1f} 分钟细分重试（第 {depth+1}/2 级）', -1)
        with tempfile.TemporaryDirectory(prefix='lulu-moss-refine-') as temporary:
            # Absorb the last <=30 seconds into the preceding half to avoid a
            # tiny artificial tail. Quiet-boundary search moves at most 20 s.
            for path, relative, length in moss_audio_chunks(
                    source, temporary, seconds=duration/2, tail_seconds=30):
                yield from self._moss_resolved_parts(path, length, model, cancelled, progress,
                    offset=offset+relative, depth=depth+1)

    def _moss_transcribe(self, source, duration, model, cancelled, progress):
        import tempfile
        parts, segments, warnings = [], [], []
        speaker_offset, count = 0, 0
        with tempfile.TemporaryDirectory(prefix='lulu-moss-chunks-') as temporary:
            sources = ([(source, 0., duration)] if duration <= 600 else
                       moss_audio_chunks(source, temporary))
            for number, (path, offset, length) in enumerate(sources, 1):
                if cancelled():
                    raise InterruptedError('转录已取消')
                progress(f'MOSS 长录音分段识别 · 第 {number} 段 · 已处理 {offset/60:.1f}/{duration/60:.1f} 分钟', offset/duration)
                try:
                    for part, version, actual_offset in self._moss_resolved_parts(
                            path, length, model, cancelled, progress, offset=offset):
                        count += 1
                        parts.append(part.text)
                        if part.meta.get('timestamp_warning'):
                            warnings.append(part.meta['timestamp_warning'])
                        speaker_ids = {s.speaker_id for s in part.segments if s.speaker_id is not None}
                        for segment in part.segments:
                            segments.append(Segment(segment.text,
                                segment.start + actual_offset if segment.start is not None else None,
                                segment.end + actual_offset if segment.end is not None else None,
                                segment.speaker_id + speaker_offset if segment.speaker_id is not None else None))
                        speaker_offset += max(speaker_ids, default=0)
                except IncompleteTranscription as exc:
                    raise IncompleteTranscription(f'MOSS 第 {number} 段未完成：{exc} 前面已完成的文字已保留。',
                        '\n'.join([*parts, exc.partial_text]), exc.raw_text) from exc
        if warnings:
            segments = [Segment(s.text, speaker_id=s.speaker_id) for s in segments]
        result = Transcript('\n'.join(parts), segments, None, self.name)
        result.meta.update(chunk_count=count, diarization_scope='chunk',
            diarization_notice='长录音按静音边界分段；不同分段的发言人编号独立，未推断跨段身份。')
        if warnings:
            result.meta['timestamp_warning'] = warnings[0]
        return result, version

    def transcribe(self, wav_path, progress=None, is_cancelled=None):
        try:
            return self._transcribe(wav_path, progress, is_cancelled)
        except IncompleteTranscription as exc:
            if not (exc.partial_text.strip() or exc.raw_text.strip()): raise
            from ..models_manager import app_data_dir
            import os
            import stat
            from uuid import uuid4
            directory = app_data_dir() / 'incomplete-transcriptions'
            try:
                if any(p.is_symlink() for p in (directory, *directory.parents)):
                    raise OSError('unsafe recovery directory')
                directory.mkdir(parents=True, mode=0o700, exist_ok=True)
                info = directory.stat()
                if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                    raise OSError('invalid recovery permissions')
                path = directory / (uuid4().hex + '.txt')
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, 'w') as out:
                    out.write('未完成的转录，仅供恢复参考。\n\n' + exc.partial_text)
                    if exc.raw_text:
                        out.write('\n\n原始返回（可能含未闭合文字和无效时间，仅供核对）：\n' + exc.raw_text)
                    out.flush()
                    os.fsync(out.fileno())
            except OSError as storage_error:
                raise IncompleteTranscription('转录未完成，部分文字也未能写入恢复文件；原音频保留。', exc.partial_text, exc.raw_text) from storage_error
            raise IncompleteTranscription(f'转录未完成，部分文字已保存在：{path}', exc.partial_text, exc.raw_text) from exc

    def _transcribe(self, wav_path, progress=None, is_cancelled=None):
        from .. import models_manager as mm
        from ..artifact_trust import model_revision
        from .local_models import LOCAL_MODELS
        progress = progress or (lambda *_: None)
        cancelled = is_cancelled or (lambda: False)
        with model_use(self.name):
            if cancelled(): raise InterruptedError('转录已取消')
            if not mm.is_downloaded(self.name): raise RuntimeError('所选本地模型尚未校验就绪。')
            root = mm.model_path(self.name)
            with wave.open(str(wav_path), 'rb') as wav:
                if wav.getframerate() != 16000 or wav.getnchannels() != 1:
                    raise ValueError('转录输入必须是已准备好的 16k 单声道音频。')
                duration = wav.getnframes()/16000
            progress(f'正在转录（{self.display_name}）…', -1)
            if self.name == 'local_sensevoice_q8':
                args = lambda work: ['-m', str(root/'sensevoice-small-q8.gguf'), '-a', str(wav_path),
                    '--vad', str(root/'fsmn-vad.gguf'), '--vad-maxseg', '30000']
                text, version = run_native('sensevoice-q8', args, is_cancelled=cancelled, progress=progress)
                text = re.sub(r'<\|[^>]*\|>', '', text).strip()
                result = Transcript(text, [Segment(x.strip()) for x in text.splitlines() if x.strip()], None, self.name)
            else:
                result, version = self._moss_transcribe(wav_path, duration, root, cancelled, progress)
            if cancelled(): raise InterruptedError('转录已取消')
            m = LOCAL_MODELS[self.name]
            result.meta['asr'] = dict(model_id=self.name, model_revision=model_revision(m.repo, m.repo_source),
                runtime_version=version, timestamp_kind='segment' if m.timestamps and result.segments
                    and all(s.start is not None and s.end is not None for s in result.segments) else 'none',
                diarization=self.name == 'local_moss_q5', timing_estimated=False)
            return result
