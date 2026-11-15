import pytest

from src.core.engines.global_speakers import link_speakers
from src.core.models import Segment


def test_same_people_keep_identity_after_chunk_order_changes_and_repeated_words():
    segments = [Segment('重复的话', 0., 3., 1), Segment('第二人', 4., 7., 2),
                Segment('第二人又说', 601., 604., 3), Segment('重复的话', 605., 608., 4)]
    result, evidence = link_speakers(segments, {1: [1., 0.], 2: [0., 1.],
                                               3: [0., 1.], 4: [1., 0.]})
    assert [s.speaker_id for s in result] == [1, 2, 2, 1]
    assert [(s.text, s.start, s.end) for s in result] == [(s.text, s.start, s.end) for s in segments]
    assert [s.speaker_id for s in segments] == [1, 2, 3, 4]
    assert evidence['scope'] == 'recording' and evidence['speaker_count'] == 2


def test_local_number_and_identical_words_are_not_identity_evidence():
    segments = [Segment('好的', 0., 3., 1), Segment('好的', 601., 604., 2)]
    result, _ = link_speakers(segments, {1: [1., 0.], 2: [0., 1.]})
    assert [s.speaker_id for s in result] == [1, 2]


def test_real_overlap_prevents_merge_even_for_similar_embeddings():
    segments = [Segment('甲', 0., 3., 1), Segment('乙', 1., 4., 2)]
    result, _ = link_speakers(segments, {1: [1., 0.], 2: [1., 0.]})
    assert result[0].speaker_id != result[1].speaker_id


def test_missing_invalid_or_untimed_acoustic_evidence_fails_without_guessing():
    segments = [Segment('甲', 0., 3., 1)]
    for evidence in ({}, {1: [0., 0.]}, {1: [float('nan'), 0.]}):
        with pytest.raises(ValueError):
            link_speakers(segments, evidence)
    with pytest.raises(ValueError):
        link_speakers([Segment('甲', speaker_id=1)], {1: [1., 0.]})


def test_cancellation_and_complete_link_prevent_unbounded_or_chained_merges():
    segments = [Segment('甲', 0., 3., 1), Segment('乙', 4., 7., 2), Segment('丙', 8., 11., 3)]
    embeddings = {1: [1., 0.], 2: [.8, .6], 3: [.28, .96]}
    _, evidence = link_speakers(segments, embeddings, threshold=.7)
    assert evidence['speaker_count'] == 2
    with pytest.raises(InterruptedError):
        link_speakers(segments, embeddings, cancelled=lambda: True)


def test_embedding_windows_use_clean_actual_speech_and_refuse_guessing():
    from src.core.engines.speaker_embedding import sample_windows
    rows = [Segment('甲', 0., 10., 1), Segment('乙', 20., 25., 2)]
    windows = sample_windows(rows, 30.)
    assert windows == {1: [(2., 6.)], 2: [(20., 5.)]}
    with pytest.raises(ValueError, match='没有足够'):
        sample_windows([Segment('短音', 0., .2, 1)], 1.)
    with pytest.raises(ValueError, match='没有足够'):
        sample_windows([Segment('甲', 0., 3., 1), Segment('乙', 0., 3., 2)], 4.)


def test_short_unresolved_turn_remains_unknown_instead_of_becoming_a_fake_person():
    rows = [Segment('长句', 0., 3., 1), Segment('嗯', 5., 5.2, 2)]
    result, audit = link_speakers(rows, {1: [1., 0.]}, allow_unresolved=True)
    assert [s.speaker_id for s in result] == [1, None]
    assert audit['unresolved_local_ids'] == [2]
    assert [s.text for s in result] == ['长句', '嗯']


def test_document_exposes_unresolved_speech_without_losing_words_or_time():
    from src.core.models import Transcript
    from src.core.obsidian import note_body
    transcript = Transcript('重复\n重复', [Segment('重复', 0., 1., 1), Segment('重复', 2., 3.)],
        engine='local_moss_q5', meta=dict(diarization_scope='recording', diarization_notice='整场匹配；短音待确认。'))
    text = note_body(transcript, 'fixture')
    assert '发言人待确认：重复' in text
    assert text.count('重复') == 2
    assert '[00:02]' in text and '短音待确认' in text


def test_cancelled_embedding_never_opens_audio_or_starts_worker():
    from src.core.engines.speaker_embedding import extract_embeddings
    with pytest.raises(InterruptedError):
        extract_embeddings('/nonexistent/source.wav', [], cancelled=lambda: True)
