"""The cast swap's `mario` donor group: Super Mario 64 DS, Super Mario 64 (ROM, decomp reader) and HD (Render96,
imported through the Blender round trip) entries collapse to the best model per character after the quality gate,
and the DOA2 / SoulCalibur / Soul Calibur II builders can take the same group."""
import json
from pathlib import Path

import pytest

from gbox import cast_swap as CS, doa2_mixed as DM, soulcalibur2_swap as SC2, soulcalibur_swap as SC

ROLES = {r: f"j_{r}" for r in ("hip", "chest", "neck", "head", "l_clav", "r_clav", "l_upper", "l_fore", "l_hand",
                               "r_upper", "r_fore", "r_hand", "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot")}
DOA2 = {"game_id": next(iter(__import__("gbox.doa2_swap", fromlist=["x"]).GAME_IDS)), "title": "Dead or Alive 2",
        "platform": "dreamcast"}
DS = ("Super Mario 64 DS (USA)", "nds", "917483267d246594")
N64 = ("Super Mario 64 (USA)", "n64", "1f1c9e2bd4d4fb6f")
R96 = ("Render96 ModelPack (Super Mario 64 HD models)", "", None)


def entry(slug, name, src, roles=ROLES, tris=500, **kw):
    title, plat, gid = src
    return {"slug": slug, "name": name, "kind": "character", "model": f"{slug}.glb", "aliases": [],
            "rig": {"roles": dict(roles)} if roles is not None else {}, "stats": {"triangles": tris, "textures": 1},
            "readiness": {"status": kw.pop("status", "ready")},
            "source": {"game_title": title, "platform": plat, "game_id": gid}, **kw}


def collection():
    return [
        entry("sm64ds_mario", "Mario (Super Mario 64 DS)", DS, tris=452),
        entry("sm64ds_luigi", "Luigi (Super Mario 64 DS)", DS, tris=455),
        entry("sm64ds_yoshi", "Yoshi (Super Mario 64 DS)", DS, tris=428),
        entry("sm64ds_koopa_troopa", "Koopa Troopa (Super Mario 64 DS)", DS),
        entry("sm64ds_toad", "Toad (Super Mario 64 DS)", DS, status="limited"),
        entry("mario", "Mario", N64, roles={"hip": "j01", "chest": "j02", "head": "j03"}, tris=752),
        entry("sm64_mario", "Mario (Super Mario 64)", N64, tris=752, character="mario", donor_group="mario",
              donor_quality="rom"),
        entry("sm64_yoshi", "Yoshi (Super Mario 64)", N64, tris=676, character="yoshi", donor_group="mario",
              donor_quality="rom"),
        entry("mario_hd", "Mario (HD, Render96)", R96, tris=19422, character="mario", donor_group="mario",
              donor_quality="hd", licence="Render96: no licence file; local use only"),
        entry("luigi_hd", "Luigi (HD, Render96)", R96, tris=20684, character="luigi", donor_group="mario",
              donor_quality="hd"),
        entry("sonic", "Sonic", ("Sonic Adventure 2 (USA)", "dreamcast", "5a20000000000000")),
    ]


def test_character_keys_match_across_games_and_packs():
    keys = {m["slug"]: CS.character_key(m) for m in collection()}
    assert keys["sm64ds_mario"] == keys["sm64_mario"] == keys["mario_hd"] == keys["mario"] == "mario"
    assert keys["sm64ds_koopa_troopa"] == "koopa_troopa" and keys["luigi_hd"] == "luigi"
    assert CS.character_key({"slug": "sm64ds_metal_wario"}) == "metal_wario"


def test_best_per_character_prefers_hd_then_rom_then_ds():
    keep, gone = CS.best_per_character([m for m in collection() if CS.in_group(m, "mario")])
    best = {CS.character_key(m): m["slug"] for m in keep}
    assert best["mario"] == "mario_hd" and best["luigi"] == "luigi_hd" and best["yoshi"] == "sm64_yoshi"
    assert best["koopa_troopa"] == "sm64ds_koopa_troopa"
    assert {r["slug"]: r["by"] for r in gone if r["character"] == "mario"} == {
        "sm64ds_mario": "mario_hd", "mario": "mario_hd", "sm64_mario": "mario_hd"}


def test_source_mario_is_a_group_with_one_donor_per_character():
    chars = collection()
    src = CS.resolve_source("mario", chars)
    assert src["best_per_character"] == ["mario"] and "sonic" not in {m["slug"] for m in src["entries"]}
    assert {"sm64ds_mario", "sm64_mario", "mario_hd", "mario"} <= {m["slug"] for m in src["entries"]}
    menu = {g["key"]: g for g in CS.source_groups(chars)}
    assert menu["mario"]["count"] == 5                       # mario, luigi, yoshi, koopa troopa, toad


def test_doa2_plan_with_the_mario_group_uses_the_hd_models_and_lists_what_they_replaced():
    p = CS.plan(DOA2, collection(), "sonic, mario", mapping="random", seed="1")
    assert p["status"] == "planned"
    used = {d["slug"] for d in p["donors"]}
    assert {"mario_hd", "luigi_hd", "sm64_yoshi", "sm64ds_koopa_troopa", "sonic"} <= used
    assert not used & {"sm64ds_mario", "sm64_mario", "mario", "sm64ds_luigi", "sm64ds_yoshi"}
    assert {r["slug"] for r in p["superseded"]} >= {"sm64ds_mario", "sm64_mario", "sm64ds_luigi", "sm64ds_yoshi"}
    assert p == CS.plan(DOA2, collection(), "sonic, mario", mapping="random", seed="1")       # deterministic


