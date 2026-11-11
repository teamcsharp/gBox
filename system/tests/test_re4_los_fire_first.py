"""Hermes #9560, ported onto main: LOS_FIRE_FIRST - the idle guard never flanks a Ganado he has a clear line to."""
from gbox.mercs.titles import re4_switch as D


def _bot(los):
    cls = next(c for c in vars(D).values() if isinstance(c, type) and "_idle_core" in vars(c))
    b = cls.__new__(cls)
    b.stats = {}
    b.target = 7
    b._line_of_sight_ok = lambda p, e, snap: los
    return b


P = {"pos": (0.0, 0.0, 0.0), "rot": 0.0}
E_NEAR = {"pos": (0.0, 0.0, 3000.0), "ptr": 7}
E_FAR = {"pos": (0.0, 0.0, D.ENGAGE_RANGE_CM + 5000.0), "ptr": 7}


def test_los_open_in_range_keeps_firing():
    assert _bot(True)._los_fire_open(P, E_NEAR, {}) is True


def test_no_los_allows_flank():
    assert _bot(False)._los_fire_open(P, E_NEAR, {}) is False


def test_out_of_range_not_fire_open():
    assert _bot(True)._los_fire_open(P, E_FAR, {}) is False


def test_idle_verdict_move_with_los_does_not_flank():
    class Idle:
        def tick(self, *a, **k):
            return "move"
    for los, flanks in ((True, 0), (False, 1)):
        b = _bot(los)
        b._uc = lambda name: Idle()
        b._profile = lambda: None
        b._flank = None
        b._approach = lambda p, pos, err, snap, run=False: ({"lup"}, "walk")
        act = {"hold": {D.AIM_BTN}, "tap": None}
        out = b._idle_core(P, act, {"enemies": [E_NEAR]}, 10.0)
        assert b.stats.get("flanks", 0) == flanks
        if los:
            assert out is act and b.stats["los_fire_keeps"] == 1 and b._flank is None
        else:
            assert out == {"hold": {"lup"}}


def test_switch_off_restores_the_flank(monkeypatch):
    class Idle:
        def tick(self, *a, **k):
            return "move"
    monkeypatch.setattr(D, "LOS_FIRE_FIRST", False)
    b = _bot(True)
    b._uc = lambda name: Idle()
    b._profile = lambda: None
    b._flank = None
    b._approach = lambda p, pos, err, snap, run=False: ({"lup"}, "walk")
    assert b._idle_core(P, {"hold": {D.AIM_BTN}, "tap": None}, {"enemies": [E_NEAR]}, 10.0) == {"hold": {"lup"}}
    assert b.stats["flanks"] == 1
