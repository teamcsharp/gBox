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
def _mechanics_at_any_multiplier(monkeypatch):
    monkeypatch.setattr(SM, "FIRE_MAX", 80.0)       # play caps it at 5x (2026-10-28); the mechanics at any multiplier


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
    par = g.alloc(0x600)                                                   # sParameter, its turn and aim rates
    g.q(BASE + SM.S_PARAM_PTR, par)
    for off, (_name, value) in SM.TURN.items():
        g.put(par + off, struct.pack("<f", value))
    for wid, fp in ((0x02, 150.0), (0x04, 300.0)):                         # the firepower groups (levels 0-5)
        g.put(BASE + SM.UPG_TABLE + SM.UPG_STRIDE * wid + SM.UPG_GROUP0,
              struct.pack("<14f", *[fp + 20 * k for k in range(6)], *[1.0] * 8))
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
    assert not caps["instant_qte"]["available"] and caps["instant_qte"]["reason"].startswith("not yet on Switch: ")
    out = T.re5_mods(T.RE5ModsIn(session_id="lilspark-re5", op="fire_rate", multiplier=40), None)["result"]
    assert out["op"] == "fire_rate" and out["fire_rate_x"] == 40.0 and out["status"]["fire_rate_x"] == 40.0
    assert T.is_switch_re5({"game_id": "52d15709be0fda1a"}) and T.is_switch_re5({"title_id": "010018100cd46000"})
    assert not T.is_switch_re5({"game_id": "e7ca89bbeb67360d", "platform": "ps3"})


def test_an_op_this_edition_has_not_yet_says_why_and_is_never_a_silent_no_op():
    g = parity_guest()
    ad = Adapter(g)
    for op in ("live_weapon", "instant_qte"):
        out = SM.tool_run(ad, op, 3, True)
        assert out["verified"] is False and out["reason"].startswith("not yet on Switch: ") and out["op"] == op
    assert SM.tool_run(ad, "qte_assist", None, True)["op"] == "instant_qte"               # the PS3's aliases too
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


def test_the_loadout_is_drawn_again_for_every_round_when_each_round_is_on():
    """MercMode's draw (operator 2026-10-27: "replace the pistol with any random shotgun or magnum", "random weapons
    from the game and campaign"): magnums, shotguns and machine guns only, other guns every round."""
    g = parity_guest()
    ad = Adapter(g)
    pool = ["0x1B", "0x1A", "0x0B", "0x19", "0x16", "0x15", "0x1D"]
    allowed = {0x11B, 0x11A, 0x10B, 0x119, 0x116, 0x115, 0x11D}
    assert SM.tool_run(ad, "loadout", None, True, seed=3, each_round=True, weapons=pool)["verified"]
    assert set(ids(g, 15)[k] for k in (1, 3, 5, 7)) <= allowed
    assert "loadout_redrawn" not in SM.maintain(ad, {"player": {"ptr": 0x1000}})    # this round's player: no draw
    assert "loadout_redrawn" not in SM.maintain(ad, {"player": {"ptr": 0x1000}})
    draws = set()
    for n in range(2, 8):                                                            # each new round's player
        assert SM.maintain(ad, {"player": {"ptr": 0x1000 * n}})["loadout_redrawn"] is True
        guns = [ids(g, 15)[k] for k in (1, 3, 5, 7)]
        assert set(guns) <= allowed and len(set(guns)) == 4
        draws.add(tuple(guns))
    assert len(draws) > 1
    assert ids(g, 14)[1] == 0x106 and ids(g, 14)[9] == 0x101                        # grenades and knives stay
    SM.tool_run(ad, "loadout", None, False)
    assert "loadout_redrawn" not in SM.maintain(ad, {"player": {"ptr": 0x9000}})    # off: never drawn again


