"""RE5 PS3 / Switch parity, step 1 (gbox.re5_mods_tool routes a Switch session to gbox.mercs.titles.re5_switch_mods):
the same ops and result shape, "not yet on Switch: why" for the rest (the panel's capabilities too), the Mercenaries
loadout templates found through the descriptor table (weapon_override / loadout / the replacements, composed with the
bombs), unlimited health, the `mines` op's cadence for the bot, apply_saved and revert_all."""
import struct
from types import SimpleNamespace

import pytest

from gbox import re5_mods_tool as T
from gbox.mercs.titles import re5_switch as R
from gbox.mercs.titles import re5_switch_mods as SM
from tests.test_re5_switch import BASE
from tests.test_re5_switch_mods import Adapter, chris_template, player, weapon_guest

GENERIC = {3: (0x102, -1, 1), 9: (0x101, -1, 0), 11: (0x100, -1, 0)}           # k: (id, count, in hand)
SAFARI = {0: (0x201, 30, 0), 1: (0x10D, -1, 0), 2: (0x203, 10, 0), 3: (0x111, -1, 1), 5: (0x116, -1, 0),
          7: (0x10D, -1, 0), 9: (0x101, -1, 0), 11: (0x100, -1, 0)}             # descriptor 15, as in main's ELF


@pytest.fixture(autouse=True)
def _fresh_state():
    for cache in (SM.ORIG, R._LASER, R._LASER_MISS, R._NOT_LASER):
        cache.clear()
    yield
    SM.ORIG.clear()


def block_at(i):
    return BASE + 0x1AAD9A8 + 0x270 * (i - 14)


def put_block(g, at, rows):
    for k in range(12):
        idw, count, hand = rows.get(k, (0, -1, 0))
        g.put(at + 0x30 * k, struct.pack("<Ii3iIIII", idw, count, -1, -1, -1, k, hand, 0x0A000005 if idw else 0,
                                         0x200 if hand else 0) + bytes(0xC))


def parity_guest(**kw):
    """weapon_guest plus the loadout descriptors (main+0x1AB6F48): 14 and 24 Chris (BSAA), 15 Chris (Safari), the
    rest a handgun loadout, at main's real block addresses."""
    g = weapon_guest(**kw)
    for i in SM.MERC_DESC:
        at = block_at(i)
        g.put(BASE + SM.DESC_TABLE + SM.DESC_STRIDE * i, struct.pack("<QQQ", at, 0, 12))
        if at - BASE in SM.CHRIS_TEMPLATES:
            chris_template(g, at - BASE)
            g.put(at + 0x30 * 3 + 0x18, struct.pack("<II", 1, 0x0A000005))      # the M92F in hand, its upgrades
        else:
            put_block(g, at, SAFARI if i == 15 else GENERIC)
    return g


def rec(g, i, k):
    return struct.unpack("<Ii3iIIII", g.rd(block_at(i) + 0x30 * k, 0x24))


def ids(g, i):
    return [rec(g, i, k)[0] for k in range(12)]


def test_a_switch_session_goes_to_its_own_mods_with_the_ps3_tools_result_shape(monkeypatch):
    from gbox import tools
    g = parity_guest()
    ad = Adapter(g)
    monkeypatch.setitem(tools.SESSIONS, "lilspark-re5", (ad, {"game_id": "52d15709be0fda1a", "platform": "switch",
                                                              "title": "Resident Evil 5"}))
    out = T.re5_mods(T.RE5ModsIn(session_id="lilspark-re5", op="status"), None)["result"]
    assert out["op"] == "status" and out["edition"] == "switch"
    caps = out["status"]["capabilities"]
    assert caps["weapon_override"]["available"] and caps["unlimited_health"]["available"]
    assert not caps["turn_speed"]["available"] and caps["turn_speed"]["reason"].startswith("not yet on Switch: ")
    out = T.re5_mods(T.RE5ModsIn(session_id="lilspark-re5", op="fire_rate", multiplier=40), None)["result"]
    assert out["op"] == "fire_rate" and out["fire_rate_x"] == 40.0 and out["status"]["fire_rate_x"] == 40.0
    assert T.is_switch_re5({"game_id": "52d15709be0fda1a"}) and T.is_switch_re5({"title_id": "010018100cd46000"})
    assert not T.is_switch_re5({"game_id": "e7ca89bbeb67360d", "platform": "ps3"})


