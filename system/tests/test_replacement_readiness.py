"""Replacement readiness (gbox.replacement_readiness): the entry standard every reader's entry gets through the shared
post-collect step, the game slot table, the donor x slot compatibility index and the per-game report, on synthetic
models (no game files)."""
import json
from pathlib import Path

import numpy as np
import pytest

from gbox import characters as C
from gbox import gta_rw as R
from gbox import replacement_readiness as RR
from gbox.retarget_profile import ROLES

from gta_vc_synth import DONOR_JOINTS, cube_mesh

SM64 = "b7aecee966090bfa"
DOA2 = "1de2e7634f3161ff"
CLAY = "f87ec3e2f6b266a1"


def glb(path: Path, joints=DONOR_JOINTS, names=None, up="Y", arms_down=False, cubes=1, rgba=True) -> Path:
    """A skinned figure of cubes, one joint per (name, parent, position); up="Z" stands it on +Z."""
    js = []
    for n, p, pos in joints:
        x, y, z = pos
        if arms_down and n in ("l_fore", "l_hand", "r_fore", "r_hand"):
            sx = 0.2 if n[0] == "l" else -0.2
            x, y = sx, 1.5 - (0.25 if n.endswith("fore") else 0.5)
        js.append((n, p, (x, -z, y) if up == "Z" else (x, y, z)))
    centers = [pos for _n, _p, pos in js] * cubes
    P, N, U, B, T = cube_mesh(centers, list(range(len(js))) * cubes, size=0.03)
    world = []
    for _n, _p, pos in js:
        w = np.eye(4)
        w[:3, 3] = pos
        world.append(w)
    tex = np.full((16, 16, 4), 200, np.uint8) if rgba else None
    return R.write_skinned_glb(path, P, N, U, B, T, names or [f"j_{n}" for n, _p, _q in js],
                               [p for _n, p, _q in js], world, tex, "fig")


def entry(root: Path, slug: str, model: Path | None = None, kind="character", roles=None, game=("Test Game", "aa" * 8),
          **kw) -> dict:
    d = root / slug
    d.mkdir(parents=True, exist_ok=True)
    meta = {"slug": slug, "name": slug.replace("_", " ").title(), "kind": kind, "aliases": [],
            "source": {"game_title": game[0], "game_id": game[1], "platform": "test"},
            "model": model.name if model else "missing.glb", "rig": {"roles": roles or {}}, "stats": {},
            "targets": {}, **kw}
    if model is not None and model.parent != d:
        (d / model.name).write_bytes(model.read_bytes())
    (d / "meta.json").write_text(json.dumps(meta))
    return meta


@pytest.fixture(autouse=True)
def _fresh():
    RR._INDEX.clear()
    C._LIST_CACHE.clear()
    yield
    RR._INDEX.clear()
    C._LIST_CACHE.clear()


# ---------------------------------------------------------------- the entry standard

def test_unmapped_humanoid_gets_roles_proportions_and_is_ready(tmp_path):
    m = entry(tmp_path, "hero", glb(tmp_path / "hero.glb"))
    new, fixed = RR.compute(tmp_path, m)
    rd = new["readiness"]
    assert rd["status"] == "ready" and rd["ready"] and rd["kind"] == "humanoid", rd["missing"]
    assert new["rig"]["roles_source"] == "auto:name" and new["rig"]["roles_guessed"]
    assert RR.RETARGET_ROLES <= set(new["rig"]["roles"])
    assert any("body roles mapped" in f for f in fixed)
    # every one of the 18 roles is mapped or explicitly absent, with the reason
    assert set(ROLES) == set(r for r in ROLES if new["rig"]["roles"].get(r)) | set(rd["rig"]["roles_absent"])
    assert rd["rig"]["roles_absent"]["l_clav"].startswith("no clavicle joint")
    assert rd["model"]["up"] == "+Y" and rd["model"]["unit"] == "m" and rd["model"]["to_metres"] == 1.0
    assert rd["bind"]["pose"] == "T" and rd["bind"]["inverse_bind"]
    assert rd["facing"]["facing"] == "+Z"
    assert 0.5 < rd["proportions"]["hip_height"] < 0.7 and rd["proportions"]["arm_span"] > 0.7
    assert rd["mesh"]["triangles"] == 16 * 12 and rd["skin"]["max_influences"] == 1
    assert rd["textures"]["count"] == 1 and rd["textures"]["max_side"] == 16 and rd["textures"]["atlas"]
    assert rd["hints"]["rigid"] and rd["hints"]["pose"] == "T"
    assert not RR.stale(tmp_path, new)


