"""RE6 Switch cast-roster planner/build tests (library- and RomFS-dependent ones skip when the assets are absent).

`GBOX_CHARACTER_LIBRARY` names the character library (one folder per entry with a `meta.json`) and
`GBOX_RE6_SWITCH_ROMFS` the extracted RomFS root. The asset tests hold on any library: the Smash Ultimate / Brawl
collection of the build machine, or the mixed-franchise library of the game host.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from gbox import re6_switch_cast as R
from gbox import re6_switch_models as S

ROMFS = Path(os.environ.get("GBOX_RE6_SWITCH_ROMFS", r"C:\_tools\gBox\.tmp\re6sw_romfs"))
LIB = Path(os.environ.get("GBOX_CHARACTER_LIBRARY", r"D:\gBox\cache\characters"))
needs_romfs = pytest.mark.skipif(not (ROMFS / "nativeNXx64" / "arc" / "NX").is_dir(),
                                 reason="the extracted RE6 Switch RomFS is not present")
needs_library = pytest.mark.skipif(not LIB.is_dir(), reason="the character library is not present")
SEVEN = [("leon", "Asia"), ("helena", "Asia"), ("chris", "Asia"), ("piers", "Asia"), ("jake", "Asia"),
         ("sherry", "Asia"), ("ada", "A")]


def _meta(slug: str, game: str, name: str | None = None, *, roles=R.FULL_ROLES, skinned: bool = True,
          model: str | None = None, shared: bool = False) -> dict:
    joints = {role: f"j_{role}" for role in roles}
    if shared:
        joints["l_foot"] = joints["r_foot"]
    return {"slug": slug, "name": name or slug, "model": f"{slug}.glb" if model is None else model,
            "source": {"game_title": game}, "rig": {"skinned": skinned, "roles": joints}}


def _library() -> list[dict]:
    games = ("Super Smash Bros. Melee (USA)", "Metal Gear Solid 2 - Substance", "Soul Calibur II (USA)",
             "Def Jam - Vendetta (USA)", "007 - Agent Under Fire", "Phantasy Star Online Episode I & II Plus",
             "John Woo Presents Stranglehold", "Crazy Taxi 2 (USA)")
    return [_meta(f"g{g}_c{c}", game, f"Fighter {g}-{c}") for g, game in enumerate(games) for c in range(4)]


def test_plan_puts_a_distinct_donor_on_every_slot():
    pool = [{"slug": f"donor{i:02d}", "name": f"Donor {i}", "rig": {"skinned": True, "roles": {}}} for i in range(30)]
    slots = [("leon", "Usa"), ("leon", "Asia"), ("chris", "Europe")]
    assignment = R.plan(ROMFS, pool, seed=3, slots=slots)
    assert set(assignment) == set(slots)
    assert len({meta["slug"] for meta in assignment.values()}) == len(slots)


def test_per_character_plan_reuses_one_donor_per_character():
    """A textured build needs one donor per character (its albedo set is shared by its costumes)."""
    pool = [{"slug": f"donor{i:02d}", "name": f"Donor {i}"} for i in range(9)]
    slots = [("leon", "Usa"), ("leon", "Asia"), ("ada", "A")]
    assignment = R.plan(ROMFS, pool, seed=1, slots=slots, per_character=True)
    assert assignment[("leon", "Usa")]["slug"] == assignment[("leon", "Asia")]["slug"]
    assert assignment[("leon", "Usa")]["slug"] != assignment[("ada", "A")]["slug"]


def test_plan_refuses_a_pool_smaller_than_the_slots():
    pool = [{"slug": "one", "name": "One"}]
    with pytest.raises(R.CastError):
        R.plan(ROMFS, pool, slots=[("leon", "Usa"), ("leon", "Asia")])


def test_the_plan_is_seeded_and_changes_with_the_seed():
    pool = _library()
    first = R.plan(ROMFS, pool, seed=5, slots=SEVEN, mix=True)
    again = R.plan(ROMFS, [dict(meta) for meta in pool], seed=5, slots=SEVEN, mix=True)
    assert {slot: meta["slug"] for slot, meta in first.items()} == {slot: meta["slug"] for slot, meta in again.items()}
    drawn = {tuple(meta["slug"] for meta in R.plan(ROMFS, pool, seed=seed, slots=SEVEN, mix=True).values())
             for seed in range(12)}
    assert len(drawn) > 8                                         # different seeds, different overlays


def test_a_mixed_plan_takes_every_source_game_before_any_game_twice():
    pool = _library()                                             # eight games, four fighters each
    for seed in range(10):
        seven = R.plan(ROMFS, pool, seed=seed, slots=SEVEN, mix=True)
        assert len({R.franchise(meta) for meta in seven.values()}) == 7
        assert len({meta["slug"] for meta in seven.values()}) == 7
    twelve = [(f"c{i}", "A") for i in range(12)]
    wide = R.plan(ROMFS, pool, seed=2, slots=twelve, mix=True)
    games = [R.franchise(meta) for meta in wide.values()]
    assert len(set(games)) == 8 and max(games.count(game) for game in set(games)) == 2
    plain = R.plan(ROMFS, pool, seed=2, slots=twelve)             # the unmixed draw makes no such promise
    assert len({meta["slug"] for meta in plain.values()}) == 12
    one = R.plan(ROMFS, pool, seed=4, slots=[("leon", "Usa"), ("leon", "Asia"), ("ada", "A")], per_character=True,
                 mix=True)
    assert one[("leon", "Usa")]["slug"] == one[("leon", "Asia")]["slug"]
    assert R.franchise(one[("leon", "Usa")]) != R.franchise(one[("ada", "A")])


def test_no_character_appears_twice_in_one_overlay():
    """Two dumps of one game list the same character under two slugs and two titles: still one cast member."""
    pool = [_meta("auf_bond_tux", "007 - Agent Under Fire (USA)", "James Bond (tuxedo)"),
            _meta("auf_bond_tux_65b7187589166b26", "007 - Agent Under Fire", "James Bond (tuxedo)"),
            _meta("sc2_link", "Soul Calibur II (USA)", "Link"),
            _meta("sc2_link_e08e8a0c1b3c9060", "Soulcalibur II", "Link"),
            _meta("melee_link", "Super Smash Bros. Melee (USA)", "Link")]
    assert R.franchise(pool[0]) == R.franchise(pool[1]) == "007 agent under fire"
    assert R.identity(pool[2]) == R.identity(pool[3]) != R.identity(pool[4])     # Melee's Link is another model
    for seed in range(8):
        for mix in (False, True):
            three = R.plan(ROMFS, pool, seed=seed, slots=[("a", "x"), ("b", "x"), ("c", "x")], mix=mix)
            assert len({R.identity(meta) for meta in three.values()}) == 3
    with pytest.raises(R.CastError):                               # five entries, three characters
        R.plan(ROMFS, pool, slots=[("a", "x"), ("b", "x"), ("c", "x"), ("d", "x")])


def test_donor_check_names_the_reason():
    assert R.donor_check(_meta("ok", "Game")) is None
    assert R.donor_check(_meta("sprite", "Game", model="sheet.png")) == "not a 3D model (sprite sheet / image)"
    assert R.donor_check(_meta("none", "Game", model="")) == "no model file"
    assert R.donor_check(_meta("rigid", "Game", skinned=False)) == "model is not skinned"
    assert R.donor_check(_meta("rob", "Game", shared=True)) == "two roles share one joint"
    no_clavicles = [role for role in R.FULL_ROLES if role not in ("r_clav", "l_clav")]
    doa = [role for role in no_clavicles if role != "neck"]
    assert R.donor_check(_meta("wrestler", "Game", roles=no_clavicles)) == "rig resolves 16/18 roles"
    assert R.donor_check(_meta("doa", "Game", roles=doa)) == "rig resolves 15/18 roles"
    assert R.donor_check(_meta("wrestler", "Game", roles=no_clavicles), tier="core") is None
    assert R.donor_check(_meta("doa", "Game", roles=doa), tier="core") is None       # neck and clavicles optional
    armless = [role for role in doa if role != "l_hand"]
    assert R.donor_check(_meta("armless", "Game", roles=armless), tier="core") == "rig resolves 14/18 roles"
    assert set(R.FULL_ROLES) - set(R.CORE_ROLES) == {"neck", "r_clav", "l_clav"}
    with pytest.raises(R.CastError):
        R.donor_check(_meta("ok", "Game"), tier="everything")


def test_pool_report_counts_usable_donors_per_source_game():
    doa = [role for role in R.FULL_ROLES if role not in ("neck", "r_clav", "l_clav")]
    entries = ([_meta(f"mgs{i}", "Metal Gear Solid 2 - Substance", f"Soldier {i}") for i in range(3)]
               + [_meta("mgs0_again", "Metal Gear Solid 2: Substance (USA)", "Soldier 0")]
               + [_meta(f"doa{i}", "Dead Or Alive ++ (Korea)", f"Fighter {i}", roles=doa) for i in range(5)]
               + [_meta(f"mvc{i}", "Marvel vs. Capcom 2", skinned=False) for i in range(2)]
               + [_meta("tetris", "Tetris DS", model="sheet.png")])
    full = R.pool_report(entries)
    assert (full["entries"], full["usable"], full["distinct_characters"], full["franchises_with_donors"]) == (12, 4, 3, 1)
    assert full["by_franchise"]["metal gear solid 2 substance"] == {"entries": 4, "usable": 4, "rejected": {}}
    assert full["by_franchise"]["dead or alive ++"]["rejected"] == {"rig resolves 15/18 roles": 5}
    assert full["rejected"] == {"rig resolves 15/18 roles": 5, "model is not skinned": 2,
                                "not a 3D model (sprite sheet / image)": 1}
    core = R.pool_report(entries, tier="core")
    assert (core["usable"], core["franchises_with_donors"]) == (9, 2)
    assert core["by_franchise"]["dead or alive ++"]["usable"] == 5


@needs_library
def test_donor_pool_only_returns_complete_rigs():
    pool = R.donor_pool(LIB)
    assert len(pool) >= 7
    assert all(all(role in meta["rig"]["roles"] for role in R.FULL_ROLES) for meta in pool)
    # two roles cannot share one joint (R.O.B.'s single leg): map_weights needs distinct anchors
    assert all(len({meta["rig"]["roles"][role] for role in R.FULL_ROLES}) == 18 for meta in pool)
    assert [meta["slug"] for meta in pool] == sorted(meta["slug"] for meta in pool)
    core = R.donor_pool(LIB, tier="core")
    assert {meta["slug"] for meta in pool} <= {meta["slug"] for meta in core}
    for suffix in ("_ssbu", "_ssbb"):                              # the Smash collections, where the library has them
        if any(path.name.endswith(suffix) for path in LIB.iterdir()):
            assert any(meta["slug"].endswith(suffix) for meta in pool)


@needs_library
def test_status_reports_an_absent_build(tmp_path):
    class Cfg:
        cache = tmp_path

    out = R.status(Cfg(), "no_such_mod")
    assert out["built"] is False and out["mod"] == "no_such_mod"


@needs_romfs
@needs_library
def test_author_slot_draws_the_donor_with_a_vetted_material():
    pool = R.donor_pool(LIB)
    slot = ("chris", "Asia") if (ROMFS / "nativeNXx64" / "arc" / "NX" / "uPlTex0200_0.arc").is_file() else None
    if slot is None or slot not in S.body_arcs(ROMFS):
        pytest.skip("Chris' Asia body and texture set are not present")
    files, receipt = R.author_slot(ROMFS, LIB, slot, pool[0])
    body = S.body_arcs(ROMFS)[slot]
    assert set(files) == {body.name, *receipt.get("blanked_parts", [])}
    choice = receipt["material_choice"]
    assert choice["vetted"] and choice["name"] != "pl_nuki" and choice["index"] == receipt["material_index"] == 1
    assert receipt["material"] == choice["name"] and receipt["bind_mode"] == "keep"
    assert (receipt["character"], receipt["costume"], receipt["donor"]) == (*slot, pool[0]["slug"])
    with pytest.raises(R.CastError):
        R.author_slot(ROMFS, LIB, ("leon", "NoSuchCostume"), pool[0])


@needs_romfs
@needs_library
def test_the_tool_plans_the_switch_roster():
    from types import SimpleNamespace

    from gbox import re6_tool as T

    ctx = SimpleNamespace(config=SimpleNamespace(cache=LIB.parent, data_dir=LIB.parent),
                          server=None, headers={}, progress=lambda _s: None)
    pool = R.donor_pool(LIB)
    bodies = S.body_arcs(ROMFS)
    wanted = [slot for slot in SEVEN if slot in bodies][:len(pool)]
    names = [f"{character}/{costume}" for character, costume in wanted]
    out = T.switch_cast_op(ctx, T.Re6In(op="switch_cast_plan", romfs=str(ROMFS), library=str(LIB), seed=7,
                                        slots=names, mix=True))
    assert out["slots"] == len(wanted) and [row["slot"] for row in out["assignment"]] == sorted(names)
    assert len({row["donor"] for row in out["assignment"]}) == out["slots"]
    assert out["mercmode"]["default_mods"] == {"re6": R.DEFAULT_NAME}
    again = T.switch_cast_op(ctx, T.Re6In(op="switch_cast_plan", romfs=str(ROMFS), library=str(LIB), seed=7,
                                          slots=names, mix=True))
    assert again["assignment"] == out["assignment"]
    core = T.switch_cast_op(ctx, T.Re6In(op="switch_cast_plan", romfs=str(ROMFS), library=str(LIB), seed=7,
                                         slots=names[:2], tier="core"))
    assert core["slots"] == 2
    if len(pool) >= len(bodies):                                   # the whole roster, where the library can fill it
        everything = T.switch_cast_op(ctx, T.Re6In(op="switch_cast_plan", romfs=str(ROMFS), library=str(LIB), seed=7))
        assert everything["slots"] == len(bodies)
        assert len({row["donor"] for row in everything["assignment"]}) == everything["slots"]
