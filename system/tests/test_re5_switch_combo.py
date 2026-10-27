"""RE5 Switch: the smoothing pieces one at a time (SMOOTH_FAR on by default, the rest off) and the combo time (operator
2026-10-27 13:10: "be proactive with combo time"): combo breaks and lapses counted every tick; with COMBO_PUSH a
running-down combo window takes the quickest kill, or a run to the nearest when nobody is in reach."""
import math

import pytest

from gbox.mercs.titles import re5_switch as R


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)


def at(dist, deg):
    a = math.radians(deg)
    return (dist * math.sin(a), 0.0, dist * math.cos(a))


def snap(enemies, combo=None, window=None, dot=None):
    return {"player": {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000, "motion": 0},
            "enemies": [{"ptr": 10 + i, "pos": e, "hp": 800, "hp_max": 800} for i, e in enumerate(enemies)],
            "inventory": [], "combo": combo, "combo_timer": window, "timer": 90.0,
            "laser": {"from": (0.0, 140.0, 30.0), "at": dot, "up": True} if dot else {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}


def bot():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock


def test_only_the_far_and_flip_pieces_are_on_by_default():
    assert R.SMOOTH is False and R.piece(R.SMOOTH_FAR) and R.piece(R.SMOOTH_FLIP) and not R.piece(R.SMOOTH_DOT)
    assert not R.piece(R.SMOOTH_LEVEL) and not R.piece(R.SMOOTH_CLOSE)
    b, clock = bot()
    a, near = at(600, 0), at(500, 4)
    chest = lambda f: (f[0], f[1] + R.CHEST_H, f[2])
    b.tick(snap([a, near]))
    clock[0] = 0.3
    b.tick(snap([a, near], dot=chest(near)))
    assert b.target == 11                                          # the dot switch is immediate again (SMOOTH_DOT off)


def test_combo_breaks_and_lapses_are_counted():
    b, clock = bot()
    for t, combo, window in ((0.0, 0, 0.0), (0.1, 1, 6.0), (0.2, 2, 5.0), (0.3, 2, 0.4), (0.4, 0, 0.0),
                             (0.5, 1, 6.0), (0.6, 1, 3.0), (0.7, 0, 0.0)):
        clock[0] = t
        b.tick(snap([at(600, 0)], combo=combo, window=window))
    assert b.stats["combo_breaks"] == 2 and b.stats["combo_lapses"] == 1   # the first ran out, the second was cut
    for k in R.COMBO_COUNTERS:
        assert k in R.RE5Switch.round_counters


def test_a_running_down_combo_takes_the_quickest_kill_or_runs_to_the_nearest(monkeypatch):
    monkeypatch.setattr(R, "COMBO_PUSH", True)
    b, clock = bot()
    b.tick(snap([at(800, 120), at(500, 5)], combo=3, window=5.0))
    b.target, b.target_at = 10, 0.0                                # a target behind, just committed
    clock[0] = 0.2
    b.tick(snap([at(800, 120), at(500, 5)], combo=3, window=2.0))   # the window runs down: the one in front
    assert b.target == 11 and b.stats["combo_pushes"] >= 1
    b2, clock2 = bot()
    act = b2.tick(snap([at(1500, 30)], combo=4, window=1.5))        # nobody in reach: run to the nearest
    assert b2.doing == "walk" and "lup" in act["hold"] and "b" in act["hold"]


def test_the_flip_guard_works_on_its_own_with_smooth_off(monkeypatch):
    monkeypatch.setattr(R, "SMOOTH", False)
    monkeypatch.setattr(R, "SMOOTH_FLIP", True)
    b, clock = bot()
    pl = snap([])["player"]
    live = [{"ptr": 10, "pos": at(1500, 100), "hp": 800, "hp_max": 800},
            {"ptr": 11, "pos": at(400, -100), "hp": 800, "hp_max": 800}]   # nobody in front: the cost decides
    assert b._choose(pl, live, 0.0)["ptr"] == 11
    b.target_at = -10.0
    b._set_target(10, 2.0)                                         # he moved on to the far one
    b.target_at = -10.0
    assert b._choose(pl, live, 2.5)["ptr"] == 10                   # no flip back within FLIP_S
    assert b.stats["target_flips"] == 0
    b.target_at = -10.0
    assert b._choose(pl, live, 4.0)["ptr"] == 11                   # past FLIP_S: free to go back
    monkeypatch.setattr(R, "SMOOTH_FLIP", False)
    b._set_target(10, 5.0)
    b.target_at = -10.0
    assert b._choose(pl, live, 5.2)["ptr"] == 11                   # with the piece off he flips back at once
