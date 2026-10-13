"""GTA Vice City (classic PC port) swap writer (gbox/gta_vc_swap.py): slots, ped family, the skinned DFF / 8888 TXD
encode, the rebuilt IMG inside a filemods mod dir, the op=use routing for a Definitive Edition install. A retarget
of the real Ganondorf (melee_ganondorf) runs when his glTF is on this node; the owned-install check skips otherwise."""
from __future__ import annotations

import json
import os
import types
from pathlib import Path

import numpy as np
import pytest

from gbox import gta_rw as R
from gbox import gta_vc_models as M
from gbox import gta_vc_swap as S

import gta_vc_synth as Y

OWNED_BAT = Path("//10.89.1.125/HyperSpin Attraction/Arcade/collections/PC Games/roms/Grand Theft Auto Vice City.bat")
GANON = next((p for p in [Path(os.environ.get("GBOX_TEST_DONOR", "")),
                          Path("D:/gBox/cache/characters/melee_ganondorf/melee_Ganondorf.gltf"),
                          Path.home() / "gbox-cache/characters/melee_ganondorf/melee_Ganondorf.gltf"] if p.is_file()), None)
# melee_ganondorf's rig.roles as the collection records them (GET /api/characters/melee_ganondorf, 2026-10-12)
GANON_ROLES = {"hip": "j004_HipN", "chest": "j017_BustN", "neck": "j017_BustN", "head": "j017_BustN",
               "l_clav": "j020_LShoulderJA", "l_upper": "j022_LArmJ", "l_fore": "j023_LHandN", "l_hand": "j025_L1stNa",
               "r_clav": "j064_RShoulderJA", "r_upper": "j066_RArmJ", "r_fore": "j067_RHandN", "r_hand": "j069_R1stNa",
               "l_thigh": "j006_LLegJ", "l_shin": "j007_LKneeJ", "l_foot": "j009_LFootJ",
               "r_thigh": "j012_RLegJ", "r_shin": "j013_RKneeJ", "r_foot": "j015_RFootJ"}


def test_game_ids_are_the_two_windows_native_entries():
    assert set(S.GAME_IDS) == {"5eacc9f11d9a5956", "1fd42f50b10252e6"} and "a2961272cbfaf3a8" not in S.GAME_IDS


def test_parse_slot():
    assert S.parse_slot("player") == ("player", None) and S.parse_slot("") == ("player", None)
    assert S.parse_slot("ped:male01") == ("ped", "male01") and S.parse_slot("ped:Cop.dff") == ("ped", "cop")
    assert S.parse_slot("peds:all") == ("peds", "all") and S.parse_slot("all") == ("all", None)
    for bad in ("enemies", "ped:", "ped:../x", "roster"):
        with pytest.raises(ValueError):
            S.parse_slot(bad)


def test_ped_family_and_slot_targets(tmp_path):
    inst = Y.install(tmp_path / "vc")
    img = M.ImgArchive(inst["img"], inst["dir"])
    assert S.ped_family(img, Y.IDE) == ["cop", "male01"]                      # zzz.dff is not on Tommy's skeleton
    assert S.ped_family(img, None) == ["cop", "male01"]                       # archive scan without an .ide
    assert S.ped_txds(inst) == {"player": "player", "cop": "cop", "male01": "male01"}
    assert S.slot_targets(img, inst, "player") == [("player", "player")]
    assert S.slot_targets(img, inst, "ped:cop") == [("cop", "cop")]
    assert S.slot_targets(img, inst, "peds:all") == [("cop", "cop"), ("male01", "male01")]
    assert S.slot_targets(img, inst, "all") == [("player", "player"), ("cop", "cop"), ("male01", "male01")]
    with pytest.raises(ValueError, match="no nope.dff"):
        S.slot_targets(img, inst, "ped:nope")


