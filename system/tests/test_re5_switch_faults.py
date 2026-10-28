"""RE5 Switch aim faults (operator 2026-10-27 15:33-15:38, watching RE5: the aim "into the distance while all of the
enemies congregate behind him", "up in the sky or away from the enemies", and a shot into a wall): the trigger only on
a confirmed ray (no wall shots; a target behind geometry left a moment), a frozen dot is no live aim, a Majini close
behind costs no turn, an aim far off the nearest threat is corrected at once, and the round data with examples."""
import math

import pytest

from gbox.mercs.titles import re5_switch as R

MUZZLE = (0.0, 140.0, 30.0)


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)


def at(dist, deg, y=0.0):
    a = math.radians(deg)
    return (dist * math.sin(a), y, dist * math.cos(a))


def chest(foot):
    return (foot[0], foot[1] + R.CHEST_H, foot[2])


def along(target, short):
    """A point on the line muzzle -> target, `short` cm before it."""
    d = math.dist(MUZZLE, target)
    return tuple(MUZZLE[k] + (target[k] - MUZZLE[k]) * (d - short) / d for k in range(3))


def p():
    return {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000, "motion": 0}


def snap(enemies, dot=None, motion=0, hp=None):
    hp = hp or [800] * len(enemies)
    return {"player": {"ptr": 0x5D00001000, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000,
                       "motion": motion},
            "enemies": [{"ptr": 10 + i, "pos": x, "hp": h, "hp_max": 800} for i, (x, h) in enumerate(zip(enemies, hp))],
            "inventory": [],
            "laser": {"from": MUZZLE, "at": dot, "up": True} if dot else {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}


def bot():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock


def test_a_ray_ending_on_a_wall_just_short_of_him_fires_nothing():
    b, clock = bot()
    foe = at(500, 0)
    b.tick(snap([foe], motion=22))
    clock[0] = 0.3
    act = b.tick(snap([foe], dot=along(chest(foe), 40.0), motion=26))   # 40 cm short: the old gate fired
    assert "zr" not in act["hold"] and b.stats["wall_shots"] == 1 and b.stats["shots"] == 0
    assert b.stats["ex_wall_shot"].startswith("0.") or "s: Chris (" in b.stats["ex_wall_shot"]


def test_a_target_behind_geometry_is_left_a_moment_for_another():
    b, clock = bot()
    hidden, other = at(900, 0), at(700, 30)
    b.tick(snap([hidden, other], motion=22))
    b.target = 10
    for k, t in enumerate((0.3, 0.5, 0.65, 0.8)):
        clock[0] = t
        b.target = 10 if k == 0 else b.target
        b.tick(snap([hidden, other], dot=(1.0 * k, 140.0, 300.0), motion=26))   # the dot on a wall 2.7 m out
    assert b.stats["wall_blocks"] == 1 and 10 in b.blocked and b.stats["shots"] == 0
    assert 0.2 <= b.stats["wall_aim_s"] <= 0.5                    # the gun's seconds on the wall, counted


def test_a_dot_frozen_while_the_aim_moves_is_no_live_aim():
    b, clock = bot()
    foe = at(600, 6)                                               # in front: the gun comes up
    b.tick(snap([foe], motion=22))
    stuck = (-150.0, 200.0, 900.0)                                 # the dot left of him: the stick turns right
    for k in range(5):
        clock[0] = 0.3 + 0.05 * k
        act = b.tick(snap([foe], dot=stuck, motion=26))
        if b.stats["frozen_dots"]:
            break
    assert b.stats["frozen_dots"] == 1 and b.doing == "restale" and act["hold"] == ()


def test_one_close_behind_beats_one_a_little_farther_ahead():
    b, clock = bot()
    live = [{"ptr": 10, "pos": at(350, 0), "hp": 800}, {"ptr": 11, "pos": at(250, 180), "hp": 800}]
    assert b._choose(p(), live, 0.0)["ptr"] == 11


def test_an_aim_far_off_the_nearest_threat_is_corrected_at_once():
    b, clock = bot()
    ahead, side = at(380, 0), at(300, 90)                          # he keeps the one ahead (within THREAT_KEEP)
    b.tick(snap([ahead, side], motion=22))
    b._set_target(10, 0.0)
    fixed = False
    for k, t in enumerate((0.3, 0.45, 0.6, 0.75)):
        clock[0] = t
        b.target = 10 if not fixed else b.target
        act = b.tick(snap([ahead, side], dot=(40.0 + 3 * k, 150.0, 900.0), motion=26))   # past him, a little off
        fixed = b.stats["aim_away_fixes"] > 0
        if fixed:
            break
    assert fixed and b.target == 11 and b.doing == "unaim" and b.stats["aim_away_s"] >= 0.29
    assert "aim" in b.stats["ex_aim_away"]


def test_seconds_with_one_close_behind_while_aiming_at_another_are_counted():
    b, clock = bot()
    live = [{"ptr": 10, "pos": at(600, 0), "hp": 800}, {"ptr": 11, "pos": at(250, 150), "hp": 800}]
    b.aim_since, b.target = 0.0, 10
    flat = lambda e: math.hypot(e["pos"][0], e["pos"][2])
    for k in range(6):
        b._fault_tick(p(), live, flat, {"enemies": live}, 0.1 * k)
    assert b.stats["behind_threat_s"] == pytest.approx(0.5, abs=0.01)
    assert b.stats["crowd_max"] == 1 and "behind" in b.stats["ex_behind_threat"]


def test_a_far_majini_fired_on_and_then_dead_is_a_long_shot_kill():
    b, clock = bot()
    far = at(1700, 0)
    b.tick(snap([far], motion=22))
    clock[0] = 0.3
    act = b.tick(snap([far], dot=chest(far), motion=26))
    clock[0] = 0.4
    act = b.tick(snap([far], dot=chest(far), motion=26))
    assert "zr" in act["hold"]
    clock[0] = 0.6
    b.tick(snap([far], hp=[0], motion=26))
    assert b.stats["long_shot_kills"] == 1
