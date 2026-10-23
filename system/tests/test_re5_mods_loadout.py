"""`re5_mods` loadout + random_cheats: the Mercenaries loadout templates (static data the round start copies into the
inventory: proven live 2026-10-21, Barry's M29 -> S&W M500 5/5 and Dragunov -> Hydra 4/4 built by the game), the
per-round randomizer and the playbook's round_ops."""
import struct
from types import SimpleNamespace
import pytest

from gbox import mercs_bot as MB, re5_mods_tool as T
from test_re5_mods import FakeRE5, fresh_originals  # noqa: F401 (the autouse fixture)


def with_template(m):
    """The loadout templates: 30 blocks, Barry's (24) and Chris Heavy Metal's (18) laid out like the executable's."""
    def rec(off, idw, count, pos, hand, levels):
        m.put(T.TEMPLATE + off, struct.pack(">11I", idw, count & 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, pos, hand,
                                            levels, 0, 0, 0))
    rec(0x84, 0x124, -1, 8, 0, 0)                                    # block 0's knife: the signature
    b = 24 * T.TEMPLATE_BLOCK
    rec(b + 5 * 0x2C, 0x100, -1, 11, 0, 0)
    rec(b + 6 * 0x2C, 0x112, -1, 3, 1, 0)
    rec(b + 7 * 0x2C, 0x10B, -1, 5, 0, 0x06000306)
    rec(b + 8 * 0x2C, 0x120, -1, 1, 0, 0x09000307)
    rec(b + 9 * 0x2C, 0x201, 50, 0, 0, 0)
    rec(b + 10 * 0x2C, 0x209, 6, 2, 0, 0)
    rec(25 * T.TEMPLATE_BLOCK, 0x114, -1, 9, 0, 0)
    b = 18 * T.TEMPLATE_BLOCK
    rec(b + 6 * 0x2C, 0x115, -1, 3, 1, 0)
    rec(b + 7 * 0x2C, 0x122, -1, 5, 0, 0)
    rec(b + 3 * 0x2C, 0x101, -1, 9, 0, 0)
    from gbox.mercs.titles.re5_mines import ORIGINAL_BANKS, ORIGINAL_KNIVES
    for address in ORIGINAL_BANKS:
        m.u32(address+3*T.TEMPLATE_REC,ORIGINAL_KNIVES[address])
        m.u32(address+5*T.TEMPLATE_REC,0x100)
    return m


def test_loadout_rewrites_every_characters_guns_with_powerful_ones_and_restores():
    m = with_template(FakeRE5())
    r = T.run(m, "loadout", seed=7)
    assert r["verified"] and r["blocks"] == 2 and len(r["barry"]) == 3 and len(r["chris_heavy_metal"]) == 2
    assert all(w in T.POWERFUL.values() for w in r["barry"]) and len(set(r["barry"])) == 3     # no repeats in a block
    t = m.read_memory(T.TEMPLATE, T.TEMPLATE_BLOCKS * T.TEMPLATE_BLOCK)
    recs = {off: (idw, lv) for off, idw, _, _, _, lv in T.template_records(t)}
    b = 24 * T.TEMPLATE_BLOCK
    assert recs[b + 6 * 0x2C][0] in T.POWERFUL and recs[b + 7 * 0x2C][1] == 0 and recs[b + 8 * 0x2C][1] == 0  # levels reset
    assert recs[25 * T.TEMPLATE_BLOCK] == (0x114, 0) and recs[b + 5 * 0x2C] == (0x100, 0) and recs[b + 9 * 0x2C] == (0x201, 0)
    assert T.run(m, "loadout", seed=7)["barry"] == r["barry"]                                    # seed = the same draw
    assert T.run(m, "loadout", weapons=["0x11b"])["barry"] == ["S&W M500"] * 3                   # a chosen set
    r = T.run(m, "loadout", on=False)
    assert r["verified"] and m.read_memory(T.TEMPLATE, T.TEMPLATE_BLOCKS * T.TEMPLATE_BLOCK) == T.ORIG[id(m)]["template"]