def test_an_op_this_edition_has_not_yet_says_why_and_is_never_a_silent_no_op():
    g = parity_guest()
    ad = Adapter(g)
    for op in ("turn_speed", "add_time", "rotten_egg_only", "mercs_select", "live_weapon", "instant_qte"):
        out = SM.tool_run(ad, op, 3, True)
        assert out["verified"] is False and out["reason"].startswith("not yet on Switch: ") and out["op"] == op
    assert SM.tool_run(ad, "clock", None, True, seconds=60)["op"] == "set_time"            # the PS3's aliases too
    assert ad.writes == []
    with pytest.raises(ValueError, match="unknown op"):
        SM.tool_run(ad, "teleport")


def test_bow_only_puts_the_longbow_in_every_gun_slot_and_keeps_knives_grenades_and_ammo():
    g = parity_guest()
    ad = Adapter(g)
    out = SM.tool_run(ad, "weapon_override", None, True, weapon=0x0F, only=True)
    assert out["verified"] and out["weapon_override"] == {"item": 0x0F, "weapon": "longbow", "only": True}
    assert ids(g, 14) == [0x201, 0x106, 0x203, 0x10F, 0, 0x10F, 0, 0x304, 0, 0x101, 0, 0x100]
    assert ids(g, 15) == [0x201, 0x10F, 0x203, 0x10F, 0, 0x10F, 0, 0x10F, 0, 0x101, 0, 0x100]
    assert rec(g, 14, 3)[7] == 0 and rec(g, 14, 3)[6] == 1                 # upgrades reset, still the one in hand
    assert out["status"]["weapon_override"]["weapon"] == "longbow"
    SM.tool_run(ad, "weapon_override", None, False)                       # off: the game's loadout
    assert ids(g, 14)[3] == 0x102 and ids(g, 15)[1] == 0x10D and rec(g, 14, 3)[7] == 0x0A000005


def test_a_main_gun_override_changes_only_the_gun_in_hand():
    g = parity_guest()
    SM.tool_run(Adapter(g), "weapon_override", None, True, weapon=0x1B)    # the S&W M500
    assert ids(g, 14)[3] == 0x11B and ids(g, 14)[5] == 0x104
    assert ids(g, 15)[3] == 0x11B and ids(g, 15)[1] == 0x10D and ids(g, 20)[3] == 0x11B


def test_the_long_guns_become_magnums_with_their_own_magazine():
    g = parity_guest()
    ad = Adapter(g)
    out = SM.tool_run(ad, "replace_rockets", None, True, seed=7)
    assert out["verified"] and out["rocket_replacements"] == ["0x10d"]
    for k in (1, 7):
        assert rec(g, 15, k)[0] in SM.MAGNUMS and rec(g, 15, k)[1] == -1 and rec(g, 15, k)[7] == 0
    assert ids(g, 15)[3] == 0x111 and ids(g, 14)[3] == 0x102
    assert SM.tool_run(ad, "replace_long_guns", None, True)["weapon_replacements"] == ["0x105", "0x10d", "0x11c",
                                                                                       "0x120"]


def test_the_loadout_draw_is_powerful_without_repeats_and_the_override_wins():
    g = parity_guest()
    ad = Adapter(g)
    out = SM.tool_run(ad, "loadout", None, True, seed=3)
    assert out["verified"] and out["loadout"] == "random powerful campaign weapons"
    guns = [ids(g, 15)[k] for k in (1, 3, 5, 7)]
    assert all(w in SM.POWERFUL and w not in SM.LONG_GUNS for w in guns) and len(set(guns)) == 4
    assert ids(g, 14)[1] == 0x106 and ids(g, 14)[9] == 0x101               # grenades and knives stay
    SM.tool_run(ad, "weapon_override", None, True, weapon=0x0F, only=True)
    assert [ids(g, 15)[k] for k in (1, 3, 5, 7)] == [0x10F] * 4
    SM.tool_run(ad, "loadout", None, False)
    SM.tool_run(ad, "weapon_override", None, False)
    assert ids(g, 15) == [0x201, 0x10D, 0x203, 0x111, 0, 0x116, 0, 0x10D, 0, 0x101, 0, 0x100]


