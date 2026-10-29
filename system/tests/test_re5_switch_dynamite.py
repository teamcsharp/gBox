"""RE5 Switch dynamite Majini (operator: "dynamite Majini - see them, keep away, shoot the dynamite"). A Majini of
one of the carrier classes (DYNAMITE_CLASSES) in a lit-fuse motion (DYNAMITE_MOTIONS) is a lit stick of dynamite:
the bot sees it (dynamite_seen), backs out of its blast when it is close (dynamite_backoffs), and shoots the stick
itself before any other target (dynamite_picks, aimed at DYNAMITE_AIM_H) so one shot detonates it."""
import math

import pytest

from gbox.mercs.titles import re5_switch as R

MUZZLE = (0.0, 140.0, 30.0)


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)
    monkeypatch.setattr(R, "MINES", False)
    monkeypatch.setattr(R, "CALM", False)


def at(dist, deg, y=0.0):
    a = math.radians(deg)
    return (dist * math.sin(a), y, dist * math.cos(a))


def foe(i, pos, motion=4, act=0, hp=800, cls="uEm10"):
    return {"ptr": 10 + i, "pos": pos, "hp": hp, "hp_max": 800, "motion": motion, "act": act, "class": cls}


def dynamite(i, pos, motion=70, **kw):
    return foe(i, pos, motion=motion, cls="uEm21", **kw)


def snap(enemies, hp=1000, motion=0, dot=None):
    return {"player": {"ptr": 0x5D00001000, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": hp, "hp_max": 1000,
                       "motion": motion, "aim_pitch": None},
            "enemies": enemies, "inventory": [], "kills": 0,
            "laser": {"from": MUZZLE, "at": dot, "up": True} if dot else {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}


def bot():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock


def test_a_lit_dynamite_majini_is_seen_and_remembered():
    b, clock = bot()
    b.tick(snap([foe(0, at(500, 10)), dynamite(1, at(600, -20))]))
    assert b.stats["dynamite_seen"] == 1 and b._dynamite_e is not None
    assert b._dynamite_e.get("ptr") == 11


def test_a_dynamite_majini_must_be_of_a_carrier_class():
    b, clock = bot()
    b.tick(snap([foe(0, at(500, 10)), foe(1, at(600, -20), motion=70)]))   # the motion, not the class: not lit
    assert b.stats["dynamite_seen"] == 0 and b._dynamite_e is None


def test_a_lit_one_close_backs_him_out_of_the_blast_before_the_fight():
    b, clock = bot()
    act = b.tick(snap([foe(0, at(200, 5)), dynamite(1, at(300, 0))]))       # 3 m: inside DYNAMITE_KEEP_R
    assert b.doing == "backoff" and b.stats["dynamite_backoffs"] >= 1
    assert "ldown" in act.get("hold", ())                                   # the gun down, moving out


def test_a_lit_one_far_is_shot_before_a_nearer_calm_one():
    b, clock = bot()
    b.tick(snap([foe(0, at(250, 5)), dynamite(1, at(550, -10))]))            # 5.5 m: outside keep, inside DYNAMITE_R
    assert b.target == 11 and b.stats["dynamite_picks"] >= 1


def test_the_shot_aims_at_the_stick_not_the_chest():
    b, clock = bot()
    d = dynamite(1, at(550, -10))
    assert b._aim_h(d, 550.0, 0.0) == R.DYNAMITE_AIM_H
    assert R.KNEE_H < R.DYNAMITE_AIM_H < R.HEAD_H                           # the stick in his raised hand
    assert R.DYNAMITE_AIM_H > R.CHEST_H                                     # above the chest: at the shoulder


def test_his_shot_on_the_carrier_is_a_detonation():
    b, clock = bot()
    b.tick(snap([dynamite(0, at(700, 0))]))
    clock[0] = 0.2
    b.tick(snap([dynamite(0, at(700, 0), hp=500)]))                         # the stick took the shot: it went off
    assert b.stats["dynamite_detonations"] == 1
