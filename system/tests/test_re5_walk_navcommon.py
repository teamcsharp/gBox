"""RE5's Bot._walk uses the shared navcommon.StuckDetector (request #3026)."""
from gbox.mercs.navcommon import StuckDetector
from gbox.mercs.titles import re5_ps3 as R


def _bot():
    return R.Bot.__new__(R.Bot)


def test_bot_stuck_detector_is_the_shared_engine_one():
    src = open(R.__file__).read()
    assert "from ..navcommon import StuckDetector" in src
    assert "self.stuck_det = StuckDetector(STUCK_S, STUCK_MOVE)" in src


def test_hist_aliases_the_detector_samples():
    b = _bot()
    b.stuck_det = StuckDetector(R.STUCK_S, R.STUCK_MOVE)
    b.hist = [(0.0, 1.0, 2.0)]
    assert b.stuck_det.hist == [(0.0, 1.0, 2.0)]
    b.hist = []
    assert b.hist == [] and b.stuck_det.hist == []
