"""RE5 Switch 5 m rampage (operator 2026-10-27 16:05: "They need to be blasting continuously until the threat is
resolved. I dont want them raising the gun and putting it down"; 16:12: "whipping their view around ... pointing the
gun at threats that aren't even on screen"): with a Majini within 5 m the gun comes up at once and the trigger stays
down, the nearest inside is held (a grab-range one takes over), one close behind gets one quick turn, the shotgun
goes up first and stays equipped after, no unaim inside, and the counters."""
import math

import pytest

from gbox.mercs.titles import re5_switch as R

MUZZLE = (0.0, 140.0, 30.0)


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)
    monkeypatch.setattr(R, "RAMPAGE", True)              # off in MercMode since 16:45 (it spun between foes); the code is kept
    monkeypatch.setattr(R, "QUICK_TURN", True)           # (off since 18:52: the heading governor)


def at(dist, deg, y=0.0):
    a = math.radians(deg)
    return (dist * math.sin(a), y, dist * math.cos(a))


def chest(foot):
    return (foot[0], foot[1] + R.CHEST_H, foot[2])


M92F = {"slot": 0, "id": 0x102, "type": 1, "item": 0x02, "rounds": 15, "cap": 15, "grid": 3, "hand": True}
SHOTGUN = {"slot": 1, "id": 0x104, "type": 1, "item": 0x04, "rounds": 6, "cap": 6, "grid": 5, "hand": False}


