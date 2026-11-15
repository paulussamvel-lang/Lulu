"""Offline CAM++ in an owned child process; no ASR or remote model loading."""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys

MODEL_SHA256 = '3388cf5fd3493c9ac9c69851d8e7a8badcfb4f3dc631020c4961371646d5ada8'
MODEL_BYTES = 28036335
MODEL_REVISION = 'e4b6ede7ce16997aff4ae69fbca1f0175e2afede'


def model_path():
    root = (Path(sys._MEIPASS) / 'speaker-runtime' if getattr(sys, 'frozen', False)
            else Path(__file__).resolve().parents[3] / 'build/global-speakers')
    path = root / 'campplus_cn_common.bin'
    if (path.is_symlink() or not path.is_file() or path.stat().st_size != MODEL_BYTES
            or hashlib.sha256(path.read_bytes()).hexdigest() != MODEL_SHA256):
        raise ValueError('整场声纹组件未通过校验；原稿保留，未推断身份。')
    return path


def sample_windows(segments, duration, *, allow_unresolved=False):
    """Use real speech clocks, never fabricate or pad a person's evidence."""
    groups = {}
    for segment in segments:
        if (segment.start is None or segment.end is None or not
                0 <= segment.start < segment.end <= duration + .1):
            raise ValueError('原稿没有有效时间戳，无法提取对应声纹。')
        if segment.speaker_id is not None:
            groups.setdefault(segment.speaker_id, []).append(segment)
    result = {}
    for key, turns in groups.items():
        clean = [turn for turn in turns if turn.end-turn.start >= .75 and not any(
            other.speaker_id != key and min(turn.end, other.end)-max(turn.start, other.start) > .2
            for other in segments)]
        selected = sorted(clean, key=lambda s: s.end-s.start, reverse=True)[:3]
        if not selected:
            if allow_unresolved:
                continue
            raise ValueError(f'发言人 {key} 没有足够的单人语音，需人工确认，未强行合并。')
        result[key] = [(turn.start + max(0., (turn.end-turn.start-6.)/2),
                        min(6., turn.end-turn.start)) for turn in selected]
    return result


def _worker(wav, windows, model, connection):
    import os
    import threading
    import time
    import wave
    parent = os.getppid()
    def watch_parent():
        while True:
            time.sleep(.2)
            if os.getppid() != parent:
                os._exit(1)
    threading.Thread(target=watch_parent, daemon=True).start()
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_IMPLICIT_TOKEN='1')
    try:
        import torch
        import numpy as np
        from torchaudio.compliance.kaldi import fbank
        from funasr.models.campplus.model import CAMPPlus
        from .global_speakers import normalized_embedding
        torch.set_num_threads(2)
        network = CAMPPlus(memory_efficient=False).eval()
        network.load_state_dict(torch.load(model, map_location='cpu', weights_only=True), strict=True)
        vectors = {}
        with wave.open(wav, 'rb') as audio, torch.inference_mode():
            for key, crops in windows.items():
                samples = []
                for start, length in crops:
                    audio.setpos(int(start*16000))
                    pcm = audio.readframes(int(length*16000))
                    waveform = torch.from_numpy(np.frombuffer(pcm, dtype='<i2').astype('float32') / 32768.)
                    features = fbank(waveform.unsqueeze(0), num_mel_bins=80, sample_frequency=16000, dither=0.)
                    features -= features.mean(dim=0, keepdim=True)
                    samples.append(normalized_embedding(network(features.unsqueeze(0))[0].tolist()))
                vectors[key] = normalized_embedding([sum(row[i] for row in samples)/len(samples)
                                                     for i in range(192)])
                connection.send(dict(kind='progress', done=len(vectors), total=len(windows)))
        connection.send(dict(kind='result', embeddings=vectors))
    except BaseException as exc:
        connection.send(dict(kind='error', message=str(exc) if isinstance(exc, ValueError)
                             else '本地声纹计算未完成，原稿保留。'))
    finally:
        connection.close()


def extract_embeddings(wav, segments, *, cancelled=lambda: False, progress=lambda *_: None):
    import multiprocessing
    import time
    import wave
    from .global_speakers import normalized_embedding
    if cancelled():
        raise InterruptedError('整场声纹匹配已取消。')
    with wave.open(str(wav), 'rb') as audio:
        if audio.getnchannels() != 1 or audio.getframerate() != 16000 or audio.getsampwidth() != 2:
            raise ValueError('声纹匹配需要 16k 单声道 PCM。')
        duration = audio.getnframes()/16000
    windows = sample_windows(segments, duration, allow_unresolved=True)
    if not windows:
        raise ValueError('没有足够的单人语音用于声纹匹配，原稿保留。')
    model = model_path()
    context = multiprocessing.get_context('spawn')
    reader, writer = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(str(wav), windows, str(model), writer), daemon=True)
    started = time.monotonic()
    process.start()
    writer.close()
    try:
        while True:
            if cancelled():
                raise InterruptedError('整场声纹匹配已取消。')
            if time.monotonic()-started > 600:
                raise ValueError('声纹计算超过 10 分钟，原稿保留。')
            if reader.poll(.1):
                value = reader.recv()
                if type(value) is not dict:
                    raise ValueError('声纹结果格式无效。')
                if value.get('kind') == 'progress':
                    if set(value) != {'kind', 'done', 'total'} or value['total'] != len(windows):
                        raise ValueError('声纹进度无效。')
                    progress('正在统一整场发言人声纹…', value['done']/max(1, value['total']))
                elif value.get('kind') == 'result':
                    if set(value) != {'kind', 'embeddings'} or set(value['embeddings']) != set(windows):
                        raise ValueError('声纹结果不完整。')
                    result = {key: normalized_embedding(row) for key, row in value['embeddings'].items()}
                    if any(len(row) != 192 for row in result.values()):
                        raise ValueError('声纹维度无效。')
                    return result
                elif value.get('kind') == 'error':
                    raise ValueError(value.get('message', '声纹计算未完成。'))
                else:
                    raise ValueError('声纹返回类型无效。')
            elif not process.is_alive():
                raise ValueError('声纹计算进程已退出，原稿保留。')
    finally:
        reader.close()
        process.join(.2)
        if process.is_alive():
            process.terminate(); process.join(3)
        if process.is_alive():
            process.kill(); process.join(3)
