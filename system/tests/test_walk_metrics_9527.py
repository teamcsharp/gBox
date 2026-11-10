"""#9527: walk-quality telemetry and the room-scaled wall probe."""
import math

from gbox.mercs.core import room_map as RM
from gbox.mercs.core.walk_metrics import WalkMetrics


def test_swivel_counts_reversals_and_unwall_share():
    m = WalkMetrics()
    rot = 0.0
    for i in range(20):                       # 20 Hz, turning back and forth 0.2 rad each tick
        rot += 0.2 if i % 2 == 0 else -0.2
        m.observe(i * 0.05, (0.0, 0.0, 0.0), rot, "unwall", True)
    s = m.summary()
    assert s["wm_reversals"] == 18 and s["wm_unwall_share"] == 1.0
    assert s["wm_reversals_pm"] == round(18 * 60.0 / 0.95, 1) and s["wm_net_mm_pm"] == 0
    assert 0.9 < s["wm_wall_s"] <= 1.0


def test_straight_run_has_no_reversals_and_path():
    m = WalkMetrics()
    for i in range(41):
        m.observe(i * 0.05, (0.0, 0.0, i * 100.0), 0.0, "walk", False)
    s = m.summary()
    assert s["wm_reversals"] == 0 and s["wm_path_mm"] == 4000 and s["wm_wall_s"] == 0.0
    assert s["wm_net_mm_pm"] == 4000 * 30


def test_respawn_jump_is_not_path():
    m = WalkMetrics()
    m.observe(0.0, (0.0, 0.0, 0.0), 0.0)
    m.observe(0.05, (50000.0, 0.0, 0.0), 0.0)
    assert m.summary()["wm_path_mm"] == 0


class _Box:
    """A square room, half-size `h` mm: walk_block is None inside, refused past the edge."""
    def __init__(self, h):
        self.h = h

    def walk_block(self, a, b, end_r=0.0, body_r=0.0):
        return None if abs(b[0]) < self.h and abs(b[2]) < self.h else "wall"


def test_probe_scales_to_the_room():
    big, small = _Box(6000.0), _Box(1000.0)
    p = (0.0, 0.0, 0.0)
    assert RM.scaled_probe(big, p, 800.0) == 800.0
    assert RM.scaled_probe(small, p, 800.0) == 400.0 + 160.0    # 0.4 * 1400: the diagonal is the longest open run, in 200 mm steps
    assert RM.scaled_probe(_Box(500.0), p, 800.0) == 400.0     # never under the minimum


def test_unwall_arcs_forward_instead_of_swivelling_in_place():
    from gbox.mercs.titles import re4_switch as r
    bot = r.Bot.__new__(r.Bot)
    p = {"pos": (0.0, 0.0, 0.0), "rot": 0.0}
    goal_side = (1000.0 * math.sin(0.85), 0.0, 1000.0 * math.cos(0.85))   # 0.85 rad off: beyond STEP_TURN_RAD
    keys = bot._unwall_keys(p, goal_side)
    assert "lup" in keys
    goal_far = (1000.0 * math.sin(1.8), 0.0, 1000.0 * math.cos(1.8))    # beyond the arc: a turn on the spot
    assert "lup" not in bot._unwall_keys(p, goal_far)
