"""RE5 Switch wind-ups first (operator 19:25: "tell who is transitioning into an attack animation and be able to
prioritize deactivating them with an attack"): a Majini's own motion (+0x8F8: 80 / 81 the grab's lunge, 60 / 91 the
swings) or his attack flag (+0xA23 0x40) makes him the target before any other; the counters."""
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


def foe(i, pos, motion=4, act=0, hp=800):
    return {"ptr": 10 + i, "pos": pos, "hp": hp, "hp_max": 800, "motion": motion, "act": act}


def snap(enemies, hp=1000, motion=0, dot=None):
    return {"player": {"ptr": 0x5D00001000, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": hp, "hp_max": 1000,
                       "motion": motion, "aim_pitch": None},
            "enemies": enemies, "inventory": [], "kills": 0,
            "laser": {"from": MUZZLE, "at": dot, "up": True} if dot else {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}


def bot():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock


def test_the_one_winding_up_is_the_target_before_a_nearer_calm_one():
    b, clock = bot()
    b.tick(snap([foe(0, at(200, 10)), foe(1, at(280, -20), motion=80)]))
    assert b.target == 11 and b.stats["windup_seen"] == 1 and b.stats["windup_picks"] >= 1


def test_the_attack_flag_counts_as_a_wind_up():
    b, clock = bot()
    b.tick(snap([foe(0, at(200, 10)), foe(1, at(280, -20), act=0x40)]))
    assert b.target == 11


def test_in_the_crowd_fire_the_wind_up_is_the_one_fired_on():
    b, clock = bot()
    ring = [foe(0, at(200, 5)), foe(1, at(300, 40)), foe(2, at(260, -30), motion=60)]
    b.tick(snap(ring))
    assert b.target == 12 and b._ramp is not None


def test_a_wind_up_that_lands_is_counted_one_his_shots_hurt_is_an_interrupt():
    b, clock = bot()
    b.tick(snap([foe(0, at(250, 0), motion=80)]))
    clock[0] = 0.5
    b.tick(snap([foe(0, at(120, 0), motion=80)], hp=800))         # it lands: his health falls
    clock[0] = 1.3
    b.tick(snap([foe(0, at(120, 0), motion=4)], hp=800))
    assert b.stats["hits_after_windup"] == 1 and b.stats["windup_interrupts"] == 0
    b2, clock2 = bot()
    b2.tick(snap([foe(0, at(250, 0), motion=80)]))
    clock2[0] = 0.4
    b2.tick(snap([foe(0, at(240, 0), motion=86, hp=500)]))         # shot: staggered, hurt
    clock2[0] = 1.3
    b2.tick(snap([foe(0, at(240, 0), motion=4, hp=500)]))
    assert b2.stats["windup_interrupts"] == 1 and b2.stats["hits_after_windup"] == 0


def test_a_wind_up_behind_beats_a_calm_one_nearer_in_front_for_the_quick_turn():
    b, clock = bot()
    b.tick(snap([foe(0, at(150, 0)), foe(1, at(220, 170), motion=81)]))
    assert b.quick == 2 and b.target == 11 and b.stats["behind_turns"] == 1


def test_a_far_wind_up_is_no_concern():
    b, clock = bot()
    b.tick(snap([foe(0, at(200, 10)), foe(1, at(900, -20), motion=80)]))
    assert b.target == 10 and b.stats["windup_seen"] == 0
