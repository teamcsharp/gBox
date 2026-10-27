"""RE5 Switch aim smoothness (operator 2026-10-27: "the bot in RE5 is aiming spasticly"): no flip back to the Majini he
just left within FLIP_S, the dot taking another Majini only after DOT_SWITCH_TICKS, the gun lowered for a far-off aim
only after UNAIM_HOLD_S (never within MIN_UP_S of coming up), the gun raised again inside RERAISE_FRAC of the raise
tolerance once turning, and the motion counters (target switches and flips, stick onsets, aim reversals, raises,
unaims) in the round's counters."""
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


def p(rot=0.0):
    return {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": rot, "hp": 1000, "hp_max": 1000, "motion": 0}


def foes(*specs):
    return [{"ptr": 10 + i, "pos": at(d, a), "hp": 800, "hp_max": 800} for i, (d, a) in enumerate(specs)]


def bot():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock


def test_no_flip_back_to_the_majini_he_just_left_unless_one_is_about_to_grab_him():
    b, clock = bot()
    live = foes((1500, 100), (400, -100))                         # nobody in front: the cost decides
    first = b._choose(p(), live, 0.0)
    assert first["ptr"] == 11                                      # the near one, far cheaper
    other = live[0]
    b.target_at = -10.0
    b._set_target(other["ptr"], 2.0)                               # he moved on to the other one
    assert b.prev_target == first["ptr"] and b.stats["target_switches"] == 1
    b.target_at = -10.0
    assert b._choose(p(), live, 2.5)["ptr"] == other["ptr"]        # the first is cheaper again, 0.5 s on: kept
    assert b.stats["target_flips"] == 0
    b.target_at = -10.0
    assert b._choose(p(), live, 4.0)["ptr"] == first["ptr"]        # past FLIP_S: free to go back
    grab = foes((1500, 100), (400, -100), (100, 170))
    b._set_target(grab[0]["ptr"], 5.0)
    b.target_at = -10.0
    assert b._choose(p(), grab, 5.2)["ptr"] == 12                  # one about to grab him wins at once


def test_turning_with_the_gun_down_raises_it_only_well_inside_the_raise_tolerance():
    b, clock = bot()
    tol = b.raise_tol(800)
    s = {"player": p(), "enemies": foes((800, math.degrees(tol) * 1.5)), "inventory": [],
         "laser": {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}
    b.tick(s)
    assert b.doing == "turn" and b.turning
    s["enemies"] = foes((800, math.degrees(tol) * 0.9))            # inside the tolerance, outside RERAISE_FRAC: on
    clock[0] = 0.1
    b.tick(s)
    assert b.doing == "turn"
    s["enemies"] = foes((800, math.degrees(tol) * 0.6))
    clock[0] = 0.2
    b.tick(s)
    assert b.doing == "raise" and b.stats["raises"] == 1 and not b.turning


def test_the_stick_counters_count_onsets_and_quick_reversals():
    b, clock = bot()
    for t, keys in ((0.0, ("rleft",)), (0.05, ("rleft",)), (0.1, ()), (0.15, ("rright",)), (0.9, ("rleft",)),
                    (1.0, ("rleft", "rup"))):
        b._count_sticks({"hold": keys}, t)
    assert b.stats["stick_onsets"] == 4                            # rleft, rright, rleft, rup
    assert b.stats["aim_reversals"] == 1                           # left -> right in 0.15 s; right -> left after 0.75 s


def test_smoothness_off_keeps_the_old_immediate_dot_switch(monkeypatch):
    monkeypatch.setattr(R, "SMOOTH", False)
    b, clock = bot()
    a, near = at(500, 0), at(200, 3)
    chest = lambda f: (f[0], f[1] + R.CHEST_H, f[2])
    snap = lambda dot: {"player": p(), "enemies": [{"ptr": 10, "pos": a, "hp": 800, "hp_max": 800},
                                                   {"ptr": 11, "pos": near, "hp": 800, "hp_max": 800}],
                        "inventory": [], "laser": {"from": (0.0, 140.0, 30.0), "at": dot, "up": True}}
    b.tick({**snap(chest(a)), "laser": {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}})
    clock[0] = 0.3
    b.tick(snap(chest(near)))
    assert b.target == 11
    for k in R.MOTION_COUNTERS:
        assert k in R.RE5Switch.round_counters