def test_skinned_geometry_and_build_dff_keep_the_rig():
    c = M.Clump(Y.ped_dff())
    head, lhand, rfoot = c.roles["head"], c.roles["l_hand"], c.roles["r_foot"]
    tri = np.array([[0, 1, 2]])
    prims = [{"pos": np.array([[0, 0, 0.6], [0.1, 0, 0.6], [0, 0.1, 0.7]]), "nrm": np.tile([0, -1.0, 0], (3, 1)),
              "tris": tri, "J": np.array([[head, 0, 0, 0]] * 3)},
             {"pos": np.array([[-0.7, 0, 0.5], [-0.8, 0, 0.5], [-0.7, 0.1, 0.5]]), "nrm": np.tile([0, -1.0, 0], (3, 1)),
              "tris": tri, "J": np.array([[lhand, 0, 0, 0]] * 3)},
             {"pos": np.array([[0.1, 0, -0.95], [0.2, 0, -0.95], [0.1, 0.1, -0.95]]), "nrm": np.tile([0, -1.0, 0], (3, 1)),
              "tris": tri, "J": np.array([[rfoot, 0, 0, 0]] * 3)},
             {"pos": np.array([[0, 0, 0], [0.1, 0, 0], [0, 0.1, 0]]), "nrm": np.tile([0, -1.0, 0], (3, 1)),
              "tris": tri, "J": np.array([[0, 0, 0, 0]] * 3)}]                 # frame 0 (no bone) -> bone 0 (Root)
    uvs = [np.array([[[0, 0], [1, 0], [0, 1]]], float)] * 4
    g, idx, w = S.skinned_geometry(c, prims, uvs, 0)
    assert len(g.pos) == 12 and len(g.tris) == 4 and g.uv.shape == (12, 2)
    assert sorted(set(idx[:, 0].tolist())) == sorted({c.frame_bone[head], c.frame_bone[lhand], c.frame_bone[rfoot], 0})
    assert np.allclose(w[:, 0], 1) and np.allclose(g.nrm[0], [0, -1, 0])
    dff = S.build_dff(c, g, idx, w, "atlas")
    n = M.Clump(dff)
    assert [f["name"] for f in n.frames] == [f["name"] for f in c.frames] and n.hanim == c.hanim and n.atomics == c.atomics
    assert np.allclose([f["world"] for f in n.frames], [f["world"] for f in c.frames])
    sg = n.geometry(0)
    assert np.allclose(sg.skin.inv_bind, c.geometry(0).skin.inv_bind) and sg.skin.num_bones == 24
    assert np.allclose(sg.geom.pos, g.pos) and np.array_equal(sg.skin.idx, idx)
    assert M.material_textures(n.geoms[0]) == ["atlas"]
    assert S.dff_parts(dff) == {"Head": 1, "L Hand": 1, "R Foot": 1, "Root": 1}
    root, tail = R.parse(dff)
    assert root.to_bytes() + tail == dff


def test_swap_files_with_a_synthetic_donor(tmp_path):
    inst = Y.install(tmp_path / "vc")
    img = M.ImgArchive(inst["img"], inst["dir"])
    donor = Y.donor_glb(tmp_path / "donor.glb")
    r = S.swap_files(img, donor, Y.DONOR_ROLES, tmp_path, None, None, "cop", "cop")
    assert r["model"] == "cop" and r["triangles"] == 16 * 12 and r["note"] is None
    assert set(r["orig_sha256"]) == {"cop.dff", "cop.txd"} and r["roles"]["head"] == "Head"
    parts = r["parts"]
    assert parts["Head"] == 12 and parts["L Hand"] == 12 and parts["R Foot"] == 12 and parts["Spine1"] >= 12
    for k in ("dff", "txd_bytes"):
        root, tail = R.parse(r[k])
        assert root.to_bytes() + tail == r[k]
    n = M.Clump(r["dff"])
    assert n.hanim == M.Clump(img.entry("cop.dff")).hanim and M.material_textures(n.geoms[0]) == ["cop"]
    rs = M.txd_rasters(r["txd_bytes"])
    assert rs[0].name == "cop" and rs[0].fmt & 0xF00 == 0x500 and rs[0].width == 256 and rs[0].depth == 32
    assert np.abs(M.raster_rgba(rs[0]).astype(int) - r["atlas"]).max() == 0 and rs[1].dxt == 1
    assert img.entry("cop.dff") == M.Clump(img.entry("cop.dff")).raw               # source archive untouched