def test_single_shotgun_draw_removes_miniguns_and_preserves_every_non_gun_record():
    g = parity_guest()
    put_block(g, block_at(16), {**GENERIC, 3: (0x115, -1, 1)})  # an actual original Gatling template
    ad = Adapter(g)
    allowed = {0x104, 0x116, 0x117, 0x119}
    raw = {i: g.rd(block_at(i), SM.TEMPLATE_REC * SM.TEMPLATE_RECS) for i in SM.MERC_DESC}
    draws = set()
    for seed in range(6):
        out = SM.tool_run(ad, "loadout", None, True, weapons=["0x04", "0x16", "0x17", "0x19"],
                          seed=seed, only=True)
        assert out["verified"]
        guns = []
        for i in SM.MERC_DESC:
            for k in range(SM.TEMPLATE_RECS):
                at = k * SM.TEMPLATE_REC
                original = raw[i][at:at + SM.TEMPLATE_REC]
                old_id = struct.unpack_from("<I", original)[0]
                current = g.rd(block_at(i) + at, SM.TEMPLATE_REC)
                if SM._is_gun(old_id) and old_id & 0xFF not in SM.THROWN_ITEMS:
                    wid = struct.unpack_from("<I", current)[0]
                    assert wid in allowed
                    if i == 15:
                        guns.append(wid)
                else:
                    assert current == original           # first aid, knives, ammo, grenades, placement unchanged
        assert len(set(guns)) == 1                       # one shotgun choice for this round's character
        draws.add(guns[0])
    assert len(draws) > 1


def test_profile_round_ops_forward_magnums_and_preserve_supplies_before_native_inventory_construction():
    from gbox import mercs_bot, ram_map

    g = parity_guest()
    put_block(g, block_at(16), {**GENERIC, 3: (0x115, -1, 1)})
    ad = Adapter(g)
    before = {i: g.rd(block_at(i), SM.TEMPLATE_REC * SM.TEMPLATE_RECS) for i in SM.MERC_DESC}
    profile = ram_map.find(R.MAP_ID).spec["mercs"] | {"map_id": R.MAP_ID, "platform": "switch"}
    assert mercs_bot.apply_ops(ad, profile["round_ops"], profile) == []
    draw = SM.ORIG[id(ad)]["loadout"]
    # operator 2026-10-28: "every round of RE5 needs mines and random weapons especially magnums and shotguns"
    assert set(draw["pool"]) == {0x11B, 0x11A, 0x10B, 0x119, 0x117, 0x116, 0x104} and not draw["only"]
    for i in SM.MERC_DESC:
        guns = [wid for wid in ids(g, i) if SM._is_gun(wid) and wid & 0xFF not in SM.THROWN_ITEMS]
        assert guns and set(guns) <= set(draw["pool"])               # each slot its own draw: shotgun AND magnum
        for k in range(SM.TEMPLATE_RECS):
            original = before[i][k * SM.TEMPLATE_REC:(k + 1) * SM.TEMPLATE_REC]
            old_id = struct.unpack_from("<I", original)[0]
            if not SM._is_gun(old_id) or old_id & 0xFF in SM.THROWN_ITEMS:
                assert g.rd(block_at(i) + k * SM.TEMPLATE_REC, SM.TEMPLATE_REC) == original
    assert 0x115 not in ids(g, 16)
    assert all(BASE <= address < BASE + SM.MAIN_SPAN for address, _ in ad.writes)


def test_an_unsupported_explicit_pool_never_falls_back_to_miniguns():
    g = parity_guest()
    ad = Adapter(g)
    before = g.rd(block_at(15), SM.TEMPLATE_REC * SM.TEMPLATE_RECS)
    with pytest.raises(ValueError, match="unsupported"):
        SM.loadout(SM.RE5Switch(ad), weapons=["0x19", "0x0F"], only=True)
    assert g.rd(block_at(15), len(before)) == before and not ad.writes


