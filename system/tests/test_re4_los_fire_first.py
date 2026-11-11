"""#9560: LOS-fire-first (the idle guard never flanks a Ganado with a clear line) and the bot_trace replay metrics."""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import bot_trace  # noqa: E402

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


def test_idle_verdict_move_with_los_does_not_flank(monkeypatch):
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


def _rows(spec, stage="x"):
    return [{"t": i * 0.2, "pos": (x * 1000.0, 0.0, z * 1000.0), "facing": f, "stage": stage,
             "keys": k, "tel": {"stand_breaks": 3}} for i, (x, z, f, k) in enumerate(spec)]


def test_metrics_swivel_vs_walk():
    swivel = _rows([(0, 0.01 * i, (0.5 if i % 2 else -0.5), ["lleft"]) for i in range(300)])
    walk = _rows([(0, 0.3 * i, 0.0, ["lup"]) for i in range(300)])
    a, b = bot_trace.metrics(swivel), bot_trace.metrics(walk)
    assert a["facing_reversals_per_min"] > 100 and b["facing_reversals_per_min"] == 0
    assert a["pure_sideways_share"] == 1.0 and b["pure_sideways_share"] == 0.0
    assert b["net_m_per_min"] > 10 * a["net_m_per_min"]
    assert math.isclose(b["seconds"], 59.8, abs_tol=0.1)
