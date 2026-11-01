"""RE5 Switch: the fighter path's wind-up interrupt (#5133 batch, 'shot still playing / no trigger' cluster).

When the PS3 brain is on (PS3_BRAIN, the production default on the Spark), _decide — the only place that called
_windup_tick — is never run: the combat core's fight() returns the trigger straight away. A Majini winding up at
arm's length while the shot plays then fires into his air until WINDUP_HIT_S elapses, his lunge lands, and the
cluster counts it as a hit.

Two-part fix:
  1. _fight calls _windup_tick itself (its wind-up accounting: windup_seen, the hit / interrupt resolution, the
     nearest wind-up as _windup_e).
  2. After the fight, a wind-up within reach releases the trigger (fire_down False, windup_interrupts +1) and
     becomes the target, so the next tick's aim re-fires on the wind-up.

Tests stub the fighter's fight() to hold {zl, zr} every tick — the production trigger — and check the interrupt.
"""
import math

import pytest

from gbox.mercs.titles import re5_switch as R


class StubFighter:
    """Holds the trigger down every tick (the PS3 brain firing), no accounting of its own."""

    flickering = False

    def __init__(self):
        self.fights = 0

    def observe(self, snap, now):
        return None

    def fight(self, snap, live, now):
        self.fights += 1
        return {"hold": {"zl", "zr"}}, "fire", "the stub's trigger"

    def end_round(self, now):
        return None


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
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
            "laser": {"from": (0.0, 140.0, 30.0), "at": dot, "up": True} if dot
            else {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}


def bot():
    clock = [0.0]
    b = R.Bot(stats={}, clock=lambda: clock[0])
    sf = StubFighter()
    b.fighter = sf                                        # the fighter path (the PS3 brain on)
    return b, clock, sf


def test_windup_interrupts_the_trigger_in_the_fighter_path():
    b, clock, sf = bot()
    b.tick(snap([foe(0, at(200, 10), motion=80)], motion=R.MOTION_SHOT))
    assert b.stats.get("windup_interrupts") == 1, f"interrupts: {b.stats.get('windup_interrupts')}"
    assert b.fire_down is False, f"fire_down: {b.fire_down}"
    assert b.target == 10, f"target: {b.target}"
    assert b.stats.get("windup_seen") == 1


def test_no_windup_keeps_firing_in_the_fighter_path():
    b, clock, sf = bot()
    b.tick(snap([foe(0, at(200, 10), motion=4)]))
    assert b.stats.get("windup_interrupts", 0) == 0
    assert b.fire_down is True
    assert b.target == 10


def test_distant_windup_no_interrupt_in_the_fighter_path():
    b, clock, sf = bot()
    b.tick(snap([foe(0, at(200, 10), motion=4), foe(1, at(320, -20), motion=80)]))
    assert b.stats.get("windup_interrupts", 0) == 0, f"interrupts: {b.stats.get('windup_interrupts')}"
    assert b.fire_down is True
    assert b.target == 10, f"the calm closer one is the target, not the far wind-up: {b.target}"


def test_second_windup_interrupts_again():
    b, clock, sf = bot()
    b.tick(snap([foe(0, at(200, 10), motion=80)]))
    assert b.stats.get("windup_interrupts") == 1
    clock[0] = 1.3                                      # the first one resolves (a kill or a land)
    b.tick(snap([foe(0, at(200, 10), motion=4), foe(1, at(220, -20), motion=81)]))
    assert b.stats.get("windup_interrupts") == 2, f"interrupts: {b.stats.get('windup_interrupts')}"
    assert b.target == 11
    assert b.fire_down is False