def test_template_ops_and_the_bombs_compose_and_revert_all_puts_every_block_back():
    g = parity_guest()
    ad = Adapter(g)
    SM.run(ad, "mine_loadout", on=True)
    SM.tool_run(ad, "weapon_override", None, True, weapon=0x0F, only=True)
    assert ids(g, 14)[1] == SM.MINE_ID and ids(g, 24)[1] == SM.MINE_ID and ids(g, 14)[3] == 0x10F   # bombs and bows
    SM.tool_run(ad, "weapon_override", None, False)
    assert ids(g, 14)[1] == SM.MINE_ID and ids(g, 14)[3] == 0x102          # the bombs outlive the override
    SM.tool_run(ad, "weapon_override", None, True, weapon=0x0F, only=True)
    out = SM.run(ad, "mine_loadout", on=True)                             # live 2026-10-27: Chris's block, bows in it
    assert out["verified"] and out["blocks"] == [hex(o) for o in SM.CHRIS_TEMPLATES]
    out = SM.tool_run(ad, "revert_all")
    assert out["verified"] and all(out["reverted"].values())
    assert ids(g, 14)[1] == SM.GRENADE_ID and ids(g, 14)[3] == 0x102 and ids(g, 15)[1] == 0x10D


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
    assert snap["mine_settings"] == {"enabled": True, "interval_s": SM.MINE_EVERY_DEFAULT, "only": False}   # ("only": the default S)
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
                                      {"op": "instant_qte", "on": True},
                                      {"op": "weapon_override", "weapon": 15, "only": True, "name": "bow"}])
    assert out["results"]["fire_rate"]["verified"] and out["results"]["bow"]["verified"]
    assert out["results"]["turn_speed"]["verified"]
    assert out["results"]["instant_qte"]["reason"].startswith("not yet on Switch: ") and out["verified"] is False


def test_mercs_select_steers_the_switch_menus_to_the_next_rounds_stage_and_character(monkeypatch):
    monkeypatch.setattr(R, "SELECTION", {})
    g = parity_guest()
    ad = Adapter(g)
    out = SM.tool_run(ad, "mercs_select", None, True, mode="no_mercy", character="Sheva (Tribal)", stage="Village")
    assert out["verified"] and out["queued"] and out["selection"]["stage"] == 2 and out["selection"]["character"] ==         "Sheva (Tribal)"
    assert R.stage_target() == 2 and R.player_target() == 5
    assert out["status"]["mercs_selection"] == {"stage": "Village", "character": "Sheva (Tribal)"}
    gs = __import__("tests.test_re5_switch", fromlist=["round_guest"]).round_guest(
        phase=R.PHASE_INTRO, player=False, units=((1, "uIdStartUp21"),), cursors={"uIdStartUp21": {R.MENU_CURSOR: 0}})
    scr = R.screen(gs)
    assert scr["where"] == "select_stage" and scr["target"] == 2 and R.step(scr) == "dright"
    bad = SM.tool_run(ad, "mercs_select", None, True, mode="reunion", character="Barry", stage=0)
    assert bad["verified"] is False and bad["reason"].startswith("not yet on Switch: ")
    assert SM.tool_run(ad, "mercs_select", None, True, mode="no_mercy", character="Barry")["verified"] is False
    assert R.player_target() == 5                                          # a refused choice changes nothing


def test_select_and_random_weapon_set_the_operators_gun_the_bot_equips_and_maintain_confirms():
    from tests.test_re5_switch_mods import put_slot
    g = parity_guest()
    ad = Adapter(g)
    put_slot(g, 0, 0x102, 15, 3, hand=1)                                  # the M92F in hand
    put_slot(g, 1, 0x104, 7, 5)                                           # the Ithaca at grid 5 (D-pad right)
    put_slot(g, 2, 0x10D, 1, 7)                                           # a rocket launcher: never offered
    st = SM.tool_run(ad, "status")["status"]
    assert [w["item"] for w in st["available_weapons"]] == [0x02, 0x04] and st["capabilities"]["select_weapon"]["available"]
    out = SM.tool_run(ad, "select_weapon", None, True, weapon=0x04)
    assert out["queued"] and out["preference_saved"] and out["request"]["weapon"] == "Ithaca M37"
    assert out["status"]["random_weapon_request"]["state"] == "pending"
    snap = R.snapshot(g)
    R.RE5Switch()._mods(SimpleNamespace(adapter=ad), snap, True)
    assert snap["preferred_weapon"] == {"item": 0x04, "weapon": "Ithaca M37"}
    b = R.Bot(stats={}, clock=lambda: 5.0)
    assert b._gun_back(snap, 5.0) == {"tap": "dright"}                   # the bot's D-pad for the Ithaca
    put_slot(g, 0, 0x102, 15, 3, hand=0)
    put_slot(g, 1, 0x104, 7, 5, hand=1)
    SM.maintain(ad, R.snapshot(g))
    st = SM.tool_run(ad, "status")["status"]
    assert st["random_weapon_request"]["state"] == "confirmed" and st["preferred_weapon"]["equipped"]
    assert SM.tool_run(ad, "select_weapon", None, True, weapon=0x0D)["reason"].startswith("The selected gun")
    rnd = SM.tool_run(ad, "random_weapon")
    assert rnd["queued"] and rnd["request"]["item"] == 0x02                # the one not in hand
    assert SM.tool_run(ad, "select_weapon", None, False)["automatic"] and SM.preferred_weapon(ad) is None