def test_reader_roles_are_kept_and_only_missing_ones_filled(tmp_path):
    own = {"hip": "j_hip", "head": "j_head", "l_upper": "j_l_upper", "r_upper": "j_r_upper",
           "l_thigh": "j_l_thigh", "r_thigh": "j_r_thigh"}
    m = entry(tmp_path, "reader", glb(tmp_path / "reader.glb"), roles=own)
    new, fixed = RR.compute(tmp_path, m)
    roles = new["rig"]["roles"]
    assert all(roles[k] == v for k, v in own.items())
    assert new["rig"]["roles_filled"] and "l_hand" in roles and "roles_source" not in new["rig"]
    assert new["readiness"]["rig"]["roles_source"] == "reader"
    assert new["readiness"]["status"] == "ready"


def test_generic_joint_names_map_from_the_skeleton_shape(tmp_path):
    names = [f"node{i:03d}" for i in range(len(DONOR_JOINTS))]
    m = entry(tmp_path, "nodes", glb(tmp_path / "nodes.glb", names=names))
    new, _f = RR.compute(tmp_path, m)
    roles = new["rig"]["roles"]
    assert new["rig"]["roles_source"] in ("auto:tree", "auto:pose")
    assert RR.HUMANOID_CORE <= set(roles)
    assert roles["l_upper"] == "node004" and roles["r_thigh"] == "node013"     # left = +X when facing +Z


def test_z_up_model_is_limited_with_an_up_fix_hint(tmp_path):
    roles = {n: f"j_{n}" for n, _p, _q in DONOR_JOINTS}
    m = entry(tmp_path, "zup", glb(tmp_path / "zup.glb", up="Z"), roles=roles)
    rd = RR.compute(tmp_path, m)[0]["readiness"]
    assert rd["model"]["up"] == "+Z" and rd["status"] == "limited"
    assert any("+Z up" in x for x in rd["missing"]) and rd["hints"]["up_fix"].startswith("rotate -90")


def test_arms_down_rest_pose_and_game_units_are_recorded(tmp_path):
    big = [(n, p, tuple(v * 100 for v in q)) for n, p, q in DONOR_JOINTS]
    m = entry(tmp_path, "big", glb(tmp_path / "big.glb", joints=big))
    rd = RR.compute(tmp_path, m)[0]["readiness"]
    assert rd["model"]["unit"] == "units" and rd["model"]["to_metres"] == pytest.approx(1.7 / rd["model"]["height"], rel=1e-3)
    m = entry(tmp_path, "down", glb(tmp_path / "down.glb", arms_down=True))
    rd = RR.compute(tmp_path, m)[0]["readiness"]
    assert rd["bind"]["pose"] == "arms_down" and any("arms down" in w for w in rd["warnings"])


def test_creature_sprite_prop_and_unrigged_character(tmp_path):
    tail = [("root", -1, (0, 0.3, 0))] + [(f"tail{i}", i, (0, 0.3, -0.1 * (i + 1))) for i in range(5)]
    m = entry(tmp_path, "worm", glb(tmp_path / "worm.glb", joints=tail, names=[n for n, _p, _q in tail]))
    rd = RR.compute(tmp_path, m)[0]["readiness"]
    assert rd["kind"] == "creature" and rd["status"] == "limited"
    assert set(rd["rig"]["roles_absent"]) == set(ROLES) and "creature" in rd["rig"]["roles_absent"]["hip"]

    from PIL import Image
    (tmp_path / "sheet").mkdir()
    Image.new("RGBA", (64, 32), (255, 0, 0, 255)).save(tmp_path / "sheet" / "sheet.png")
    m = entry(tmp_path, "sheet", tmp_path / "sheet" / "sheet.png", kind="sprites")
    rd = RR.compute(tmp_path, m)[0]["readiness"]
    assert rd["kind"] == "sprite" and rd["status"] == "ready" and rd["model"]["sheet"] == [64, 32]
    assert set(rd["rig"]["roles_absent"]) == set(ROLES)

    m = entry(tmp_path, "cab", glb(tmp_path / "cab.glb"), kind="vehicle")
    assert RR.compute(tmp_path, m)[0]["readiness"]["status"] == "n/a"

    m = entry(tmp_path, "gone", None)
    rd = RR.compute(tmp_path, m)[0]["readiness"]
    assert rd["status"] == "blocked" and rd["missing"] == ["model file missing"]