@pytest.mark.skipif(GANON is None, reason="melee_ganondorf glTF not on this node (GBOX_TEST_DONOR or the collection cache)")
def test_swap_files_with_ganondorf(tmp_path):
    inst = Y.install(tmp_path / "vc")
    img = M.ImgArchive(inst["img"], inst["dir"])
    r = S.swap_files(img, GANON, GANON_ROLES, tmp_path, None, None, "player", "player")
    assert r["triangles"] >= 1000 and r["vertices"] >= 500
    parts = r["parts"]
    assert parts["Head"] > 100 and parts["L Hand"] > 20 and parts["R Hand"] > 20 and parts["L Foot"] > 10
    assert parts.get("Spine", 0) + parts.get("Spine1", 0) + parts.get("Pelvis", 0) > 200   # chest/neck/head share one Melee joint
    n = M.Clump(r["dff"])
    sg = n.geometry(0)
    assert sg.skin.idx[:, 0].max() < 24 and np.allclose(sg.skin.w[:, 0], 1)
    z = sg.geom.pos[:, 2]
    assert z.max() > 0.5 and z.min() < -0.8                                     # head above the neck, feet near the floor
    assert np.abs(sg.geom.pos[:, 0]).max() < 1.0


def _cfg(tmp_path):
    return types.SimpleNamespace(cache=str(tmp_path / "cache"))


