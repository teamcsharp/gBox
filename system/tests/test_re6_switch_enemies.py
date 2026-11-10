"""RE6 Switch enemies: the stage-set census, the donor draw and the body checks.

The synthetic tests need nothing. The ones marked `needs_enemy` read the J'avo archives copied read-only from the game
host (`GBOX_RE6_ENEMY_INPUTS`, default C:\\_tools\\gBox\\.scratch-merc-recovery\\re6\\inputs\\enemy) and a library
donor (`GBOX_RE6_LIBRARY`), and skip when they are absent.
"""
import os
import zlib
from pathlib import Path

import pytest

from gbox import mt_arc, mt_model, re6_switch_enemies as E, re6_switch_models as M

INPUTS = Path(os.environ.get("GBOX_RE6_ENEMY_INPUTS", r"C:\_tools\gBox\.scratch-merc-recovery\re6\inputs\enemy"))
LIBRARY = Path(os.environ.get("GBOX_RE6_LIBRARY", r"C:\_tools\gBox\.scratch-merc-recovery\re6\inputs\characters"))
needs_enemy = pytest.mark.skipif(not (INPUTS / "uEm1000.arc").is_file(), reason="the J'avo archives are not present")


def soft_arc():
    rows = b"".join(b"cSetInfoEm1000\0uEm1400\0" for _ in range(3)) + b"cSetInfoEm1000\0uEm1000\0"
    contents = [("soft\\stage\\s1218\\s1218_em00", 0x15302EF4, b"XFS\0" + rows),
                ("soft\\stage\\s1218\\s1218_em01", 0x15302EF4, b"XFS\0cSetInfoEm5210\0uEm5210\0"),
                ("soft\\stage\\s1218\\s1218_it00", 0x15302EF4, b"XFS\0uEm9999\0"),           # an item layout
                ("soft\\stage\\s1218\\fsm\\plan\\fix\\EmSet1218", 0x66B45610, b"XFS\0uEm3200\0"),   # the FSM
                ("soft\\stage\\s1218\\s1218", 0x4EF19843, b"NAV\0")]
    entries = [mt_arc.Entry(name=n, hash=h, tag=0x40000000 | len(d), size=0, offset=0, data=zlib.compress(d, 6))
               for n, h, d in contents]
    return mt_arc.build(mt_arc.Arc(7, entries))


def test_the_census_counts_placements_in_the_enemy_layouts_only():
    census = E.stage_census(soft_arc())
    assert census["classes"] == {"uEm1400": 3, "uEm1000": 1, "uEm5210": 1}
    assert census["layouts"] == ["s1218_em00", "s1218_em01"]


def meta(slug, game, name=None):
    return {"slug": slug, "name": name or slug, "model": f"{slug}.glb", "source": {"game_title": game},
            "rig": {"skinned": True, "roles": {}}}


def test_one_donor_per_class_with_no_character_twice_and_the_games_in_turn():
    pool = [meta("a1", "Game A", "Ann"), meta("a2", "Game A", "Ann"), meta("b1", "Game B"), meta("c1", "Game C")]
    plan = E.plan_pool(["uEm1400", "uEm1000", "uEm5210"], pool, seed=3)
    assert sorted(plan) == ["uEm1000", "uEm1400", "uEm5210"]
    games = [d["source"]["game_title"] for d in plan.values()]
    assert len(set(games)) == 3                                # three classes, three source games
    assert E.plan_pool(["uEm1400"], pool, seed=3) == E.plan_pool(["uEm1400"], pool, seed=3)   # seeded
    with pytest.raises(E.EnemyError):
        E.plan_pool(["x", "y"], [meta("a1", "Game A", "Ann"), meta("a2", "Game A", "Ann")], seed=1)


def test_the_body_material_is_the_vetted_body_one(monkeypatch):
    from gbox import re6_switch_tex as T
    names = ["em_Eye", "em_ID2_Body", "em_Skirt"]
    bindings = {"em_Eye": ("BSBlendAlpha", "FTransparencyAlpha", "FVertexDisplacement"),
                "em_ID2_Body": ("BSSolid", "FTransparency", "FVertexDisplacement"),
                "em_Skirt": ("BSSolid", "FTransparency", "FVertexDisplacementCurveUV")}
    monkeypatch.setattr(M, "body_materials", lambda model: names)
    monkeypatch.setattr(T, "material_bindings", lambda arc, name: {
        "blend": bindings[name][0], "functions": {"FTransparency": bindings[name][1],
                                                  "FVertexDisplacement": bindings[name][2]},
        "slots": {"tAlbedoMap": f"x\\{name}_BM"}})
    pick = E.body_material(None, None)
    assert (pick["index"], pick["name"], pick["vetted"]) == (1, "em_ID2_Body", True)
    names[1] = "em_Coat"                                       # no `_Body`: the first still, opaque one
    bindings["em_Coat"] = bindings["em_ID2_Body"]
    pick = E.body_material(None, None)
    assert pick["name"] == "em_Coat" and pick["why"].startswith("first opaque")


@needs_enemy
@pytest.mark.parametrize("cls,bones", [("uEm1000", 27), ("uEm1400", 35)])
def test_the_javo_bodies_take_the_player_writer(cls, bones):
    path = INPUTS / f"{cls}.arc"
    if not path.is_file():
        pytest.skip(f"{cls} is not present")
    check = E.body_check(path.read_bytes())
    assert check["bones"] == bones and check["roots"] == 1 and len(check["roles"]) == 18
    assert check["material"]["name"] == "em1000_ID2_Body" and check["material"]["vetted"]
    assert "0x2000D414" in check["formats"] and 175 < check["height_cm"] < 185
    model = mt_model.parse_mod(M._find_model(mt_arc.parse(path.read_bytes()))[2])
    record = model.meshes()[check["template_index"]]
    assert record["material_index"] == check["material"]["index"] and record["level_of_detail"] & 1
    assert check["template"]["group"] == 3                     # the body material's base group on both J'avo


@needs_enemy
def test_a_library_donor_on_a_javo_changes_only_the_body_and_keeps_the_skeleton():
    from gbox import characters as C
    donors = {m["slug"]: m for m in C.list_all(LIBRARY)} if LIBRARY.is_dir() else {}
    if "sc2_yunsung" not in donors:
        pytest.skip("the library donor is not present")
    native = (INPUTS / "uEm1400.arc").read_bytes()
    donor = donors["sc2_yunsung"]
    payload, receipt = E.build_enemy(native, LIBRARY / donor["slug"] / donor["model"], donor["rig"]["roles"])
    assert receipt["changed_entries"] == [receipt["body"]["entry_index"]] and receipt["bind_mode"] == "keep"
    before = M._find_model(mt_arc.parse(native))[2]
    after = M._find_model(mt_arc.parse(payload))[2]
    a, b = mt_model.parse_mod(before), mt_model.parse_mod(after)
    assert a.bone_table()["anim_map"] == b.bone_table()["anim_map"]
    off_a, off_b = a.header()["offsets"], b.header()["offsets"]
    assert before[off_a["bones"]:off_a["groups"]] == after[off_b["bones"]:off_b["groups"]]   # the skeleton, byte for byte
    assert len(b.meshes()) == 1 and b.meshes()[0]["material_index"] == receipt["body"]["material"]["index"]
