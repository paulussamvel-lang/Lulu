"""Regression cases for complete words with bad clocks and bounded long inputs."""
import json
from pathlib import Path
import wave
from unittest.mock import patch

import pytest

from src.core.engines.local_native import (
    IncompleteTranscription, NativeASREngine, moss_audio_chunks, parse_moss,
)
from src.core.models import Segment, Transcript


def row():
    return dict(file='/audio.wav', text='完整正文。', raw_text='[0.00][S1]完整正文。[5.54]',
        segments=[dict(text='完整正文。', t0_ms=0, t1_ms=5540, speaker_id=1)])


def test_complete_words_survive_invalid_clock_without_fabricated_times():
    result = parse_moss(json.dumps(row()), '/audio.wav', 3)
    assert result.text == '完整正文。'
    assert result.segments[0].speaker_id == 1
    assert result.segments[0].start is None and result.segments[0].end is None
    assert 'timestamp_warning' in result.meta


def test_unclosed_or_conflicting_output_is_still_rejected():
    data = row()
    data['raw_text'] += '[6.00][S1]未完成'
    with pytest.raises(IncompleteTranscription):
        parse_moss(json.dumps(data), '/audio.wav', 3)
    data = row()
    data['segments'][0]['t1_ms'] = 1000
    with pytest.raises(IncompleteTranscription):
        parse_moss(json.dumps(data), '/audio.wav', 3)


def test_chunk_partition_retains_every_pcm_frame_once(tmp_path):
    source = tmp_path/'source.wav'
    pcm = b'\x01\x00' * (27 * 16000 + 173)
    with wave.open(str(source), 'wb') as out:
        out.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        out.writeframes(pcm)
    joined, cursor = bytearray(), 0
    for path, offset, duration in moss_audio_chunks(source, tmp_path, seconds=10):
        assert offset == pytest.approx(cursor/16000)
        assert duration <= 10
        with wave.open(str(path), 'rb') as part:
            joined.extend(part.readframes(part.getnframes()))
            cursor += part.getnframes()
    assert bytes(joined) == pcm
    assert not list(tmp_path.glob('part-*.wav'))


def test_chunk_times_and_speakers_do_not_claim_cross_chunk_identity(tmp_path):
    engine = NativeASREngine('local_moss_q5')
    chunks = [(Path('a.wav'), 0., 600.), (Path('b.wav'), 600., 10.)]
    replies = [(Transcript('甲', [Segment('甲', 1., 2., 1)]), 'test'),
               (Transcript('乙', [Segment('乙', 3., 4., 1)]), 'test')]
    with patch('src.core.engines.local_native.moss_audio_chunks', return_value=iter(chunks)), \
         patch.object(engine, '_moss_part', side_effect=replies):
        result, _ = engine._moss_transcribe(Path('source.wav'), 610, tmp_path, lambda:False, lambda *args:None)
    assert result.segments[1].start == 603
    assert result.segments[0].speaker_id != result.segments[1].speaker_id
    assert result.meta['diarization_scope'] == 'chunk'


def test_failed_later_chunk_preserves_prior_complete_words(tmp_path):
    engine = NativeASREngine('local_moss_q5')
    with patch('src.core.engines.local_native.moss_audio_chunks', return_value=iter([
        (Path('a.wav'), 0., 600.), (Path('b.wav'), 600., 10.)])), \
         patch.object(engine, '_moss_part', side_effect=[
             (Transcript('前段', [Segment('前段', 0., 1.)]), 'test'),
             IncompleteTranscription('未完成', '后段部分', '[未闭合')]):
        with pytest.raises(IncompleteTranscription) as failure:
            engine._moss_transcribe(Path('source.wav'), 610, tmp_path, lambda:False, lambda *args:None)
    assert failure.value.partial_text == '前段\n后段部分'


def test_gross_timestamp_overrun_is_not_published_as_verified_words():
    data = row()
    data['segments'][0]['t1_ms'] = 1307000
    data['raw_text'] = '[0.00][S1]完整正文。[1307.00]'
    with pytest.raises(IncompleteTranscription, match='重复解码'):
        parse_moss(json.dumps(data), '/audio.wav', 600)


def test_empty_native_speaker_turn_is_not_mistaken_for_missing_words():
    data = row()
    data['raw_text'] = '[0.00][S1] \n[0.10]' + data['raw_text']
    result = parse_moss(json.dumps(data), '/audio.wav', 6)
    assert result.text == data['text']
    assert len(result.segments) == 1
    assert result.segments[0].end == 5.54
    data['raw_text'] += '[5.54][S1]未返回的正文。[5.90]'
    with pytest.raises(IncompleteTranscription):
        parse_moss(json.dumps(data), '/audio.wav', 6)


def test_refinement_keeps_pcm_and_offsets_without_tiny_tail(tmp_path):
    source = tmp_path/'source.wav'
    pcm = b'\x01\x00' * (600 * 16000)
    with wave.open(str(source), 'wb') as out:
        out.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        out.writeframes(pcm)
    engine = NativeASREngine('local_moss_q5')
    decoded, frames = [], bytearray()
    def transcribe(path, duration, *_):
        if path == source:
            raise IncompleteTranscription('重复输出', '不可信的父段文字')
        with wave.open(str(path), 'rb') as part:
            frames.extend(part.readframes(part.getnframes()))
        decoded.append(duration)
        return Transcript('子段文字', [Segment('子段文字', 0., duration, 1)]), 'test'
    with patch.object(engine, '_moss_part', side_effect=transcribe):
        result, _ = engine._moss_transcribe(source, 600, tmp_path, lambda:False, lambda *args:None)
    assert len(decoded) == 2
    assert bytes(frames) == pcm
    assert result.text == '子段文字\n子段文字'
    assert result.segments[0].end == pytest.approx(result.segments[1].start)
    assert result.segments[-1].end == pytest.approx(600)
    assert result.segments[0].speaker_id != result.segments[1].speaker_id


def test_refinement_has_a_fixed_budget_and_does_not_retry_cancellation(tmp_path):
    engine = NativeASREngine('local_moss_q5')
    with patch.object(engine, '_moss_part', side_effect=IncompleteTranscription('仍不完整')) as call:
        with pytest.raises(IncompleteTranscription):
            list(engine._moss_resolved_parts(Path('source.wav'), 150, tmp_path,
                lambda:False, lambda *args:None, depth=2))
        assert call.call_count == 1
    with patch.object(engine, '_moss_part') as call:
        with pytest.raises(InterruptedError):
            list(engine._moss_resolved_parts(Path('source.wav'), 600, tmp_path,
                lambda:True, lambda *args:None))
        call.assert_not_called()


def test_refinement_does_not_repeat_a_native_resource_failure(tmp_path):
    from src.core.engines.native_process import NativeProcessError
    failure = IncompleteTranscription('本地计算失败')
    failure.__cause__ = NativeProcessError('计算未完成', '')
    engine = NativeASREngine('local_moss_q5')
    with patch.object(engine, '_moss_part', side_effect=failure) as call:
        with pytest.raises(IncompleteTranscription):
            list(engine._moss_resolved_parts(Path('source.wav'), 600, tmp_path,
                lambda:False, lambda *args:None))
        assert call.call_count == 1