def test_random_cheats_picks_a_set_and_reports_it():
    m = with_template(FakeRE5())
    r = T.run(m, "random_cheats", seed=3)
    assert r["verified"] and r["telemetry"]["fire_rate_x"] == 80.0 and r["telemetry"]["turn_speed_x"] == 1.0
    assert r["telemetry"]["bullet_damage_x"] in (1.0, 3.0, 10.0) and r["telemetry"]["infinite_ammo"] is True
    st = r["status"]
    assert st["fire_rate_x"] == 80.0 and st["infinite_ammo"] is True and st["turn_speed_x"] == r["telemetry"]["turn_speed_x"]
    rr = T.run(m, "revert_all")
    assert rr["verified"] and "loadout" in rr["reverted"] and rr["status"]["fire_rate_x"] == 1.0


def test_requested_rockets_become_random_magnums_in_generated_loadouts():
    m = with_template(FakeRE5())
    names = set()
    for seed in range(12):
        result = T.run(m, "loadout", weapons=[0x10D], seed=seed)
        names.update(result["barry"])
        assert set(result["barry"]) <= {T.WEAPONS[w & 0xFF] for w in T.MAGNUMS}
        assert all(idw != 0x10D for _, idw, *_ in T.template_records(
            m.read_memory(T.TEMPLATE, T.TEMPLATE_BLOCKS * T.TEMPLATE_BLOCK)))
    assert len(names) == 3


def test_existing_rocket_templates_are_replaced_without_touching_equipped_objects_or_other_records():
    m = with_template(FakeRE5())
    off = 24 * T.TEMPLATE_BLOCK + 6 * T.TEMPLATE_REC
    m.u32(T.TEMPLATE + off, 0x10D)
    before = m.read_memory(T.TEMPLATE, T.TEMPLATE_BLOCKS * T.TEMPLATE_BLOCK)
    equipped = m.read_memory(0x303F89E0 + T.INV_OFS, T.INV_SLOTS * T.SLOT)
    result = T.run(m, "replace_rockets", seed=7)
    assert result["verified"] and result["effective_next_round"] is True
    assert len(result["rocket_replacements"]) == 1
    after = m.read_memory(T.TEMPLATE, len(before))
    assert struct.unpack_from(">I", after, off)[0] in T.MAGNUMS
    assert after[:off] == before[:off] and after[off + T.TEMPLATE_REC:] == before[off + T.TEMPLATE_REC:]
    assert after[off + 8:off + 28] == before[off + 8:off + 28]  # grid/hand and record identity preserved
    assert struct.unpack_from(">I", after, off + 4)[0] == 0xFFFFFFFF
    assert struct.unpack_from(">I", after, off + 28)[0] == 0
    assert m.read_memory(0x303F89E0 + T.INV_OFS, len(equipped)) == equipped
    writes = len(m.writes)
    assert T.run(m, "replace_rockets")["rocket_replacements"] == [] and len(m.writes) == writes
    m.u32(T.TEMPLATE + T.TEMPLATE_SIGNATURE[0], 0)
    with pytest.raises(RuntimeError, match="signature"):
        T.run(m, "replace_rockets")


def test_the_playbook_runs_round_ops_at_every_select_and_shows_the_picks():
    m = with_template(FakeRE5())
    prof = {"platform": "ps3", "map_id": "BLUS30491"}
    stats: dict = {}
    assert MB.apply_ops(m, [["random_cheats", {"seed": 1}]], prof, stats) == [] and stats["cheats"]["fire_rate_x"] == 80.0
    screens = iter(["select_player", "select_player", "playing", "results", "select_player", "playing"])
    menus = SimpleNamespace(screen=lambda mm, merc=None: {"where": next(screens)}, step=lambda scr: None,
                            wandered=lambda scr: None)
    rounds, hooks = [], []
    boot = MB.Boot(menus, m, lambda rows: None, sleep=lambda s: None, clock=lambda: 0.0, stats=stats,
                   hooks=lambda: hooks.append(1) or [], round_hooks=lambda: rounds.append(1) or [])
    for _ in range(6):
        boot.tick()
    assert len(rounds) == 2 and len(hooks) == 1 and stats["rounds_hooked"] == 2         # once per visit to the selects