def snap(enemies, dot=None, motion=0, inv=None, kills=None):
    return {"player": {"ptr": 0x5D00001000, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000,
                       "motion": motion},
            "enemies": [{"ptr": 10 + i, "pos": x, "hp": 800, "hp_max": 800} for i, x in enumerate(enemies)],
            "inventory": inv or [], "kills": kills,
            "laser": {"from": MUZZLE, "at": dot, "up": True} if dot else {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}


def bot():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock


def test_one_within_5_m_the_gun_comes_up_and_the_trigger_is_down_from_the_first_tick():
    b, clock = bot()
    foe = at(350, 20)                                              # 20 deg off: no body turn first
    act = b.tick(snap([foe]))
    assert {"zl", "zr"} <= set(act["hold"]) and b.doing == "fire" and b.stats["rampage_shots"] == 1
    clock[0] = 0.3
    act = b.tick(snap([foe], dot=(300.0, 150.0, 800.0), motion=26))    # the dot far off him: still blasting
    assert {"zl", "zr"} <= set(act["hold"]) and b.doing == "fire" and b.stats["unaims_in_5m"] == 0
    assert b.stats["idle_in_5m_s"] == 0 and b.stats["rampage_s"] > 0


def test_one_close_behind_gets_one_quick_turn_then_the_gun_up():
    b, clock = bot()
    behind = at(200, 170)
    act = b.tick(snap([behind]))
    assert act["hold"] == ("ldown",) and b.quick == 2 and b.stats["behind_turns"] == 1


def test_the_shotgun_stays_equipped_after_the_crowd_clears():
    b, clock = bot()
    foe = at(300, 0)
    act = b.tick(snap([foe], inv=[M92F, SHOTGUN]))
    assert act["hold"] == ("dright",) and b.stats["rampage_swaps"] == 1 and b.stats["rampage_weapon"] == "shotgun"
    held = [dict(M92F, hand=False), dict(SHOTGUN, hand=True)]
    clock[0] = 0.2
    act = b.tick(snap([foe], inv=held))
    assert {"zl", "zr"} <= set(act["hold"])
    clock[0] = 0.5
    b.tick(snap([], inv=held))                                     # the circle clear: the gun down first
    b._gun_down()
    clock[0] = 1.8
    act = b.tick(snap([], inv=held))
    assert not set(act.get("hold", ())) & set(R.QUICK.values())
    assert b.stats["rampage_swaps"] == 1 and b._restore is None


@pytest.mark.parametrize("held_item", [0x04, 0x17])
@pytest.mark.parametrize("held_grid", [5, 4])
def test_crowd_keeps_the_shotgun_in_hand_even_when_another_shotgun_is_first(held_item, held_grid):
    b, clock = bot()
    held = dict(SHOTGUN, slot=2, id=0x100 | held_item, item=held_item, grid=held_grid, hand=True)
    inv = [dict(SHOTGUN, grid=1), held]
    assert b._rampage_gun(inv) == (held, "shotgun")
    foe = at(300, 0)
    act = b.tick(snap([foe], inv=inv))
    assert {"zl", "zr"} <= set(act["hold"])
    assert not set(act["hold"]) & set(R.QUICK.values())
    assert b.stats["rampage_swaps"] == 0
    clock[0] = 0.3
    act = b.tick(snap([foe], inv=inv, motion=26, dot=chest(foe)))
    assert {"zl", "zr"} <= set(act["hold"])
    assert b.stats["rampage_swaps"] == 0


def test_the_target_inside_is_held_and_only_a_grab_range_one_takes_over():
    b, clock = bot()
    a, c = at(300, 0), at(400, 30)
    b.tick(snap([a, c]))
    assert b.target == 10
    clock[0] = 0.2
    b.tick(snap([a, at(220, 30)]))                                 # the other comes nearer: still the first
    assert b.target == 10
    clock[0] = 0.9
    b.tick(snap([a, at(90, 30)]))                                  # within grab range: him at once
    assert b.target == 11


def test_a_turn_reversed_within_a_second_is_a_whip():
    b, clock = bot()
    for t, deg in ((0.0, 0), (0.1, 40), (0.2, 80), (0.3, 110), (0.5, 80), (0.7, 50)):
        b._watch_whips({"rot": math.radians(deg)}, t)
    assert b.stats["whips"] == 1
    b2, _ = bot()
    for t, deg in ((0.0, 0), (0.1, 40), (0.2, 80), (0.3, 110), (2.0, 80), (2.2, 50)):
        b2._watch_whips({"rot": math.radians(deg)}, t)
    assert b2.stats["whips"] == 0


def test_kills_during_the_rampage_are_counted():
    b, clock = bot()
    foe = at(300, 0)
    b.tick(snap([foe, at(350, 10)], kills=5))
    clock[0] = 0.3
    b.tick(snap([at(350, 10)], kills=6, dot=chest(at(350, 10)), motion=26))
    assert b.stats["rampage_kills"] == 1


def _block(records):
    import struct
    from gbox.mercs.titles import re5_switch_mods as SM
    t = bytearray(SM.TEMPLATE_REC * SM.TEMPLATE_RECS)
    for k, (idw, count, grid, hand) in enumerate(records):
        o = k * SM.TEMPLATE_REC
        struct.pack_into("<I", t, o + SM.REC_ID, idw)
        struct.pack_into("<i", t, o + SM.REC_COUNT, count)
        struct.pack_into("<I", t, o + SM.REC_GRID, grid)
        struct.pack_into("<I", t, o + SM.REC_HAND, hand)
    return t


def test_the_rampage_loadout_puts_a_shotgun_on_a_d_pad_slot_where_none_is():
    import struct
    from gbox.mercs.titles import re5_switch_mods as SM
    t = _block([(0x201, 50, 0, 0), (0x106, 5, 1, 0), (0x102, 15, 3, 1), (0x103, 10, 5, 0), (0x304, 1, 7, 0)])
    assert SM._rampage_block(t)
    assert struct.unpack_from("<I", t, 3 * SM.TEMPLATE_REC + SM.REC_ID)[0] == SM.RAMPAGE_GUN       # not the hand gun
    assert struct.unpack_from("<I", t, 2 * SM.TEMPLATE_REC + SM.REC_ID)[0] == 0x102
    assert struct.unpack_from("<I", t, 1 * SM.TEMPLATE_REC + SM.REC_ID)[0] == 0x106                # grenades kept
    chris = _block([(0x201, 50, 0, 0), (0x10A, 5, 1, 0), (0x102, 15, 3, 1), (0x104, 6, 5, 0), (0x304, 1, 7, 0)])
    assert not SM._rampage_block(chris)                          # the Ithaca M37 on the D-pad already


def test_the_profile_plays_the_rampage_loadout():
    import json
    import pathlib
    prof = json.loads(pathlib.Path("profiles/gamedata/010018100CD46000-ram.json").read_text(encoding="utf-8"))
    ops = [o[0] for o in prof["mercs"]["playing_ops"]]
    assert {"infinite_ammo", "fire_rate", "rampage_loadout"} <= set(ops)