def test_name_roles_reads_common_conventions():
    mixamo = ["mixamorig:Hips", "mixamorig:Spine", "mixamorig:Spine1", "mixamorig:Spine2", "mixamorig:Neck",
              "mixamorig:Head", "mixamorig:HeadTop_End", "mixamorig:LeftShoulder", "mixamorig:LeftArm",
              "mixamorig:LeftForeArm", "mixamorig:LeftHand", "mixamorig:LeftHandIndex1", "mixamorig:RightShoulder",
              "mixamorig:RightArm", "mixamorig:RightForeArm", "mixamorig:RightHand", "mixamorig:LeftUpLeg",
              "mixamorig:LeftLeg", "mixamorig:LeftFoot", "mixamorig:LeftToeBase", "mixamorig:RightUpLeg",
              "mixamorig:RightLeg", "mixamorig:RightFoot"]
    parent = {"mixamorig:Spine": "mixamorig:Hips", "mixamorig:Spine1": "mixamorig:Spine",
              "mixamorig:Spine2": "mixamorig:Spine1", "mixamorig:LeftShoulder": "mixamorig:Spine2",
              "mixamorig:RightShoulder": "mixamorig:Spine2", "mixamorig:LeftArm": "mixamorig:LeftShoulder",
              "mixamorig:RightArm": "mixamorig:RightShoulder"}
    r = RR.name_roles(mixamo, parent)
    assert r["hip"] == "mixamorig:Hips" and r["head"] == "mixamorig:Head" and r["chest"] == "mixamorig:Spine2"
    assert r["l_clav"] == "mixamorig:LeftShoulder" and r["l_upper"] == "mixamorig:LeftArm"
    assert r["l_fore"] == "mixamorig:LeftForeArm" and r["l_hand"] == "mixamorig:LeftHand"
    assert r["r_thigh"] == "mixamorig:RightUpLeg" and r["r_shin"] == "mixamorig:RightLeg"
    biped = ["Bip01 Pelvis", "Bip01 Spine", "Bip01 Neck", "Bip01 Head", "Bip01 L Clavicle", "Bip01 L UpperArm",
             "Bip01 L Forearm", "Bip01 L Hand", "Bip01 R Thigh", "Bip01 R Calf", "Bip01 R Foot"]
    r = RR.name_roles(biped)
    assert r["hip"] == "Bip01 Pelvis" and r["l_clav"] == "Bip01 L Clavicle" and r["l_upper"] == "Bip01 L UpperArm"
    assert r["r_shin"] == "Bip01 R Calf" and r["r_foot"] == "Bip01 R Foot"
    glitch = ["Groin", "Waist", "Torso", "Neck", "Head", "L_Arm_Upper", "L_Arm_Lower", "L_Hand", "L_Leg_Upper",
              "L_Knee", "L_Foot_Back"]
    r = RR.name_roles(glitch)
    assert r["l_upper"] == "L_Arm_Upper" and r["l_fore"] == "L_Arm_Lower" and r["l_shin"] == "L_Knee"


# ---------------------------------------------------------------- the shared post-collect step

def test_add_runs_the_post_collect_step_for_every_reader(tmp_path):
    src = glb(tmp_path / "src.glb")
    lib = tmp_path / "lib"
    meta = C.add(lib, "newbie", "Newbie", [src], {"game_title": "Test Game", "game_id": "aa" * 8}, "test reader")
    assert meta["readiness"]["status"] == "ready" and meta["rig"]["roles_source"] == "auto:name"
    assert json.loads((lib / "newbie" / "meta.json").read_text())["readiness"]["version"] == RR.READINESS_VERSION


