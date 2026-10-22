import pytest
import math

from gbox.mercs.titles import re5_motion as M
from gbox.mercs.titles import re5_ps3


def test_hold_ignores_small_flips_and_commits_after_dwell():
    h = M.HeadingHold()
    assert h.pick(0.0, 0.0) == 0.0
    assert h.pick(math.radians(20), 0.1) == 0.0           # inside deadband
    assert h.pick(math.radians(90), 0.2) == 0.0           # large but not yet persistent
    assert h.pick(math.radians(-90), 0.4) == 0.0          # flip-flop restarts the dwell
    assert h.pick(math.radians(-90), 1.1) == pytest.approx(math.radians(-90))
    assert h.flips_suppressed == 2


def test_meter_idle_spin_vs_walk():
    m = M.MotionMeter()
    for i in range(11):                                   # spin in place at 120 deg/s for 1 s
        m.observe(i * 0.1, (0, 0, 0), M.wrap(math.radians(12) * i))
    s = m.summary()
    assert s["idle_spin_s"] == 1.0 and s["samples"] == 10
    w = M.MotionMeter()
    for i in range(11):                                   # straight run at 145 cm/s, constant heading
        w.observe(i * 0.1, (0, 0, 14.5 * i), 0.0)
    ws = w.summary()
    assert ws["idle_spin_s"] == 0.0 and ws["turn_rate_var"] == 0.0


def test_bot_walk_holds_heading_and_reports_stats():
    t = [0.0]
    bot = re5_ps3.Bot(clock=lambda: t[0])
    p = {"pos": (0.0, 0.0, 0.0), "rot": 0.0}
    k = bot._walk(p, math.radians(10), 0.0)
    assert "lup" in k
    t[0] = 0.1
    k2 = bot._walk(p, math.radians(-15), 0.1)             # within hold of committed 10 deg: same decision
    assert "lup" in k2 and abs(bot.hold_heading.heading - math.radians(10)) < 1e-9
    bot.tick({"player": {**p, "pitch": 0.0, "action": 0}})
    assert "motion_idle_spin_s" in bot.stats
