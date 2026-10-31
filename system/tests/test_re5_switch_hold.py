"""RE5 Switch hold first (the "grabbed from the front" cluster #5133, 2026-10-28/29: 23 holds of 2.2-3.2 m while the
bot aimed at a farther Majini - 79 % front, avg 2.7 s to break, 6 s of 25 s dead): one on his level within HOLD_R is
a hold he cannot break from in time, so the target he already has is kept and shot (HOLD_FIRST), never a swing at a
farther one while that near one stands; past HOLD_R, as before."""
import math

import pytest

from gbox.mercs.titles import re5_switch as R

MUZZLE = (0.0, 140.0, 30.0)


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "CROWD_FIRE", False)   # (these test the hold-first paths; tests/test_re5_switch_crowd.py)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)


def at(dist, deg, y=0.0):
    a = math.radians(deg)
    return (dist * math.sin(a), y, dist * math.cos(a))


def chest(foot):
    return (foot[0], foot[1] + R.CHEST_H, foot[2])


def p():
    return {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000, "motion": 0}


def foes(*pos):
    return [{"ptr": 10 + i, "pos": x, "hp": 800, "hp_max": 800} for i, x in enumerate(pos)]


def snap(enemies, dot=None, motion=0):
    return {"player": {"ptr": 0x5D00001000, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000,
                       "motion": motion},
            "enemies": [{"ptr": 10 + i, "pos": x, "hp": 800, "hp_max": 800} for i, x in enumerate(enemies)],
            "inventory": [],
            "laser": {"from": MUZZLE, "at": dot, "up": True} if dot else {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}


def bot():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock


def test_a_near_majini_on_his_level_keeps_the_target_over_a_farther_one():
    b, clock = bot()
    far, near = at(800, 0), at(300, 90)                      # the hold at 3.0 m, beside him (cluster's front hold)
    b._set_target(10, 0.0)
    assert b._choose(p(), foes(far, near), 0.0)["ptr"] == 10  # not a swing at the far one while the near one stands
    assert b.stats["threat_switches"] == 0


def test_the_hold_wins_at_grab_range_just_beyond_the_keep():
    b, clock = bot()
    far, near = at(600, 0), at(320, 120)                      # 3.2 m hold, the keep rule alone would keep the far one
    b._set_target(10, 0.0)
    assert b._choose(p(), foes(far, near), 0.0)["ptr"] == 10  # held first: the current one kept and shot at
    assert b.stats["threat_switches"] == 0


def test_past_hold_range_the_old_pick_still_applies():
    b, clock = bot()
    far, beyond = at(800, 0), at(450, 90)                     # 4.5 m: no hold threat, in front first, as before
    b._set_target(10, 0.0)
    assert b._choose(p(), foes(far, beyond), 0.0)["ptr"] == 10
    assert b.stats["threat_ticks"] == 0


def test_an_off_level_near_majini_is_no_hold_first():
    b, clock = bot()
    far, roof = at(800, 0), at(300, 0, y=300.0)                # 2.5 m up on a ledge: not a hold threat
    b._set_target(10, 0.0)
    assert b._choose(p(), foes(far, roof), 0.0)["ptr"] == 10   # the old pick (off-level penalty) takes the far one
    assert b.stats["threat_ticks"] == 0


def test_with_no_target_the_hold_is_not_a_keep_but_the_grab_still_wins():
    b, clock = bot()
    far, near = at(800, 0), at(300, 90)
    assert b._choose(p(), foes(far, near), 0.0)["ptr"] == 11    # in front, no hold to keep (no target yet)


def test_the_hold_first_picks_the_nearest_in_front_when_held():
    b, clock = bot()
    s = snap([at(300, 90), at(500, 0)], motion=22)             # the hold beside him, one in front to shoot at
    b.tick(s)                                                  # held: the one in front is the pick, not the hold itself
    assert b.target == 10


def test_hold_first_is_off_and_the_old_pick_stands(monkeypatch):
    monkeypatch.setattr(R, "HOLD_FIRST", False)
    b, clock = bot()
    far, near = at(800, 0), at(300, 90)
    b._set_target(10, 0.0)
    assert b._choose(p(), foes(far, near), 0.0)["ptr"] == 11   # (the old threat-first pick, unchanged)
