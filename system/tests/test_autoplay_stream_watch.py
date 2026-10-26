"""Autoplay's periodic visual check must not start a competing screen capture."""
from types import SimpleNamespace
import time

import pytest

from gbox import tools as T
from tests.test_autoplay_recovery import png


@pytest.mark.parametrize('grey, expected', [(2, True), (90, False)])
def test_black_watch_uses_fresh_encoder_frame_without_a_second_grab(grey, expected):
    def extra_grab():
        pytest.fail('A live stream must not spawn a second desktop capture')
    ad = SimpleNamespace(get_frame=extra_grab, stream=SimpleNamespace(
        latest=png(grey), clock=lambda: 10., last_frame=9.5, closed=False))
    assert T._black(ad) is expected


@pytest.mark.parametrize('patch', [dict(last_frame=7.), dict(last_frame=11.), dict(closed=True), dict(latest=None)])
def test_missing_or_stale_stream_is_not_black_game_evidence(patch):
    stream = dict(latest=png(0), clock=lambda: 10., last_frame=9.5, closed=False)
    stream.update(patch)
    ad = SimpleNamespace(stream=SimpleNamespace(**stream), get_frame=lambda: pytest.fail('No competing capture'))
    assert T._black(ad) is None


def test_unknown_stream_gap_does_not_count_toward_black_game_timeout(monkeypatch):
    now = [100.]
    driver = SimpleNamespace(stopped=False)
    run = {'sid': 'worker-game', 'thread': None}
    monkeypatch.setattr(T, '_black', lambda ad: True if now[0] == 100 or now[0] >= 160 else None)
    monkeypatch.setattr(T, '_mercs_human_controls', lambda sid: False)
    def sleep(seconds):
        now[0] += seconds
        if now[0] >= 185:
            driver.stopped = True
    T._black_watch(run, driver, SimpleNamespace(get_frame=lambda: b''), clock=lambda: now[0], sleep=sleep)
    for _ in range(100):
        if driver.stopped:
            break
        time.sleep(.005)
    assert driver.stopped and 'bad_end' not in run
