"""RE5 Switch crowd fire (operator 19:25: "They should have pulled out their shotgun and did crowd control"; 19:5x:
"give the bot rapid fire shotguns for crowd control ... this bot is swarmed and is barely shooting"): three within 5 m
or one within 2 m - the shotgun up, the trigger with the aim on them, the aim turned to the nearest in front between
shots only, never an unaim with anyone within 5 m."""
import math

import pytest

from gbox.mercs.titles import re5_switch as R

MUZZLE = (0.0, 140.0, 30.0)
M92F = {"slot": 0, "id": 0x102, "type": 1, "item": 0x02, "rounds": 15, "cap": 15, "grid": 3, "hand": True}
SHOTGUN = {"slot": 1, "id": 0x104, "type": 1, "item": 0x04, "rounds": 6, "cap": 6, "grid": 5, "hand": False}


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)
    monkeypatch.setattr(R, "MINES", False)
    monkeypatch.setattr(R, "CALM", False)                         # (the calm budget's coasting is tested on its own)


def at(dist, deg, y=0.0):
    a = math.radians(deg)
    return (dist * math.sin(a), y, dist * math.cos(a))


def chest(foot):
    return (foot[0], foot[1] + R.CHEST_H, foot[2])


def snap(enemies, dot=None, motion=0, inv=None, aim_pitch=None, kills=0):
    return {"player": {"ptr": 0x5D00001000, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000,
                       "motion": motion, "aim_pitch": aim_pitch},
            "enemies": [{"ptr": 10 + i, "pos": x, "hp": 800, "hp_max": 800} for i, x in enumerate(enemies)],
            "inventory": inv if inv is not None else [], "kills": kills,
            "laser": {"from": MUZZLE, "at": dot, "up": True} if dot else {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}


def bot():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock


CROWD = [at(250, 5), at(350, 60), at(300, -100)]


def test_three_within_5_m_put_the_shotgun_up_first():
    b, clock = bot()
    act = b.tick(snap(CROWD, inv=[M92F, SHOTGUN]))
    assert act["hold"] == ("dright",) and b.stats["shotgun_swaps"] == 1 and b.stats["rampage_weapon"] == "shotgun"


def test_with_the_aim_on_the_nearest_in_front_the_trigger_holds_and_no_stick():
    b, clock = bot()
    held = [dict(M92F, hand=False), dict(SHOTGUN, hand=True)]
    b.tick(snap(CROWD, inv=held))
    clock[0] = 0.2
    act = b.tick(snap(CROWD, dot=chest(CROWD[0]), motion=26, inv=held))
    assert {"zl", "zr"} <= set(act["hold"]) and not {"rleft", "rright"} & set(act["hold"])
    assert b.target == 10 and b.stats["crowd_fire_s"] > 0


def test_the_aim_off_them_lets_the_trigger_go_and_turns_between_shots_only():
    b, clock = bot()
    held = [dict(M92F, hand=False), dict(SHOTGUN, hand=True)]
    b.tick(snap(CROWD, inv=held))
    off = (-1500.0, 140.0, 2500.0)                                 # the dot 31 deg right of the one in front
    clock[0] = 0.2
    act = b.tick(snap(CROWD, dot=off, motion=29, inv=held))        # the shot still playing: no stick
    assert "zr" not in act["hold"] and not {"rleft", "rright"} & set(act["hold"]) and "zl" in act["hold"]
    clock[0] = 0.25
    act = b.tick(snap(CROWD, dot=off, motion=26, inv=held))
    assert "rleft" in act["hold"] and "zr" not in act["hold"] and b.doing == "aim"


def test_one_within_2_m_alone_is_crowd_fire():
    b, clock = bot()
    b.tick(snap([at(150, 10)]))
    assert b.stats["crowd_fire_s"] >= 0 and b._ramp is not None and b.aim_since is not None


def test_two_at_3_m_are_not_crowd_fire_but_the_gun_never_goes_down():
    b, clock = bot()
    pair = [at(300, 0), at(350, 30)]
    b.tick(snap(pair))
    assert b._ramp is None
    clock[0] = 0.3
    act = b.tick(snap(pair, dot=(2000.0, 140.0, -500.0), motion=26))   # the aim far off them
    assert "zl" in act["hold"] and b.stats["unaims_in_5m"] == 0 and b.stats["unaims"] == 0


def test_once_on_it_stays_while_anyone_is_within_5_m_then_the_main_gun_comes_back():
    b, clock = bot()
    held = [dict(M92F, hand=False), dict(SHOTGUN, hand=True)]
    b.tick(snap(CROWD, inv=[M92F, SHOTGUN]))
    clock[0] = 0.2
    b.tick(snap(CROWD, inv=held))
    clock[0] = 0.4
    b.tick(snap([at(450, 0)], dot=chest(at(450, 0)), motion=26, inv=held))
    assert b._ramp is not None and b.doing == "fire"               # one left inside: still on
    clock[0] = 0.6
    b.tick(snap([at(900, 0)], inv=held))
    assert b._ramp is None


def test_the_aim_pitch_is_held_on_a_chest():
    b, clock = bot()
    held = [dict(M92F, hand=False), dict(SHOTGUN, hand=True)]
    b.tick(snap(CROWD, inv=held))
    clock[0] = 0.3
    act = b.tick(snap(CROWD, dot=chest(CROWD[0]), motion=26, inv=held, aim_pitch=-0.4))
    assert "rdown" in act["hold"] and "rup" not in act["hold"]


def test_with_one_near_a_far_one_is_never_the_target_nor_shot():
    b, clock = bot()
    near, far = at(400, 50), at(1200, 0)                           # the far one straight ahead, the near one aside
    b.tick(snap([near, far]))
    assert b.target == 10
    clock[0] = 0.3
    act = b.tick(snap([near, far], dot=chest(far), motion=26))    # the dot lands on the far one
    assert "zr" not in act["hold"] and b.target == 10 and b.stats["far_picks_while_crowded"] == 0
    assert b.stats["confirmed_shots"] == 0


def test_the_crowds_gun_is_a_shotgun_else_an_automatic_else_a_magnum():
    b, _ = bot()
    gatling = {"slot": 2, "id": 0x115, "type": 1, "item": 0x15, "rounds": 100, "cap": 100, "grid": 7, "hand": False}
    magnum = {"slot": 3, "id": 0x10B, "type": 1, "item": 0x0B, "rounds": 6, "cap": 6, "grid": 1, "hand": False}
    assert b._rampage_gun([magnum, gatling])[1] == "automatic"
    assert b._rampage_gun([magnum, gatling, SHOTGUN])[1] == "shotgun"
    assert b._rampage_gun([magnum])[1] == "magnum"
