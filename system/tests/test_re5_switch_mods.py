"""RE5 Switch live mods (gbox.mercs.titles.re5_switch_mods) on the fake guest of tests/test_re5_switch.py: the weapon
table's no-ammo flags with their originals, fire_rate's time scale only while the shot motion plays, the driver's
per-snapshot upkeep and release, mercs_bot's package dispatch and the profile's playing_ops."""
import struct

import pytest

from gbox import mercs_bot, ram_map
from gbox.mercs.titles import re5_switch_mods as SM
from gbox.mercs.titles import re5_switch as R
from tests.test_re5_switch import BASE, round_guest

NAMES = {0x00: "WP00 NONE", 0x01: "WP01 KNIFE_CHRIS", 0x02: "WP02 HAND_M92F", 0x03: "WP03 MACHINE_SCORPION",
         0x06: "WP06 GRENADE_NORMAL", 0x15: "WP15 MACHINE_GATLING", 0x18: "WP18 Empty18", 0x22: "WP22 STUNROD"}
GUNS, NOT_GUNS = (0x02, 0x03, 0x06, 0x15), (0x00, 0x01, 0x18, 0x22)


@pytest.fixture(autouse=True)
def _fresh_state():
    for cache in (SM.ORIG, R._LASER, R._LASER_MISS, R._NOT_LASER):
        cache.clear()
    yield
    SM.ORIG.clear()


class Adapter:
    """The Switch adapter's memory interface over a fake guest (NCE: a guest address is the host address)."""
    address_mode = "direct"

    def __init__(self, g):
        self.g, self.writes = g, []

    def _guest(self):
        return 1, {"mapped": self.g.rows(), "base": 0}

    def read_memory(self, a, n):
        return self.g.rd(a, n)

    def write_memory(self, a, data):
        self.g.put(a, bytes(data))
        self.writes.append((a, bytes(data)))
        assert self.g.rd(a, len(data)) == bytes(data)
        return {"address": a, "written": len(data), "verified": True}


def weapon_guest(names=NAMES, **kw):
    g = round_guest(**kw)
    for wid, name in names.items():
        at = BASE + 0x1900000 + 0x40 * wid
        g.put(at, name.encode() + b"\0")
        g.q(BASE + SM.DEF_TABLE + SM.DEF_STRIDE * wid + SM.DEF_NAME, at)
    g.i32(BASE + SM.DEF_TABLE + SM.DEF_STRIDE * 0x15 + SM.DEF_NOAMMO, 1)    # the Gatling's own flag
    if kw.get("player", True):
        g.put(player(g) + SM.P_TIME_SCALE, struct.pack("<f", 1.0))
    return g


def player(g):
    return R.snapshot(g)["player"]["ptr"]


def flag(g, wid):
    return struct.unpack("<I", g.rd(BASE + SM.DEF_TABLE + SM.DEF_STRIDE * wid + SM.DEF_NOAMMO, 4))[0]


def scale(g, ptr=None):
    return struct.unpack("<f", g.rd((ptr or player(g)) + SM.P_TIME_SCALE, 4))[0]


def snap_of(g, motion):
    snap = R.snapshot(g)
    snap["player"] = dict(snap["player"], motion=motion)
    return snap


def test_infinite_ammo_flags_every_gun_and_puts_the_originals_back():
    g = weapon_guest()
    ad = Adapter(g)
    res = SM.run(ad, "infinite_ammo", on=True)
    assert res["verified"] and res["weapons"] == len(GUNS)
    assert all(flag(g, w) == 1 for w in GUNS) and all(flag(g, w) == 0 for w in NOT_GUNS)
    assert SM.run(ad, "status")["infinite_ammo"] is True
    SM.run(ad, "ammo", on=False)                                       # an alias
    assert flag(g, 0x02) == flag(g, 0x03) == flag(g, 0x06) == 0 and flag(g, 0x15) == 1   # the Gatling keeps its own


def test_the_weapon_table_must_match_this_build():
    g = weapon_guest(names={0x00: "WP00 NONE"})
    with pytest.raises(RuntimeError, match="does not match this build"):
        SM.RE5Switch(Adapter(g))


def test_fire_rate_scales_the_player_only_while_his_shot_plays():
    g = weapon_guest()
    ad = Adapter(g)
    assert SM.run(ad, "fire_rate", multiplier=80)["fire_rate_x"] == 80.0
    assert SM.maintain(ad, snap_of(g, 26))["active"] is False and scale(g) == 1.0      # aiming: the game's pace
    out = SM.maintain(ad, snap_of(g, SM.MOTION_SHOT))
    assert out["active"] and out["writes"] == 1 and scale(g) == 80.0               # a shot: x80
    assert SM.maintain(ad, snap_of(g, SM.MOTION_SHOT))["writes"] == 0              # once
    assert SM.maintain(ad, snap_of(g, 26))["writes"] == 1 and scale(g) == 1.0      # the shot ended: back
    SM.maintain(ad, snap_of(g, SM.MOTION_SHOT))
    assert SM.maintain(ad, snap_of(g, SM.MOTION_SHOT), enabled=False)["writes"] == 1 and scale(g) == 1.0
    with pytest.raises(ValueError):
        SM.run(ad, "fire_rate", multiplier=200)


