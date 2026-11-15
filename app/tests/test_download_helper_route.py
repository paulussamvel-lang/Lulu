from src.core.collect.download_helper import media_choices, select_detail, work_id
from src.core.live_recording.contracts import Observation, Stream, validate_request, LiveError
from src.core.live_recording.service import LiveService
import pytest


def test_modal_id_wins_over_background_video_id():
    assert work_id('https://www.douyin.com/video/111111111111?modal_id=222222222222') == '222222222222'


def test_same_work_high_resolution_first_and_no_audio_or_foreign_cdn():
    video = dict(bit_rate=[
        dict(bit_rate=9000000, play_addr=dict(width=720, height=1280, url_list=['https://v.douyinvod.com/720.mp4'])),
        dict(bit_rate=5000000, play_addr=dict(width=1080, height=1920, url_list=['https://v.douyinvod.com/1080.mp4'])),
        dict(play_addr=dict(url_list=['https://attacker.invalid/a.mp4', 'https://v.douyinvod.com/audio/a.m4a']))])
    assert media_choices(video) == ['https://v.douyinvod.com/1080.mp4', 'https://v.douyinvod.com/720.mp4']
    payload = dict(aweme_detail=dict(aweme_id='222222222222', video=video))
    assert select_detail(payload, '111111111111') is None
    assert select_detail(payload, '222222222222')[0]['aweme_id'] == '222222222222'


def test_recording_quality_selects_available_source_tier():
    streams = tuple(Stream('https://v.douyincdn.com/'+q, bitrate=n, quality=q)
                    for q,n in [('origin',9000000),('uhd',6000000),('hd',3000000),('sd',1000000)])
    value = Observation('live', streams=streams)
    assert LiveService._choice(value, 0).quality == 'origin'
    assert LiveService._choice(value, 0, '1080p').quality == 'uhd'
    assert LiveService._choice(value, 0, '720p').quality == 'hd'
    assert LiveService._choice(value, 0, '540p').quality == 'sd'
    reduced = Observation('live', streams=(streams[0],streams[-1]))
    assert LiveService._choice(reduced, 0, '720p').quality == 'sd'


def test_quality_setting_rejects_arbitrary_values():
    token = 'session-'+'a'*32
    validate_request('quality_setting', dict(session=token, quality='720p'))
    with pytest.raises(LiveError): validate_request('quality_setting', dict(session=token, quality='8k'))