def test_bullet_damage_scales_every_firepower_level_and_turn_speed_the_turn_and_aim_rates():
    g = parity_guest()
    ad = Adapter(g)
    fp = lambda wid: struct.unpack("<14f", g.rd(BASE + SM.UPG_TABLE + SM.UPG_STRIDE * wid + SM.UPG_GROUP0, 56))
    out = SM.tool_run(ad, "bullet_damage", 10, True)
    assert out["verified"] and out["m92f_firepower_level0"] == 1500.0 and out["status"]["bullet_damage_x"] == 10.0
    assert fp(0x02)[:3] == (1500.0, 1700.0, 1900.0) and fp(0x04)[0] == 3000.0
    SM.tool_run(ad, "bullet_damage", 10, False)
    assert fp(0x02)[0] == 150.0
    par = struct.unpack("<Q", g.rd(BASE + SM.S_PARAM_PTR, 8))[0]
    out = SM.tool_run(ad, "turn_speed", 3, True)
    assert out["verified"] and out["values"]["aim_yaw_deg_s"] == pytest.approx(173.7) and out["status"]["turn_speed_x"] == 3.0
    assert struct.unpack("<f", g.rd(par + 0x34, 4))[0] == pytest.approx(330.0)
    assert SM.tool_run(ad, "turn_speed", "max", True)["turn_speed_x"] == SM.TURN_MAX
    assert SM.tool_run(ad, "revert_all")["verified"]
    assert struct.unpack("<f", g.rd(par + 0x2D4, 4))[0] == pytest.approx(57.9) and fp(0x02)[0] == 150.0
    g.put(BASE + SM.UPG_TABLE + SM.UPG_STRIDE * 2 + SM.UPG_GROUP0, struct.pack("<f", 77.0))
    SM.ORIG.clear()
    with pytest.raises(RuntimeError, match="firepower"):
        SM.tool_run(Adapter(g), "bullet_damage", 10, True)               # not this build's table: nothing written


def clock_guest():
    """parity_guest plus the round's clock owner: sArea (main+0x26A1460) +0x7040 -> aGame, its countdown at +0x7C0 = the
    HUD's 97.5 (cGameSys +0x948), its end flag +0x7B8 = 0."""
    g = parity_guest()
    area, game = g.alloc(0x8000), g.alloc(0x1000)
    g.put(area, bytes(0x8000))
    g.put(game, bytes(0x1000))
    g.q(BASE + SM.S_AREA_PTR, area)
    g.q(area + SM.AREA_GAME, game)
    g.put(game + SM.GAME_CLOCK, struct.pack("<f", 97.5))
    return g, game


def test_the_clock_ops_write_the_authoritative_countdown_not_the_huds_copy():
    g, game = clock_guest()
    ad = Adapter(g)
    gs = R.game_sys(g, BASE)
    master = lambda: struct.unpack("<f", g.rd(game + SM.GAME_CLOCK, 4))[0]
    out = SM.tool_run(ad, "add_time", None, True, seconds=60)
    assert out["verified"] and out["added_seconds"] == 60 and master() == 157.5
    assert struct.unpack("<i", g.rd(gs + SM.GS_LAST_BONUS, 4))[0] == 60 and g.rd(gs + SM.GS_SHOW_BONUS, 1) == b"\x01"
    assert struct.unpack("<f", g.rd(gs + R.GS_TIMER, 4))[0] == 97.5            # the copy: the game copies it each frame
    g.put(gs + R.GS_TIMER, struct.pack("<f", 157.5))
    out = SM.tool_run(ad, "add_time", -500, True)                              # a cut stops at one second
    assert out["verified"] and out["clamped"] and master() == 1.0
    g.put(gs + R.GS_TIMER, struct.pack("<f", 1.0))
    assert SM.tool_run(ad, "set_time", None, True, seconds=5)["verified"] and master() == 5.0
    g.put(gs + R.GS_TIMER, struct.pack("<f", 50.0))                            # owner and HUD disagree: refused
    with pytest.raises(RuntimeError, match="disagrees"):
        SM.tool_run(ad, "add_time", 30, True)
    with pytest.raises(ValueError):
        SM.tool_run(ad, "set_time", None, True, seconds=0)