def test_extract_dedicated_backfills_readiness_of_an_entry_already_in_the_collection(tmp_path, monkeypatch):
    m = entry(tmp_path, "old", glb(tmp_path / "old.glb"))
    monkeypatch.setattr(C, "DEDICATED", [("fixture", lambda t, p: True,
                                          lambda: [{"slug": "old", "name": "Old", "aliases": []}], None)])
    monkeypatch.setattr(C, "verify_entry", lambda root, meta: {"ok": True})
    monkeypatch.setattr(C, "dedicated_entries", lambda cfg, game, name, roster: roster())
    from types import SimpleNamespace
    ctx = SimpleNamespace(config=SimpleNamespace(cache=str(tmp_path / "cache")), progress=lambda *a: None)
    res = C.extract_dedicated(ctx, {"title": "x", "platform": "test", "game_id": "aa" * 8}, "old", tmp_path)
    assert res["status"] == "in_collection" and res["entry"]["readiness"]["status"] == "ready"
    assert C.get(tmp_path, "old")["readiness"]["roles_digest"] == res["entry"]["readiness"]["roles_digest"]
    assert m.get("readiness") is None


def test_readiness_goes_stale_with_a_new_version_model_or_roles(tmp_path, monkeypatch):
    m = entry(tmp_path, "s", glb(tmp_path / "s.glb"))
    new = RR.post_collect(tmp_path, m, write=True)
    assert not RR.stale(tmp_path, new)
    assert RR.stale(tmp_path, new | {"rig": dict(new["rig"], roles={"hip": "j_hip"})})
    monkeypatch.setattr(RR, "READINESS_VERSION", RR.READINESS_VERSION + 1)
    assert RR.stale(tmp_path, new)