def test_build_mod_rebuilds_the_img_in_a_filemods_copy(tmp_path):
    inst = Y.install(tmp_path / "vc")
    game = {"game_id": "1fd42f50b10252e6", "title": "Grand Theft Auto Vice City", "platform": "windows_native"}
    donor = Y.donor_glb(tmp_path / "donor.glb")
    before = Path(inst["img"]).read_bytes()
    r = S.build_mod(_cfg(tmp_path), game, Path(inst["exe"]), donor, Y.DONOR_ROLES, "gtavc_donor_peds", "peds:all")
    assert r["models"] == ["cop", "male01"] and r["skipped"] == {} and set(r["new_sha256"]) == {"cop.dff", "cop.txd", "male01.dff", "male01.txd"}
    out = Path(r["dir"])
    assert out == tmp_path / "cache" / "mods" / game["game_id"] / "gtavc_donor_peds"
    meta = json.loads((out / ".gbox-mod.json").read_text())
    assert meta["name"] == "gtavc_donor_peds" and meta["slot"] == "peds:all" and meta["install_kind"] == "classic"
    assert sorted(meta["files"]) == ["models/gta3.dir", "models/gta3.img"] and meta["exe"] == "gta-vc.exe"
    assert (out / "gta-vc.exe").exists() and (out / "data" / "default.ide").exists() and (out / "anim" / "ped.ifp").exists()
    new = M.ImgArchive(out / "models" / "gta3.img", out / "models" / "gta3.dir")
    old = M.ImgArchive(inst["img"], inst["dir"])
    assert new.names() == old.names()
    assert new.entry("player.dff") == old.entry("player.dff") and new.entry("generic.col") == old.entry("generic.col")
    assert new.entry("cop.dff") != old.entry("cop.dff") and S.dff_parts(new.entry("cop.dff"))["Head"] == 12
    assert M.txd_rasters(new.entry("male01.txd"))[0].depth == 32
    offs = [e[0] for e in new.ents]
    assert offs == sorted(offs) and all(e[0] + e[1] == n for e, n in zip(new.ents, offs[1:] + [new.img.stat().st_size // R.SECTOR]))
    assert Path(inst["img"]).read_bytes() == before                             # the install is never written
    assert r["img_bytes"] == new.img.stat().st_size and "RocketLauncher" in r["launch"]


def test_use_on_a_definitive_edition_install_files_the_gap(tmp_path, monkeypatch):
    from gbox import char_coverage, characters as C
    de = tmp_path / "de"
    (de / "Gameface" / "Content" / "Paks" / "~mods").mkdir(parents=True)
    (de / "Gameface" / "Content" / "Paks" / "gta.pak").write_bytes(b"\0" * 8)
    exe = de / "Gameface" / "Binaries" / "Win64" / "ViceCity.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    bat = tmp_path / "Grand Theft Auto Vice City.bat"
    bat.write_text('@echo off\nset "GAMENAME=ViceCity.exe"\nset "GAMEPATH=\\de\\Gameface\\Binaries\\Win64\\\\"\nstart "" "%GAMEROOT%%GAMENAME%"\n')
    monkeypatch.setattr(C, "_rom", lambda ctx, game: bat)
    seen = {}

    def fake_no_writer(ctx, api, meta, game, need, inp):
        seen["need"] = need
        return {"status": "overlay", "gap": {"number": 220}}
    monkeypatch.setattr(char_coverage, "no_writer", fake_no_writer)
    game = {"game_id": "1fd42f50b10252e6", "title": "Grand Theft Auto Vice City", "platform": "windows_native",
            "launch": {"kind": "attract"}}
    inp = types.SimpleNamespace(slot="peds:all", session_id="", x=None, y=None, rebuild=False, launch=True)
    r = S.use(types.SimpleNamespace(config=_cfg(tmp_path)), {"slug": "melee_ganondorf", "name": "Ganondorf"}, game, inp)
    assert r["status"] == "overlay" and r["install"]["kind"] == "definitive" and r["writer"] == "gbox.gta_vc_swap"
    assert "SK_player" in seen["need"]["target"] and "Unreal" in seen["need"]["format"] and "~mods" in seen["need"]["format"]
    assert r["install"]["pak"] == str(de / "Gameface" / "Content" / "Paks" / "gta.pak")


def test_use_on_a_classic_install_builds_and_reports_the_exe(tmp_path, monkeypatch):
    from gbox import characters as C
    inst = Y.install(tmp_path / "vc")
    donor = Y.donor_glb(tmp_path / "donor.glb")
    monkeypatch.setattr(C, "_rom", lambda ctx, game: Path(inst["exe"]))
    monkeypatch.setattr(C, "_local_or_fetch", lambda ctx, meta, rel: donor)
    posted = []
    monkeypatch.setattr(C, "_api", lambda ctx, method, path, **kw: posted.append((method, path, kw.get("json"))) or {"id": "job1"})
    game = {"game_id": "5eacc9f11d9a5956", "title": "Grand Theft Auto: Vice City (USA)", "platform": "windows_native",
            "launch": {"kind": "attract"}}
    meta = {"slug": "donor", "name": "Donor", "model": "donor.glb", "rig": {"roles": Y.DONOR_ROLES}}
    ctx = types.SimpleNamespace(config=_cfg(tmp_path), progress=lambda p, m: None)
    inp = types.SimpleNamespace(slot="ped:male01", session_id="", rebuild=False, launch=True, x=None, y=None)
    r = S.use(ctx, meta, game, inp)
    assert r["mod"] == "gtavc_donor_male01" and r["status"] == "built" and r["build"]["models"] == ["male01"]
    assert r["launch"] is None and "gta-vc.exe" in r["message"] and r["replaces"] == "the male01 ped"
    assert posted[0][1] == "/api/characters/donor/targets" and posted[0][2]["slot"] == "ped:male01"
    r2 = S.use(ctx, meta, game, types.SimpleNamespace(slot="ped:male01", session_id="", rebuild=False, launch=False, x=None, y=None))
    assert r2["status"] == "ready" and r2["build"] is None                     # already built


@pytest.mark.skipif(not OWNED_BAT.exists(), reason="HyperSpin share with the owned Vice City not reachable")
def test_owned_install_kind_decides_the_route():
    inst = M.locate_install(OWNED_BAT)
    if inst["kind"] == "definitive":
        assert Path(inst["mods"]).is_dir() and "SK_player" not in inst["root"]
    else:
        img = M.ImgArchive(inst["img"], inst["dir"])
        assert "player.dff" in img and S.ped_family(img, Path(inst["ide"]).read_text("utf-8", "replace") if inst.get("ide") else None)