def test_a_raised_scale_is_never_written_into_a_player_the_round_freed():
    g = weapon_guest()
    ad = Adapter(g)
    SM.run(ad, "fire_rate", multiplier=8)
    old = player(g)
    SM.maintain(ad, snap_of(g, SM.MOTION_SHOT))
    assert scale(g, old) == 8.0
    snap = snap_of(g, 26)
    snap["player"]["ptr"] = old + 0x10000                              # the next round's player
    n = len(ad.writes)
    assert SM.maintain(ad, snap)["writes"] == 0 and len(ad.writes) == n
    assert "scaled" not in SM.ORIG[id(ad)]
    assert SM.maintain(ad, {"player": None})["writes"] == 0            # out of a round: nothing to write


def test_a_slow_motion_moment_is_left_alone():
    g = weapon_guest()
    ad = Adapter(g)
    SM.run(ad, "fire_rate", multiplier=80)
    g.put(player(g) + SM.P_TIME_SCALE, struct.pack("<f", 0.25))       # the game's own pace is not 1.0 right now
    assert SM.maintain(ad, snap_of(g, SM.MOTION_SHOT))["writes"] == 0 and scale(g) == 0.25


def test_maintain_puts_back_no_ammo_flags_the_game_reset():
    g = weapon_guest()
    ad = Adapter(g)
    SM.run(ad, "infinite_ammo", on=True)
    g.i32(BASE + SM.DEF_TABLE + SM.DEF_STRIDE * 0x02 + SM.DEF_NOAMMO, 0)
    out = SM.maintain(ad, snap_of(g, 26), clock=lambda: 1000.0)
    assert out["ammo_restored"] is True and flag(g, 0x02) == 1


def test_the_driver_keeps_the_mods_from_its_snapshot_and_lets_go_when_the_bot_stops():
    g = weapon_guest(motion=SM.MOTION_SHOT)
    ad = Adapter(g)
    SM.run(ad, "fire_rate", multiplier=8)
    m = SM.Mem(ad)
    drv = R.RE5Switch()
    stats = {}
    bot = drv.brain(m, stats, clock=lambda: 0.0)
    assert drv.screen(m, R.snapshot(m)) == "playing"
    assert scale(g) == 8.0 and stats["rapid_fire_active"] is True and stats["mod_writes"] == 1
    bot.save()                                                         # the engine's finally: the game's pace back
    assert scale(g) == 1.0
    m.mercs_no_modifications = True                                    # a second player's view: no writes at all
    n = len(ad.writes)
    drv.screen(m, R.snapshot(m))
    assert len(ad.writes) == n


def test_mercs_bot_routes_the_switch_profile_to_re5_switch_mods():
    g = weapon_guest()
    ad = Adapter(g)
    prof = {"map_id": "010018100CD46000", "platform": "switch"}
    failed = mercs_bot.apply_ops(ad, [("infinite_ammo", {"on": True}), ("fire_rate", {"multiplier": 80})], prof)
    assert failed == [] and flag(g, 0x02) == 1 and SM.ORIG[id(ad)]["fire_rate"] == 80.0
    failed = mercs_bot.apply_ops(ad, [("nonsense", {})], prof)
    assert len(failed) == 1 and failed[0].startswith("nonsense: re5_mods on Switch: unknown op 'nonsense' (")
    assert "weapon_override" in failed[0] and "mines" in failed[0]               # the PS3 tool's ops, listed


def test_the_profile_turns_the_mods_and_the_bombs_on_when_a_round_starts():
    rm = ram_map.find({"game_id": "52d15709be0fda1a", "platform": "switch"})
    assert rm.spec["mercs"]["playing_ops"] == [["infinite_ammo", {"on": True}], ["fire_rate", {"multiplier": 80}],
                                               ["mine_loadout", {"on": True}]]


def put_slot(g, k, idw, rounds, grid, hand=0, obj=0x5D4DDE4740):
    slot = player(g) + R.P_INV + R.INV_SLOT * k
    g.put(slot + R.INV_ID, struct.pack("<I", idw))
    g.put(slot + R.INV_ROUNDS, struct.pack("<ii", rounds, rounds))
    g.put(slot + R.INV_GRID, struct.pack("<ii", grid, hand))
    g.put(slot + R.INV_OBJ, struct.pack("<Q", obj if idw else 0))
    return slot


