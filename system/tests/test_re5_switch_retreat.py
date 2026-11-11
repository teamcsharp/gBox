"""Coaching note 11 (2026-11-10, 'Flawed handling'): critical HP, no heal, a crowd round him - the retreat heads for the
side with the least crowd, not straight away from the one nearest Majini."""
import math

from gbox.mercs.titles import re5_switch as R


def _bot():
    return R.Bot(stats={}, clock=lambda: 0.0)


def _p(rot=0.0):
    return {"pos": (1889.0, 350.0, -475.0), "rot": rot, "hp": 262, "hp_max": 1000, "ptr": 1}


def _foe(dx, dz):
    return {"pos": (1889.0 + dx, 50.0, -475.0 + dz), "hp": 800, "hp_max": 800}


def test_moment_crowd_to_the_east_runs_west_not_away_from_nearest():
    # the moment's shape: one Majini 15 cm south, the pack (10+) 0.2-0.8 m... to the east/north-east
    foes = [_foe(0, -15)] + [_foe(60 + 10 * i, 40 - 8 * i) for i in range(12)]
    h = _bot()._retreat_heading(_p(), foes)
    away_nearest = math.atan2(0, 15)               # the old heading: +z (north), into the pack's flank
    assert abs(R.wrap(h - away_nearest)) > math.radians(45)
    assert math.sin(h) < -0.3                       # west, away from the pack


def test_never_into_a_remembered_wall():
    b = _bot()
    foes = [_foe(0, -100)]                          # open answer: north (+z)
    b._walls = [(1889.0, -475.0, 0.0)]              # a wall bumped heading north here
    h = b._retreat_heading(_p(), foes)
    assert abs(R.wrap(h)) > math.radians(R.WALL_MEM_DEG)


def test_single_foe_is_still_straight_away():
    h = _bot()._retreat_heading(_p(), [_foe(0, -100)])
    assert abs(R.wrap(h)) < 1e-6


def test_critical_heal_uses_it():
    b = _bot()
    foes = [_foe(0, -15)] + [_foe(60 + 10 * i, 40 - 8 * i) for i in range(12)]
    snap = {"inventory": [{"id": 1, "item": 0x1, "rounds": 1, "grid": 0, "hand": False, "type": 1}]}
    p = _p(); p["hp"] = 240
    act = b._heal(p, snap, foes, lambda e: math.hypot(e["pos"][0] - 1889, e["pos"][2] + 475), 10.0)
    assert act is not None and b.stats["heal_status"].startswith("critical retreat")
    away = b.escape[0]
    assert math.sin(away) < -0.3