def test_post_collect_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(RR, "compute", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out = RR.post_collect(tmp_path, {"slug": "x", "name": "X"})
    assert out["readiness"]["status"] == "blocked" and "boom" in out["readiness"]["missing"][0]


# ---------------------------------------------------------------- slots, specs and compatibility

def test_every_writer_has_a_target_spec():
    from gbox import char_coverage as CC
    writers = [f"gbox.{w}" for w, *_r in CC.WRITERS] + ["gbox.characters.build_re4 (+ re4wii)", "gbox.oot_swap"]
    for w in writers:
        sp = RR.spec_for(w)
        assert sp["known"], w
        assert sp["required"] is not None and isinstance(sp["roles"], list)
        assert sp["tris"] is None or isinstance(sp["tris"], int)
    assert RR.spec_for("gbox.sm64_swap")["tris"] == 1600 and RR.spec_for("gbox.sm64_swap")["influences"] == 1
    assert set(RR.spec_for("gbox.doa2_swap")["required"]) == RR.RETARGET_ROLES
    assert RR.spec_for("gbox.clayfighter_swap")["kind"] == "sprite"
    assert RR.spec_for("gbox.mgs_vr_swap")["donors"] == ["hucast"]


def test_slot_table_lists_writer_games_with_reader_and_slots():
    tab = RR.slot_table(RR.known_games([]))
    assert tab[SM64]["writer"] == "gbox.sm64_swap" and tab[SM64]["routed"] and tab[SM64]["reader"] == "sm64"
    assert [s["slot"] for s in tab[SM64]["slots"]] == ["player"]
    assert len(tab[DOA2]["slots"]) > 5 and tab[CLAY]["spec"] == "gbox.clayfighter_swap"


def test_compat_budget_roles_kinds_and_writer_limits():
    sm64 = RR.spec_for("gbox.sm64_swap")
    hero = {"kind": "character", "body": "humanoid", "status": "ready", "roles": sorted(RR.RETARGET_ROLES),
            "tris": 4000, "verts": 2500, "influences": 4, "tex": 1024, "up": "+Y"}
    row = RR.compat(hero, sm64)
    assert row["ok"] and row["fit"] == "decimate" and row["ratio"] == pytest.approx(0.4)
    assert set(row["missing_roles"]) == {"neck", "l_clav", "r_clav"}
    assert any("-> 1 (rigid)" in n for n in row["notes"]) and any("<= 64 px" in n for n in row["notes"])
    assert RR.compat(hero | {"tris": 900}, sm64)["fit"] == "fits"
    assert not RR.compat(hero | {"roles": ["head"]}, sm64)["ok"]                     # no hip
    assert not RR.compat(hero | {"body": "sprite"}, sm64)["ok"]
    assert not RR.compat(hero, RR.spec_for("gbox.clayfighter_swap"))["ok"]
    assert RR.compat({"kind": "sprites", "body": "sprite", "status": "ready", "roles": []},
                     RR.spec_for("gbox.clayfighter_swap"))["ok"]
    doa2 = RR.spec_for("gbox.doa2_swap")
    assert not RR.compat(hero | {"roles": ["hip", "head", "chest"]}, doa2)["ok"]
    assert RR.compat(hero, doa2)["ok"]
    mgs = RR.spec_for("gbox.mgs_vr_swap")
    assert not RR.compat(hero, mgs, slug="sonic")["ok"] and RR.compat(hero, mgs, slug="hucast")["ok"]
    creature = hero | {"body": "creature", "roles": [], "status": "limited"}
    assert not RR.compat(creature, sm64)["ok"]
    # the operator's Retarget editor roles for that game count
    assert RR.compat(creature | {"profile_roles": {SM64: ["hip", "head"]}}, sm64, SM64)["ok"]


def test_role_names_in_the_wrong_case_are_matched_to_the_joints(tmp_path):
    """GTA III Claude's reader stored 'smid' for the GLB joint 'Smid': writers look bones up by exact name."""
    names = [f"S{n.title().replace('_', '')}" for n, _p, _q in DONOR_JOINTS]
    roles = {n: names[i].lower() for i, (n, _p, _q) in enumerate(DONOR_JOINTS)}
    m = entry(tmp_path, "claude", glb(tmp_path / "claude.glb", names=names), roles=roles)
    new, fixed = RR.compute(tmp_path, m)
    assert new["rig"]["roles"]["hip"] == "SHip" and set(new["rig"]["roles_case_fixed"]) == set(roles)
    assert new["readiness"]["status"] == "ready" and any("(case)" in f for f in fixed)


def test_hierarchy_fills_the_chest_and_a_lone_hand(tmp_path):
    """FF7 Cloud's reader maps no chest; Tifa's lacks a hand: the joint tree gives them away."""
    names = [f"j{i:02d}" for i in range(len(DONOR_JOINTS))]
    full = {n: names[i] for i, (n, _p, _q) in enumerate(DONOR_JOINTS)}
    partial = {r: b for r, b in full.items() if r not in ("chest", "neck", "r_hand")}
    m = entry(tmp_path, "cloud", glb(tmp_path / "cloud.glb", names=names), roles=partial)
    new, fixed = RR.compute(tmp_path, m)
    roles = new["rig"]["roles"]
    assert roles["chest"] == full["chest"] and roles["r_hand"] == full["r_hand"]
    assert new["readiness"]["status"] == "ready" and any(f.startswith("filled") for f in fixed)
    # the optional neck is only suggested: a reader-mapped entry keeps fitting as it did
    rd = new["readiness"]
    assert "neck" not in roles and rd["suggested_roles"]["neck"] == full["neck"]
    assert "suggests" in rd["rig"]["roles_absent"]["neck"]


def test_the_readers_own_role_reader_comes_first(tmp_path, monkeypatch):
    """PSO classes were stored without roles; characters.ROLE_BACKFILL['pso'] reads them from the entry's files."""
    from gbox import cast_swap
    names = [f"node{i:03d}" for i in range(len(DONOR_JOINTS))]
    want = {n: names[i] for i, (n, _p, _q) in enumerate(DONOR_JOINTS)}
    monkeypatch.setitem(C.ROLE_BACKFILL, "fixture", lambda path: dict(want))
    monkeypatch.setattr(cast_swap, "extractor_of", lambda meta: "fixture")
    m = entry(tmp_path, "cls", glb(tmp_path / "cls.glb", names=names))
    new, fixed = RR.compute(tmp_path, m)
    assert new["rig"]["roles_source"] == "reader backfill" and new["rig"]["roles"]["l_hand"] == want["l_hand"]
    assert new["readiness"]["status"] == "ready"


def test_a_limb_that_ends_early_is_an_explicit_absence_not_a_gap(tmp_path):
    """OoT's Zelda: the legs end at the shin; no foot joint exists, so nothing is missing."""
    joints = [j for j in DONOR_JOINTS if j[0] not in ("l_foot", "r_foot")]
    idx = {n: i for i, (n, _p, _q) in enumerate(joints)}
    old = [n for n, _p, _q in DONOR_JOINTS]
    joints = [(n, idx[old[p]] if p >= 0 else -1, q) for n, p, q in joints]
    roles = {n: f"j_{n}" for n, _p, _q in joints}
    m = entry(tmp_path, "zl", glb(tmp_path / "zl.glb", joints=joints), roles=roles)
    rd = RR.compute(tmp_path, m)[0]["readiness"]
    assert rd["rig"]["roles_absent"]["l_foot"] == "no foot joint (the limb ends at the shin)"
    assert rd["status"] == "ready"


def _library(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    a = RR.post_collect(lib, entry(lib, "hero", glb(tmp_path / "hero.glb")), write=True)
    b = RR.post_collect(lib, entry(lib, "tiny", glb(tmp_path / "tiny.glb", cubes=10)), write=True)
    tail = [("root", -1, (0, 0.3, 0))] + [(f"tail{i}", i, (0, 0.3, -0.1 * (i + 1))) for i in range(5)]
    c = RR.post_collect(lib, entry(lib, "worm", glb(tmp_path / "worm.glb", joints=tail,
                                                     names=[n for n, _p, _q in tail])), write=True)
    entry(lib, "unchecked", glb(tmp_path / "unchecked.glb"), roles={n: f"j_{n}" for n, _p, _q in DONOR_JOINTS})
    return lib, (a, b, c)


def test_index_answers_who_can_replace_a_slot_and_updates_on_put_meta(tmp_path):
    lib, (hero, tiny, worm) = _library(tmp_path)
    ix = RR.index(lib)
    got = RR.candidates(ix, SM64, "player")
    slugs = [c["slug"] for c in got["candidates"]]
    assert got["writer"] == "gbox.sm64_swap" and "worm" not in slugs
    assert slugs[:2] == ["hero", "tiny"] and "unchecked" in slugs          # unchecked ranks after checked donors
    fit = {c["slug"]: c for c in got["candidates"]}
    assert fit["hero"]["fit"] == "fits" and fit["tiny"]["fit"] == "decimate"      # 1920 triangles > Mario's 1600
    assert fit["tiny"]["ratio"] == pytest.approx(1600 / 1920, abs=1e-3)
    every = RR.candidates(ix, SM64, "player", include_all=True)
    assert next(c for c in every["candidates"] if c["slug"] == "worm")["blocking"]
    # a write through put_meta invalidates the donor: drop its hip and it is no longer a candidate
    C.put_meta(lib, hero | {"rig": dict(hero["rig"], roles={"head": "j_head"})})
    slugs = [c["slug"] for c in RR.candidates(RR.index(lib), SM64, "player")["candidates"]]
    assert "hero" not in slugs
    v = RR.donor_view(RR.index(lib), "tiny")
    assert v["compatible_games"] > 5 and any(g["game_id"] == SM64 and g["ok"] for g in v["games"])
    assert RR.save(lib, force=True).is_file()
    assert not (lib / RR.INDEX_DIR / "meta.json").exists()
    assert "hero" in {m["slug"] for m in C.list_all(lib)} and len(C.list_all(lib)) == 4


def test_index_survives_a_restart_through_its_file(tmp_path):
    lib, _ = _library(tmp_path)
    RR.index(lib)
    RR.save(lib, force=True)
    RR._INDEX.clear()
    ix = RR.index(lib)
    assert set(ix["donors"]) == {"hero", "tiny", "worm", "unchecked"}
    assert RR.candidates(ix, SM64)["compatible"] >= 2


def test_backfill_report_and_markdown(tmp_path):
    lib, _ = _library(tmp_path)
    out = RR.backfill(lib)
    assert out["updated"] == 1 and out["skipped_current"] == 3                # only the unchecked entry is computed
    rep = out["report"]
    g = next(r for r in rep["games"] if r["game_id"] == "aa" * 8)
    assert g["entries"]["total"] == 4 and g["entries"]["ready"] == 3 and g["entries"]["limited"] == 1
    assert "creature: no humanoid body roles; humanoid slots need a role map (Retarget editor)" in \
        g["entries"]["why_not_ready"]
    sm = next(r for r in rep["games"] if r["game_id"] == SM64)
    assert sm["writer"]["routed"] and sm["writer"]["compatible_donors"] == 3 and sm["writer"]["ready"]
    assert sm["reader"] == "sm64" and sm["entries"]["total"] == 0
    md = RR.markdown(rep)
    assert "| Super Mario 64 (USA) | sm64 |" in md and "gbox.sm64_swap" in md
    assert RR.backfill(lib)["updated"] == 0


def test_collect_rows_carry_replacement_status(monkeypatch, tmp_path):
    from types import SimpleNamespace
    game = {"game_id": "fixture", "title": "Fixture", "platform": "test"}
    monkeypatch.setattr(C, "DEDICATED", [("fixture", lambda t, p: True,
                                          lambda: [{"slug": "a", "name": "a", "aliases": []}], None)])
    monkeypatch.setattr(C, "_game", lambda ctx, inp: game)
    monkeypatch.setattr(C, "library_root", lambda cfg: tmp_path)
    monkeypatch.setattr(C, "extract_dedicated", lambda *a: {"status": "in_collection", "entry": {"slug": "a"}})
    monkeypatch.setattr(C, "get", lambda root, slug: {"slug": slug, "name": slug, "rig": {"roles": {"hip": "h"}},
                                                      "readiness": {"status": "ready", "missing": []}})
    monkeypatch.setattr(C, "verify_entry", lambda root, meta: {"ok": True})
    res = C.collect(SimpleNamespace(config=None, progress=lambda *a: None), C.CharIn(op="collect"))
    assert res["entries"][0]["replacement"]["status"] == "ready" and res["replacement_ready"] == 1


def test_characters_op_readiness_runs_the_pass_where_the_library_is(tmp_path, monkeypatch):
    from types import SimpleNamespace
    lib, _ = _library(tmp_path)
    monkeypatch.setattr(C, "library_root", lambda cfg: lib)
    ctx = SimpleNamespace(config=None, progress=lambda *a: None)
    res = C.characters_tool(C.CharIn(op="readiness"), ctx)["result"]
    assert res["status"] == "done" and res["report"]["summary"]["entries"] == 4
    one = C.characters_tool(C.CharIn(op="readiness", character="hero", rebuild=True), ctx)["result"]
    assert one["updated"] == 1


# ---------------------------------------------------------------- HTTP

@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from gbox.config import Config
    from gbox.server import create_app
    lib, _ = _library(tmp_path)
    monkeypatch.setenv("GBOX_CHARACTERS", str(lib))
    cfg = Config(data_dir=tmp_path / "data")
    app = create_app(cfg)
    with TestClient(app) as c:
        c.headers["Authorization"] = f"Bearer {cfg.token()}"
        c.lib = lib
        yield c


def test_api_candidates_donor_slots_report(client):
    r = client.get(f"/api/replacement/candidates?game_id={SM64}&slot=player").json()
    assert r["writer"] == "gbox.sm64_swap" and [c["slug"] for c in r["candidates"]][:2] == ["hero", "tiny"]
    assert client.get(f"/api/replacement/candidates?game_id={SM64}&limit=1").json()["candidates"][0]["slug"] == "hero"
    d = client.get("/api/replacement/donor/worm").json()
    assert d["body"] == "creature" and d["compatible_games"] == 0
    assert client.get("/api/replacement/donor/nobody").status_code == 404
    s = client.get(f"/api/replacement/slots?game_id={SM64}").json()["games"][SM64]
    assert s["spec_detail"]["tris"] == 1600 and s["slots"][0]["slot"] == "player"
    rep = client.get("/api/replacement/report").json()
    assert rep["summary"]["entries"] == 4
    md = client.get("/api/replacement/report?format=md")
    assert md.status_code == 200 and "| Game | Reader |" in md.text
    assert client.post("/api/replacement/refresh").json()["donors"] == 4
    assert client.get("/api/characters").status_code == 200
    assert len(client.get("/api/characters").json()) == 4