def count_cap(g, slot):
    return struct.unpack("<ii", g.rd(slot + R.INV_ROUNDS, 8))


def test_infinite_spray_keeps_the_live_spray_at_two_and_writes_nothing_else():
    g = weapon_guest()
    ad = Adapter(g)
    put_slot(g, 0, 0x102, 50, 3, hand=1)
    slot = put_slot(g, 2, SM.SPRAY_ID, 1, 7)
    assert SM.run(ad, "auto_first_aid", on=True)["infinite_spray"] is True
    out = SM.maintain(ad, R.snapshot(g))
    assert out["writes"] == 1 and out["spray_kept"] is True and count_cap(g, slot) == (SM.SPRAY_KEEP, SM.SPRAY_KEEP)
    assert ad.writes[-1][0] == slot + R.INV_ROUNDS and len(ad.writes[-1][1]) == 8      # the two ints only
    assert SM.maintain(ad, R.snapshot(g))["writes"] == 0                             # already at two
    put_slot(g, 2, SM.SPRAY_ID, 0, 7, hand=1)                                         # a use under way (count 0)
    assert SM.maintain(ad, R.snapshot(g))["writes"] == 0
    put_slot(g, 2, 0, 0, 13)                                                          # the game cleared it: never
    assert SM.maintain(ad, R.snapshot(g))["writes"] == 0
    put_slot(g, 2, SM.SPRAY_ID, 1, 7, obj=0)                                          # no item object: never
    assert SM.maintain(ad, R.snapshot(g))["writes"] == 0
    put_slot(g, 2, SM.SPRAY_ID, 1, 7)
    SM.run(ad, "infinite_spray", on=False)
    assert SM.maintain(ad, R.snapshot(g))["writes"] == 0
    spray_writes = [(a, d) for a, d in ad.writes if slot <= a < slot + R.INV_SLOT]
    assert spray_writes and all(slot + R.INV_ROUNDS <= a and a + len(d) <= slot + R.INV_CAP + 4
                                for a, d in spray_writes)               # the count / capacity ints, never a pointer
    assert not [a for a, d in ad.writes if player(g) + R.P_INV <= a < player(g) + R.P_INV + R.INV_SLOT * R.INV_SLOTS
                and not slot <= a < slot + R.INV_SLOT]                   # never another (or an empty) slot


def chris_template(g, off, rec1=0x106):
    """Chris (BSAA)'s loadout block as read live 2026-10-27 (12 records of 0x30)."""
    rows = {0: (0x201, 50, 0), 1: (rec1, 5, 1), 2: (0x203, 30, 2), 3: (0x102, -1, 3), 5: (0x104, -1, 5),
            7: (0x304, -1, 7), 9: (0x101, -1, 9), 11: (0x100, -1, 11)}
    for k in range(12):
        idw, count, grid = rows.get(k, (0, -1, k))
        g.put(BASE + off + 0x30 * k, struct.pack("<Ii3iI", idw, count, -1, -1, -1, grid) + bytes(0x18))


def test_mine_loadout_gives_chris_the_proximity_bomb_in_both_banks_and_takes_it_back():
    g = weapon_guest()
    for off in SM.CHRIS_TEMPLATES:
        chris_template(g, off)
    ad = Adapter(g)
    res = SM.run(ad, "mine_loadout", on=True)
    assert res["verified"] and res["blocks"] == [hex(o) for o in SM.CHRIS_TEMPLATES]
    for off in SM.CHRIS_TEMPLATES:
        rec = struct.unpack("<Ii3iI", g.rd(BASE + off + 0x30, 24))
        assert rec == (SM.MINE_ID, 5, -1, -1, -1, 1)                  # the bomb x5 at grid 1, nothing else moved
    assert all(a in (BASE + o + 0x30 for o in SM.CHRIS_TEMPLATES) and len(d) == 4 for a, d in ad.writes)
    assert SM.run(ad, "mine_loadout", on=True)["verified"] and len(ad.writes) == 2   # already: no new write
    assert SM.run(ad, "mine_loadout", on=False)["verified"]
    assert struct.unpack("<I", g.rd(BASE + SM.CHRIS_TEMPLATES[0] + 0x30, 4))[0] == SM.GRENADE_ID


def test_mine_loadout_writes_nothing_where_the_block_is_not_chriss():
    g = weapon_guest()
    chris_template(g, SM.CHRIS_TEMPLATES[0])
    g.put(BASE + SM.CHRIS_TEMPLATES[0] + 0x30 * 3, struct.pack("<I", 0x111))      # another costume's gun at grid 3
    ad = Adapter(g)
    res = SM.run(ad, "mine_loadout", on=True)
    assert not res["verified"] and res["blocks"] == [] and ad.writes == []
