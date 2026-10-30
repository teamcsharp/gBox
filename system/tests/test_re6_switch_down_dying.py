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


# --- the felling guard: down at low health, a melee wind-up near -------------------------------------------------------

def _winding_enemy(pos, ehp=700, action="cPlAction_zombie_Attack_ex"):
    """An enemy in a melee wind-up (the action name contains an WINDUP_KEY)."""
    return {"ptr": 99, "pos": pos, "hp": ehp, "hp_max": ehp, "action": action}


def test_down_at_low_health_with_a_melee_windup_stays_down():
    """Incident 2/4/5: getting up (3.85 m) -> felled 900->1, 862->1. Down at low HP
    with one winding up a melee strike: stay down until it swings through."""
    b, clock = _bot()
    b.held = lambda p, now: False
    # hp 300 (<= SURVIVAL_HP*900 = 315), a melee wind-up within WINDUP_R (500 cm)
    snap = _snap(DOWN_ACTION, 300, enemies=())
    snap["enemies"] = [_winding_enemy((300.0, 0.0, 100.0))]
    acts = _run(b, clock, snap, 4)
    assert b.down and not b.down_dying, "down but not dying (hp 300 > 1)"
    assert all(a.get("hold") == () for a in acts), f"expected no buttons, got {acts}"
    assert not any(a.get("tap") == "zr" for a in acts), "no kick while a wind-up is near"
    assert not any("lup" in a.get("hold", ()) for a in acts), "no rise while a wind-up is near"
    assert b.stats["act"] == "down_windup_hold"
    assert b.stats.get("melee", 0) == 0
    assert b.stats.get("down_shots", 0) == 0


def test_down_at_low_health_stays_down_until_the_windup_clears():
    """Once the wind-up enemy is gone, the bot resumes its normal down behaviour
    (kick or rise) - the guard is scoped to the wind-up, not a permanent hold."""
    b, clock = _bot()
    b.held = lambda p, now: False
    # wind-up enemy at 300 cm
    snap_wind = _snap(DOWN_ACTION, 300, enemies=())
    snap_wind["enemies"] = [_winding_enemy((300.0, 0.0, 100.0))]
    # after the wind-up: enemy in a neutral action, no longer winding up
    snap_clear = _snap(DOWN_ACTION, 300, enemies=())
    snap_clear["enemies"] = [{"ptr": 99, "pos": (300.0, 0.0, 100.0), "hp": 700,
                              "hp_max": 700, "action": "cPlAction_zombie_walk"}]
    acts_wind = _run(b, clock, snap_wind, 4)
    assert all(a.get("hold") == () for a in acts_wind), "stay down while winding"
    assert b.stats["act"] == "down_windup_hold"
    # after clear: the bot resumes fighting (aims and fires at the neutral enemy)
    acts_clear = _run(b, clock, snap_clear, 4)
    assert any(a.get("hold") for a in acts_clear), "resumes fighting once the wind-up clears"
    assert b.stats["act"] != "down_windup_hold", "guard released once the wind-up clears"


def test_down_at_full_health_with_a_melee_windup_still_fights():
    """hp 900 (> SURVIVAL_HP*900 = 315): the guard does not trigger; normal
    down fight resumes (kick or fire)."""
    b, clock = _bot()
    b.held = lambda p, now: False
    snap = _snap(DOWN_ACTION, 900, enemies=())
    snap["enemies"] = [_winding_enemy((300.0, 0.0, 100.0))]
    acts = _run(b, clock, snap, 4)
    assert b.down and not b.down_dying
    # full health: the wind-up guard is inactive, so the bot fights (fires at 300 cm)
    assert b.stats["act"] != "down_windup_hold", "full HP: no wind-up hold"
    assert any(a.get("hold") for a in acts), "fights at full HP even with a wind-up"


def test_down_at_dying_hp_still_stays_down_with_a_windup():
    """hp 1 (dying): the dying guard takes precedence; the wind-up guard is
    redundant here but both agree on stay down."""
    b, clock = _bot()
    b.held = lambda p, now: False
    snap = _snap(DOWN_ACTION, 1, enemies=())
    snap["enemies"] = [_winding_enemy((300.0, 0.0, 100.0))]
    acts = _run(b, clock, snap, 4)
    assert b.down and b.down_dying
    assert b.stats["act"] == "down_dying_stay", "dying guard fires first"
    assert all(a.get("hold") == () for a in acts)
