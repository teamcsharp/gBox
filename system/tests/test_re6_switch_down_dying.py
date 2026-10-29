"""RE6 Switch down/dying survival (the fall, knockdown or dying chain's one change: down at 1 HP, the bot stays
down - no kick, no shot, no rise - #5052). Representative incidents: decision cc_kick (171), raise (110),
tablet (141) while down at 1 HP, all ending in death. The change is in Bot._down_fight: self.down_dying gates
the fight. A down at normal health still fights and rises as before.
"""
import math

import pytest

from gbox.mercs.titles import re6_switch as R


def _snap(action, hp, enemies=(), tablets=0):
    return {
        "player": {
            "ptr": 0x5D00001000, "pos": (0.0, 0.0, 0.0), "rot": 0.0,
            "hp": hp, "hp_max": 900, "motion": 0, "aim_pitch": None,
            "action": action, "state": 3, "tablets": tablets,
        },
        "enemies": [{"ptr": 10 + i, "pos": pos, "hp": ehp, "hp_max": ehp}
                    for i, (pos, ehp) in enumerate(enemies)],
        "inventory": [], "kills": 0, "timer": 120.0, "timer_start": 120.0,
        "laser": {"from": (0.0, 140.0, 30.0), "at": None, "up": False},
    }


def _bot():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock


def _run(bot, clock, snap, ticks, dt=0.05):
    out = []
    for _ in range(ticks):
        clock[0] += dt
        out.append(bot.tick(snap))
    return out


DOWN_ACTION = "cPlAction_pl_act_lying_down_weapon_ready_loop"
DYING_LOOP = "cPlAction_pl_act_dying_loop"
GETUP_ACTION = "cPlAction_pl_act_gets_up"


# --- the change ---------------------------------------------------------------------------------------------------------

def test_dying_down_he_stays_down_and_does_not_kick_the_one_on_him():
    """Incident 1: down at 1 HP, a zombie at 122 cm, decision cc_kick -> death. Now: stay down."""
    b, clock = _bot()
    b.held = lambda p, now: False
    foe = ((120.0, 0.0, 50.0), 700)
    snap = _snap(DOWN_ACTION, 1, enemies=(foe,))
    acts = _run(b, clock, snap, 4)
    assert b.down and b.down_dying
    assert all(a.get("hold") == () for a in acts), f"expected no buttons, got {acts}"
    assert b.stats.get("melee", 0) == 0, "no kick while dying"
    assert b.stats.get("down_shots", 0) == 0, "no shot while dying"
    assert b.stats["act"] == "down_dying_stay"


def test_dying_down_he_stays_down_and_does_not_rise_when_nobody_is_near():
    """Incident: down at 1 HP, nobody near, decision raise -> death. Now: stay down."""
    b, clock = _bot()
    b.held = lambda p, now: False
    snap = _snap(DYING_LOOP, 1, enemies=())
    acts = _run(b, clock, snap, 4)
    assert b.down and b.down_dying
    assert all(a.get("hold") == () for a in acts), f"expected no buttons, got {acts}"
    assert not any("lup" in a.get("hold", ()) for a in acts), "no rise while dying"
    assert b.stats["act"] == "down_dying_stay"


def test_dying_down_he_stays_down_even_with_a_crowd_on_him():
    """Incident: down at 1 HP, 2+ within 2 m, decision bomb_place / cc_quick_shot -> death. Now: stay down."""
    b, clock = _bot()
    b.held = lambda p, now: False
    crowd = (((100.0, 0.0, 0.0), 700), ((150.0, 0.0, 80.0), 700), ((-80.0, 0.0, 60.0), 700))
    snap = _snap(DOWN_ACTION, 1, enemies=crowd)
    acts = _run(b, clock, snap, 4)
    assert b.down and b.down_dying
    assert all(a.get("hold") == () for a in acts), f"expected no buttons, got {acts}"
    assert b.stats["act"] == "down_dying_stay"


def test_dying_down_he_does_not_fire_at_the_one_he_aims_at():
    """Incident: down at 1 HP, decision down_fire / down_aim -> death. Now: no aim, no trigger."""
    b, clock = _bot()
    b.held = lambda p, now: False
    foe = ((400.0, 0.0, 300.0), 700)
    snap = _snap(DOWN_ACTION, 1, enemies=(foe,))
    acts = _run(b, clock, snap, 4)
    assert b.down and b.down_dying
    assert all(a.get("hold") == () for a in acts), f"expected no buttons, got {acts}"
    assert b.stats.get("down_shots", 0) == 0
    assert b.stats["act"] == "down_dying_stay"


# --- regression: a down at normal health still fights and rises ---------------------------------------------------------

def test_a_down_at_normal_health_still_kicks_the_one_on_him():
    b, clock = _bot()
    b.held = lambda p, now: False
    foe = ((120.0, 0.0, 50.0), 700)
    snap = _snap(DOWN_ACTION, 400, enemies=(foe,))
    acts = _run(b, clock, snap, 4)
    assert b.down and not b.down_dying
    assert any(a.get("tap") == "zr" for a in acts), "kick at normal HP while down"
    assert b.stats.get("melee", 0) >= 1


def test_a_down_at_normal_health_still_rises_when_nobody_is_near():
    b, clock = _bot()
    b.held = lambda p, now: False
    snap = _snap(DOWN_ACTION, 400, enemies=())
    acts = _run(b, clock, snap, 4)
    assert b.down and not b.down_dying
    assert any("lup" in a.get("hold", ()) for a in acts), "rise at normal HP when clear"


def test_a_down_at_low_but_not_dying_health_still_fights():
    """HP 100 (not 1): still fights - the gate is exactly DYING_HP."""
    b, clock = _bot()
    b.held = lambda p, now: False
    foe = ((200.0, 0.0, 100.0), 700)
    snap = _snap(DOWN_ACTION, 100, enemies=(foe,))
    acts = _run(b, clock, snap, 4)
    assert b.down and not b.down_dying
    assert any(a.get("hold") for a in acts), "still fighting at 100 HP"