def test_a_refused_hd_model_falls_back_to_the_next_best_of_that_character():
    chars = [m if m["slug"] != "mario_hd" else dict(m, rig={}) for m in collection()]          # HD Mario unmapped
    p = CS.plan(DOA2, chars, "mario", mapping="random", seed="1")
    used = {d["slug"] for d in p["donors"]}
    assert "mario_hd" in {r["slug"] for r in p["refused"]} and "sm64_mario" in used and "mario_hd" not in used


def _library(root: Path) -> Path:
    for m in collection():
        (root / m["slug"]).mkdir(parents=True)
        (root / m["slug"] / "meta.json").write_text(json.dumps(m))
    return root


def test_builders_upgrade_the_mario_side_from_a_library_folder(tmp_path):
    lib = _library(tmp_path / "lib")
    assert CS.upgrade_slugs(["sm64ds_mario", "sm64ds_luigi", "sm64ds_yoshi", "sm64ds_ukiki", "sonic"],
                            CS.library_metas(lib)) == {"sm64ds_mario": "mario_hd", "sm64ds_luigi": "luigi_hd",
                                                       "sm64ds_yoshi": "sm64_yoshi", "sm64ds_ukiki": "sm64ds_ukiki",
                                                       "sonic": "sonic"}
    # DOA2 mixed: the upgraded donors still count as the Mario franchise, half the headlines each
    pool, heads = DM.mario_group(lib)
    assert pool[:4] == ["mario_hd", "luigi_hd", "sm64ds_wario", "sm64_yoshi"] and heads["KTE"] == "mario_hd" and heads["JAN"] == "sonic"
    plan = DM.plan_pools({f: ["0", "1", "2"] for f in DM.HEADLINE}, sm64ds=pool, headline=heads, seed="s")
    chk = DM.check_plan(plan)
    assert chk["ok"] and chk["headline_sa2"] == chk["headline_sm64ds"] == 7
    assert "mario_hd" in chk["donors"] and "sm64ds_mario" not in chk["donors"]
    # SoulCalibur DC: Mitsurugi's Mario costume becomes HD Mario, the SA2 side is untouched
    sc = SC.mario_group(lib)
    assert sc["MIT"] == ["sonic", "mario_hd"] and sc["LIZ"] == ["sa2_chaos_0", "sm64_yoshi"]
    assert all(SC.franchise(s) == "SM64DS" for s in ("mario_hd", "sm64_yoshi", "sm64ds_ukiki", "mario"))
    assert SC.franchise("sa2_rouge") == "SA2" and DM.franchise("luigi_hd") == "SM64DS"
    # Soul Calibur II: --pool mario
    assert SC2.pool_slugs(lib, "mario") == ["luigi_hd", "mario_hd", "sm64_yoshi", "sm64ds_koopa_troopa"]


@pytest.mark.parametrize("spec", ["mario", "Mario characters", "mario hd"])
def test_mario_group_aliases(spec):
    assert CS.resolve_source(spec, collection())["best_per_character"] == ["mario"]


def test_hd_builds_name_the_mario_group_in_their_markers():
    """#1748: a build whose Mario side holds HD / SM64 models says so in its title, and its cast_source maps back to
    source=mario (special_builds.source_spec); the SM64 DS builds keep their wording."""
    from gbox import special_builds as SB
    src, words = CS.mario_side(["mario_hd", "sm64ds_ukiki"])
    assert src == CS.GROUPS["mario"]["label"] and "HD" in words
    assert SB.source_spec(f"Sonic Adventure 2 (USA) + {src}") == "Sonic Adventure 2 (USA), mario"
    assert CS.mario_side(["sm64_yoshi"])[0] == src
    assert CS.mario_side(["sm64ds_mario", "sm64ds_ukiki"]) == ("Super Mario 64 DS (USA)", "Super Mario 64 DS")
    # SoulCalibur DC marker
    plan = [{"fighter": "MIT", "name": "Mitsurugi", "costume": 0, "entry": 0, "character": "sonic"},
            {"fighter": "MIT", "name": "Mitsurugi", "costume": 1, "entry": 1, "character": "mario_hd"}]
    res = {"image": "x.gdi", "reports": [], "failures": [], "verification": {"ok": True}, "random_select": None}
    assert SC.marker("m", "g", Path("x.gdi"), plan, res, "t")["cast_source"] == f"Sonic Adventure 2 (USA) + {src}"
    plan[1]["character"] = "sm64ds_mario"
    assert SC.marker("m", "g", Path("x.gdi"), plan, res, "t")["cast_source"] == \
        "Sonic Adventure 2 (USA) + Super Mario 64 DS (USA)"
    # Soul Calibur II description
    assert "Super Mario HD" in SC2.random_desc({("mitsurugi", 0): "sonic", ("mitsurugi", 1): "peach_hd"})
    assert SC2.random_desc({("mitsurugi", 0): "sa2_rouge", ("mitsurugi", 1): "sm64ds_peach"}) == \
        "Soul Calibur II: Sonic Adventure 2 vs Super Mario 64 DS, a random costume per selection"