def test_template_ops_and_the_bombs_compose_and_revert_all_puts_every_block_back():
    g = parity_guest()
    ad = Adapter(g)
    SM.run(ad, "mine_loadout", on=True)
    SM.tool_run(ad, "weapon_override", None, True, weapon=0x0F, only=True)
    assert ids(g, 14)[1] == SM.MINE_ID and ids(g, 24)[1] == SM.MINE_ID and ids(g, 14)[3] == 0x10F   # bombs and bows
    SM.tool_run(ad, "weapon_override", None, False)
    assert ids(g, 14)[1] == SM.MINE_ID and ids(g, 14)[3] == 0x102          # the bombs outlive the override
    out = SM.tool_run(ad, "revert_all")
    assert out["verified"] and ids(g, 14)[1] == SM.GRENADE_ID and ids(g, 15)[1] == 0x10D


def test_unlimited_health_refills_a_living_player_to_the_boosted_maximum_never_a_dying_one():
    g = parity_guest()
    ad = Adapter(g)
    hp_at = player(g) + R.P_HP
    g.put(hp_at, struct.pack("<hh", 500, 1000))
    out = SM.tool_run(ad, "unlimited_health", None, True)
    assert out["verified"] and struct.unpack("<hh", g.rd(hp_at, 4)) == (SM.HEALTH_MAX, SM.HEALTH_MAX)
    g.put(hp_at, struct.pack("<hh", 22000, SM.HEALTH_MAX))                 # hit
    snap = R.snapshot(g)
    assert SM.maintain(ad, snap)["writes"] == 1 and snap["player"]["hp"] == SM.HEALTH_MAX
    for dying in (1, 0):                                                   # resuscitation / dead: never written
        g.put(hp_at, struct.pack("<hh", dying, SM.HEALTH_MAX))
        assert SM.maintain(ad, R.snapshot(g))["writes"] == 0
    g.put(hp_at, struct.pack("<hh", 20000, SM.HEALTH_MAX))
    assert SM.tool_run(ad, "unlimited_health", None, False)["restored"]
    assert struct.unpack("<hh", g.rd(hp_at, 4)) == (1000, 1000)            # his own maximum back
    assert SM.maintain(ad, R.snapshot(g))["writes"] == 0


def test_the_mines_op_sets_the_bots_cadence_through_the_driver_and_can_switch_placements_off():
    g = parity_guest()
    ad = Adapter(g)
    out = SM.tool_run(ad, "mines", 15, True)
    assert out["verified"] and out["mine_settings"] == {"enabled": True, "interval_s": 15.0, "only": False}
    assert ids(g, 14)[1] == SM.MINE_ID and SM.mine_settings(ad)["interval_s"] == 15.0
    assert "not yet on Switch" in SM.tool_run(ad, "mines", "only", True)["note"]
    snap = R.snapshot(g)
    R.RE5Switch()._mods(SimpleNamespace(adapter=ad), snap, True)
    assert snap["mine_settings"] == {"enabled": True, "interval_s": 9.0, "only": False}   # ("only": the default S)
    from gbox.mercs.titles import re5_switch_mines as MN
    m = MN.Mines({})
    m.configure({"enabled": False, "interval_s": 30})
    m.new_round(0.0)
    inv = [{"slot": 1, "id": 0x10A, "type": 1, "item": 0x0A, "rounds": 5, "cap": 5, "grid": 1, "hand": False}]
    assert m.every_s == 30.0 and m.due({"pos": (0.0, 0.0, 0.0)}, {"inventory": inv}, [], 99.0) is None


def test_apply_saved_answers_each_item_with_its_own_reason():
    g = parity_guest()
    out = SM.apply_saved(Adapter(g), [{"op": "fire_rate", "multiplier": 80, "on": True},
                                      {"op": "turn_speed", "multiplier": 3, "on": True},
                                      {"op": "weapon_override", "weapon": 15, "only": True, "name": "bow"}])
    assert out["results"]["fire_rate"]["verified"] and out["results"]["bow"]["verified"]
    assert out["results"]["turn_speed"]["reason"].startswith("not yet on Switch: ") and out["verified"] is False