def test_kill_time_adds_seconds_for_each_kill_and_the_hourglasses_scale_where_they_stand():
    g, game = clock_guest()
    ad = Adapter(g)
    gs = R.game_sys(g, BASE)
    assert SM.tool_run(ad, "kill_time", 5, True)["seconds"] == 5.0
    snap = R.snapshot(g)                                                       # kills 9: the first look
    assert SM.maintain(ad, snap)["writes"] == 0
    g.i32(gs + R.GS_KILLS, 11)
    assert SM.maintain(ad, R.snapshot(g))["writes"] == 1
    assert struct.unpack("<f", g.rd(game + SM.GAME_CLOCK, 4))[0] == 107.5        # two kills: +10 s
    st = SM.tool_run(ad, "status")["status"]
    assert st["kill_time_on"] and st["kill_time_s"] == 5.0 and st["capabilities"]["add_time"]["available"]
    su = R.u64(g, BASE + R.S_UNIT)
    hg = g.alloc(0x2000)
    g.put(hg, bytes(0x2000))
    g.q(hg, BASE + SM.HOURGLASS_VT)
    g.put(hg + SM.HG_SECONDS, struct.pack("<h", 30))
    g.q(su + R.UNIT_LINES + R.LINE_STRIDE * 12, hg)
    parent, other = g.alloc(0x2000), g.alloc(0x2000)                           # uOmHourGlass's own, and not one
    for u, vt, sec in ((parent, SM.HOURGLASS_PARENT_VT, 90), (other, 0x1BD6D48, 30)):
        g.put(u, bytes(0x2000))
        g.q(u, BASE + vt)
        g.put(u + SM.HG_SECONDS, struct.pack("<h", sec))
    g.q(su + R.UNIT_LINES + R.LINE_STRIDE * 13, parent)
    g.q(parent + R.UNIT_NEXT, other)
    out = SM.tool_run(ad, "time_bonus_multiplier", 3, True)
    assert out["verified"] and out["hourglasses"] == 2 and out["hourglass_seconds"] == [90, 270]
    assert struct.unpack("<h", g.rd(other + SM.HG_SECONDS, 2))[0] == 30         # another unit is left alone
    assert SM.tool_run(ad, "time_bonus_multiplier", 3, True)["scaled"] == 0    # once a unit (90 is not raw 30)


def test_the_standing_hourglass_is_uom0100_and_its_parent_is_accepted_too():
    assert (SM.HOURGLASS_VT, SM.HOURGLASS_PARENT_VT) == (0x1BD6D58, 0x1BD71D8)


def test_rotten_eggs_only_puts_the_egg_in_every_gun_slot_with_an_endless_stock_and_takes_it_back():
    g = parity_guest()
    at = BASE + 0x1900000 + 0x40 * 0x36
    g.put(at, b"WP36 EGG_X\t\t\t\t\0")
    g.q(BASE + SM.DEF_TABLE + SM.DEF_STRIDE * 0x36 + SM.DEF_NAME, at)
    ad = Adapter(g)
    flag = lambda: struct.unpack("<I", g.rd(BASE + SM.DEF_TABLE + SM.DEF_STRIDE * 0x36 + SM.DEF_NOAMMO, 4))[0]
    out = SM.tool_run(ad, "rotten_egg_only", 20, True)
    assert out["verified"] and out["rotten_egg_only"] and out["egg_rate_x"] == 20.0 and flag() == 1
    assert ids(g, 14)[3] == SM.EGG_ID and ids(g, 14)[5] == SM.EGG_ID and ids(g, 14)[1] == 0x106   # guns, not grenades
    assert out["status"]["rotten_egg_only"] and out["status"]["fire_rate_x"] == 20.0
    out = SM.tool_run(ad, "rotten_egg_only", None, False)
    assert out["verified"] and flag() == 0 and ids(g, 14)[3] == 0x102
    with pytest.raises(ValueError):
        SM.tool_run(ad, "rotten_egg_only", 50, True)
