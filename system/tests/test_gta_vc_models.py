"""GTA Vice City (classic PC port) reader (gbox/gta_vc_models.py): synthetic IMG / DFF / TXD round trips always run;
the owned-install checks run when the HyperSpin share is reachable and skip otherwise."""
from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import gta_rw as R
from gbox import gta_vc_models as M

import gta_vc_synth as S

OWNED_BAT = Path("//10.89.1.125/HyperSpin Attraction/Arcade/collections/PC Games/roms/Grand Theft Auto Vice City.bat")


# ------------------------------------------------------------------------------------------------- versions / IMG
def test_rw_version_unpacks_library_ids():
    assert R.rw_version(0x1003FFFF) == 0x34003          # VC PC
    assert R.rw_version(0x1803FFFF) == 0x36003          # SA PC
    assert R.rw_version(0x0C02FFFF) == 0x33002          # GTA III PC
    assert R.rw_version(0x310) == 0x31000               # GTA III PS2 bare stamp


def test_img_dir_entries_and_reads(tmp_path):
    a, b = b"A" * 100, b"B" * 5000
    img, dr = S.write_img(tmp_path, [("a.dff", a), ("b.txd", b), ("c.col", b"C")])
    ar = M.ImgArchive(img, dr)
    assert ar.names() == ["a.dff", "b.txd", "c.col"] and ar.names(".dff") == ["a.dff"]
    assert [e[:2] for e in ar.ents] == [[0, 1], [1, 3], [4, 1]]
    assert "B.TXD" in ar and "x" not in ar
    assert ar.entry("A.DFF")[:100] == a and len(ar.entry("a.dff")) == R.SECTOR
    assert ar.entry("b.txd")[:5000] == b


def test_img_rebuild_recomputes_offsets_and_keeps_the_rest(tmp_path):
    img, dr = S.write_img(tmp_path / "src", [("a.dff", b"A" * 100), ("b.txd", b"B" * 5000), ("c.col", b"C" * 3000), ("d.dff", b"D" * 10)])
    ar = M.ImgArchive(img, dr)
    big, small = b"X" * 7000, b"Y" * 10
    new_dir = ar.rebuild(tmp_path / "out.img", {"A.dff": big, "b.txd": small})
    (tmp_path / "out.dir").write_bytes(new_dir)
    out = M.ImgArchive(tmp_path / "out.img", tmp_path / "out.dir")
    assert out.names() == ar.names()
    assert [e[:2] for e in out.ents] == [[0, 4], [4, 1], [5, 2], [7, 1]]
    assert (tmp_path / "out.img").stat().st_size == 8 * R.SECTOR
    assert out.entry("a.dff")[:7000] == big and out.entry("a.dff")[7000:] == b"\0" * (4 * R.SECTOR - 7000)
    assert out.entry("b.txd")[:10] == small
    assert out.entry("c.col") == ar.entry("c.col") and out.entry("d.dff") == ar.entry("d.dff")
    for k in range(len(ar.ents)):                                   # name fields verbatim
        assert new_dir[k * 32 + 8:k * 32 + 32] == dr.read_bytes()[k * 32 + 8:k * 32 + 32]
    with pytest.raises(KeyError):
        ar.rebuild(tmp_path / "x.img", {"nope.dff": b""})


def test_ide_peds_section():
    assert M.ide_peds(S.IDE) == [("player", "player"), ("cop", "cop"), ("male01", "male01")]
    assert M.ide_peds("objs\n1, x, y\nend\n") == []


# ------------------------------------------------------------------------------------------------------ DFF
def test_clump_round_trips_and_reads_frames_hanim_skin():
    dff = S.ped_dff()
    root, tail = R.parse(dff)
    assert root.to_bytes() + tail == dff
    c = M.Clump(dff)
    assert [f["name"] for f in c.frames] == [n for n, *_ in S.SKELETON]
    assert c.hanim["root"] == 1 and len(c.hanim["nodes"]) == 24
    assert c.hanim["ids"][:3] == [None, 0, 1] and c.hanim["ids"][6] == 5
    assert c.bone_frames == list(range(1, 25)) and c.frame_bone[6] == 5
    assert c.skinned == [(0, 0)] and c.version == M.VC_VERSION
    st = c.stats()
    assert st["bones"] == 24 and st["triangles"] == 24 * 12 and st["vertices"] == 24 * 8 and st["version"] == 0x34003
    assert np.allclose(c.frames[6]["world"][:3, 3], (0, 0, 0.62))


def test_role_map_prefers_bone_tags_then_names():
    c = M.Clump(S.ped_dff())
    names = {r: c.frames[i]["name"] for r, i in c.roles.items()}
    assert names["pelvis"] == "Pelvis" and names["hip"] == "Spine" and names["chest"] == "Spine1"
    assert names["head"] == "Head" and names["l_hand"] == "L Hand" and names["r_foot"] == "R Foot"
    assert names["l_clav"] == "Bip01 L Clavicle" and names["r_toe"] == "R Toe0"
    assert set(c.role_source.values()) == {"hanim"}
    assert set(M.REQUIRED_ROLES) <= set(c.roles)
    # no HAnim plugins at all: the Biped names carry it
    c2 = M.Clump(S.ped_dff(bones=False))
    assert set(c2.role_source.values()) == {"name"}
    assert c2.frames[c2.roles["l_upper"]]["name"] == "L UpperArm"
    # neither: a clear error naming what the file has
    with pytest.raises(ValueError, match="not a GTA VC ped clump"):
        M.Clump(S.ped_dff(names=False, bones=False))
    with pytest.raises(ValueError):
        M.Clump(S.rigid_dff())


def test_skin_plugin_decodes_and_encodes():
    c = M.Clump(S.ped_dff())
    sg = c.geometry(0)
    sk = sg.skin
    assert sk is not None and sk.num_bones == 24 and sk.max_weights == 1 and sk.used == list(range(24))
    assert sk.idx.shape == (24 * 8, 4) and sk.w.shape == (24 * 8, 4)
    assert sk.idx[8, 0] == 1 and sk.w[8].tolist() == [1, 0, 0, 0]
    assert np.allclose(sk.inv_bind[5][:3, 3], (0, 0, -0.62))         # Head's inverse bind = -world
    assert sk.split == struct.pack("<III", 0, 0, 0) and not sk.old
    nv = 5
    idx = np.array([[3, 4, 0, 0]] * nv, np.uint8)
    w = np.array([[0.75, 0.25, 0, 0]] * nv, np.float32)
    ch = M.skin_chunk(sk, idx, w, M.VC_VERSION)
    g = R.Chunk(R.GEOMETRY, M.VC_VERSION, container=True, kids=[R.Chunk(R.EXTENSION, M.VC_VERSION, container=True, kids=[ch])])
    back = M.skin_read(g, nv)
    assert back.used == [3, 4] and back.max_weights == 2
    assert np.array_equal(back.idx, idx) and np.allclose(back.w, w) and np.allclose(back.inv_bind, sk.inv_bind)
    old = M.skin_read(R.Chunk(R.GEOMETRY, 0x0C02FFFF, container=True,
                              kids=[R.Chunk(R.EXTENSION, 0x0C02FFFF, container=True, kids=[M.skin_chunk(sk, idx, w, 0x0C02FFFF)])]), nv)
    assert old.old and old.used == [] and np.allclose(old.inv_bind, sk.inv_bind)   # GTA III layout: 0xDEADDEAD per bone


def test_geometry_chunk_writes_new_vertices_with_their_skin():
    c = M.Clump(S.ped_dff())
    tmpl = c.geoms[0]
    P, N, U, B, T = S.cube_mesh([(0, 0, 0.6), (0.5, 0, 0.5)], [5, 9])
    idx = np.c_[B, np.zeros((len(B), 3))].astype(np.uint8)
    w = np.c_[np.ones(len(B)), np.zeros((len(B), 3))].astype(np.float32)
    g = M.geometry_chunk(R.Geom(P, N, U, T), tmpl, c.geometry(0).skin, idx, w)
    sg = M.geometry_read(g)
    assert np.allclose(sg.geom.pos, P) and np.allclose(sg.geom.uv, U) and np.array_equal(sg.geom.tris, T)
    assert np.array_equal(sg.skin.idx, idx) and sg.skin.used == [5, 9]
    assert M.material_textures(g) == ["player"]
    bm = [k for k in g.first(R.EXTENSION).kids if k.type == R.BINMESH][0]
    assert struct.unpack_from("<III", bm.data) == (0, 1, 24 * 3)                     # triangle list, 1 mesh
    assert R.parse(g.to_bytes())[0].to_bytes() == g.to_bytes()


def _native_chunk(meshes: list[dict]) -> R.Chunk:
    """A D3D8 Native Data PLG per gta_vc_models._d3d8_native_read's documented layout (test-side encoder)."""
    d = struct.pack("<II", M.D3D8, len(meshes))
    for m in meshes:
        fvf = 0x2 | 0x10 | 0x100
        d += struct.pack("<IiiiIIIIII4B", 0, 32, len(m["pos"]), len(m["idx"]), m["mat"], fvf, m["prim"], 0, 0, 0, 0, 0, 0, 0)
    for m in meshes:
        d += np.asarray(m["idx"], "<u2").tobytes()
        d += np.c_[m["pos"], m["nrm"], m["uv"]].astype("<f4").tobytes()
    return R.Chunk(R.NATIVEDATA, M.VC_VERSION, d)


def test_d3d8_native_geometry_decodes_lists_and_strips():
    pos = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], np.float32)
    nrm = np.tile([0, 0, 1], (4, 1)).astype(np.float32)
    uv = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32)
    nd = _native_chunk([{"pos": pos, "nrm": nrm, "uv": uv, "idx": [0, 1, 2, 0, 2, 3], "mat": 0, "prim": 4},
                        {"pos": pos + 5, "nrm": nrm, "uv": uv, "idx": [0, 1, 3, 2], "mat": 1, "prim": 5}])
    st = struct.pack("<IIII", M.GEOM_NATIVE | M.GEOM_TEX | M.GEOM_NRM, 0, 8, 1)
    g = R.Chunk(R.GEOMETRY, M.VC_VERSION, container=True,
                kids=[R.Chunk(R.STRUCT, M.VC_VERSION, st), M.material_list(["a", "b"]),
                      R.Chunk(R.EXTENSION, M.VC_VERSION, container=True, kids=[nd])])
    sg = M.geometry_read(g)
    assert sg.native and sg.skin is None
    assert np.allclose(sg.geom.pos[:4], pos) and np.allclose(sg.geom.pos[4:], pos + 5) and np.allclose(sg.geom.uv[:4], uv)
    assert sg.geom.tris[:2].tolist() == [[0, 1, 2], [0, 2, 3]]
    assert sg.geom.tris[2:].tolist() == [[4, 5, 7], [7, 5, 6]] and sg.geom.mat.tolist() == [0, 0, 1, 1]
    bad = _native_chunk([{"pos": pos, "nrm": nrm, "uv": uv, "idx": [0, 1, 2], "mat": 0, "prim": 4}])
    bad.data = bad.data[:8] + struct.pack("<Ii", 0, 20) + bad.data[16:]                # stride disagrees with the FVF
    g.first(R.EXTENSION).kids = [bad]
    with pytest.raises(ValueError, match="stride"):
        M.geometry_read(g)


# ------------------------------------------------------------------------------------------------------ TXD
def test_txd_rasters_decode_every_pc_format():
    y, x = np.mgrid[0:8, 0:8]
    rgba = np.stack([x * 32, y * 32, np.full_like(x, 96), np.where(x < 4, 255, 0)], -1).astype(np.uint8)
    rs = [S.pal8_raster("pal", 8, 8, rgba), S.rgba_raster("rgba", rgba), S.dxt1_raster("dxt1", 8, 8, (200, 40, 40), levels=4)]
    # 888 / 565 / 1555 / 4444 / LUM8 / DXT3 / DXT5 hand-packed
    px = np.ascontiguousarray(rgba[..., [2, 1, 0, 3]]).tobytes()
    rs.append(M.D3dRaster(M.D3D8, 0, "x888", "", 0x600, 0, 8, 8, 32, 1, 4, 0, None, [px]))
    r5, g6, b5 = rgba[..., 0].astype(np.uint32) >> 3, rgba[..., 1].astype(np.uint32) >> 2, rgba[..., 2].astype(np.uint32) >> 3
    rs.append(M.D3dRaster(M.D3D8, 0, "r565", "", 0x200, 0, 8, 8, 16, 1, 4, 0, None, [((r5 << 11) | (g6 << 5) | b5).astype("<u2").tobytes()]))
    a1 = (rgba[..., 3] > 127).astype(np.uint32)
    rs.append(M.D3dRaster(M.D3D8, 0, "r1555", "", 0x100, 1, 8, 8, 16, 1, 4, 0, None,
                          [((a1 << 15) | (r5 << 10) | ((rgba[..., 1].astype(np.uint32) >> 3) << 5) | b5).astype("<u2").tobytes()]))
    r4, g4, b4, a4 = (rgba >> 4).transpose(2, 0, 1).astype(np.uint32)
    rs.append(M.D3dRaster(M.D3D8, 0, "r4444", "", 0x300, 1, 8, 8, 16, 1, 4, 0, None, [((a4 << 12) | (r4 << 8) | (g4 << 4) | b4).astype("<u2").tobytes()]))
    rs.append(M.D3dRaster(M.D3D8, 0, "lum", "", 0x400, 0, 8, 8, 8, 1, 4, 0, None, [rgba[..., 0].tobytes()]))
    c0 = S.rgb565(200, 40, 40)
    dxt3 = (struct.pack("<Q", 0x0F0F0F0F0F0F0F0F) + struct.pack("<HHI", c0, c0, 0)) * 4     # alpha 0xF | 0x0 alternating
    rs.append(M.D3dRaster(M.D3D8, 0, "dxt3", "", 0x100, 1, 8, 8, 16, 1, 4, 3, None, [dxt3]))
    dxt5 = (bytes([255, 255]) + b"\0" * 6 + struct.pack("<HHI", c0, c0, 0)) * 4
    rs.append(M.D3dRaster(M.D3D8, 0, "dxt5", "", 0x100, 1, 8, 8, 16, 1, 4, 5, None, [dxt5]))
    txd = M.txd_build(rs)
    root, tail = R.parse(txd)
    assert root.to_bytes() + tail == txd
    back = {r.name: r for r in M.txd_rasters(txd)}
    assert set(back) == {r.name for r in rs}
    assert np.array_equal(M.raster_rgba(back["pal"]), rgba)
    assert np.array_equal(M.raster_rgba(back["rgba"]), rgba) and back["rgba"].has_alpha
    d = M.raster_rgba(back["dxt1"])
    assert d.shape == (8, 8, 4) and np.allclose(d[0, 0, :3], [206, 40, 41], atol=2) and d[..., 3].min() == 255
    assert M.raster_rgba(back["dxt1"], 3).shape == (1, 1, 4) and back["dxt1"].describe().startswith("dxt1: 8x8 1555 DXT1 4")
    x888 = M.raster_rgba(back["x888"])
    assert np.array_equal(x888[..., :3], rgba[..., :3]) and x888[..., 3].min() == 255
    assert np.abs(M.raster_rgba(back["r565"])[..., :3].astype(int) - rgba[..., :3]).max() <= 8
    r1555 = M.raster_rgba(back["r1555"])
    assert np.abs(r1555[..., :3].astype(int) - rgba[..., :3]).max() <= 8 and np.array_equal(r1555[..., 3], rgba[..., 3])
    assert np.abs(M.raster_rgba(back["r4444"]).astype(int) - rgba).max() <= 16
    assert np.array_equal(M.raster_rgba(back["lum"])[..., 0], rgba[..., 0])
    d3 = M.raster_rgba(back["dxt3"])
    assert d3[0, 0, 3] == 255 and d3[0, 1, 3] == 0 and np.allclose(d3[0, 0, :3], [206, 40, 41], atol=2)
    assert M.raster_rgba(back["dxt5"])[..., 3].min() == 255


def test_raster_8888_write_replaces_in_txd_with_mips():
    txd = S.ped_txd("player", 32)
    r = M.main_raster(txd, "player")
    assert r.name == "player" and r.fmt & M.PAL8 and M.main_raster(txd, "nope").name == "player"   # largest
    y, x = np.mgrid[0:64, 0:64]
    rgba = np.stack([x * 4, y * 4, np.full_like(x, 10), np.where(x > 50, 0, 255)], -1).astype(np.uint8)
    new = M.raster_8888(r, rgba, mips=True)
    assert new.width == 64 and new.depth == 32 and new.levels == 7 and new.fmt == 0x500 | M.MIPMAP and new.has_alpha
    assert new.name == "player" and new.filter == r.filter and new.palette is None
    out = M.txd_replace(txd, {"PLAYER": new})
    back = M.txd_rasters(out)
    assert [b.name for b in back] == ["player", "extra"]
    assert np.array_equal(M.raster_rgba(back[0]), rgba)
    assert M.raster_rgba(back[0], 6).shape == (1, 1, 4) and len(back[0].mips) == 7
    assert back[1].dxt == 1                                        # untouched raster verbatim
    with pytest.raises(ValueError, match="power-of-two"):
        M.raster_8888(r, np.zeros((30, 64, 4), np.uint8))
    nine = M.raster_8888(M.D3dRaster(M.D3D9, 0, "p", "", 0x500, 21, 8, 8, 32, 1, 4, 0, None, [b""]), rgba[:8, 48:56], mips=False)
    assert nine.platform == M.D3D9 and nine.alpha == 21 and nine.comp == 1 and nine.dxt == 0


# ----------------------------------------------------------------------------------------------- glTF / install
def test_clump_to_gltf_exports_four_weight_skin(tmp_path):
    dff, txd = S.ped_dff(), S.ped_txd()
    out = M.clump_to_gltf(dff, tmp_path / "p.glb", M.raster_rgba(M.main_raster(txd, "player")), "player")
    b = out.read_bytes()
    jl = struct.unpack_from("<I", b, 12)[0]
    gl = json.loads(b[20:20 + jl])
    assert len(gl["nodes"]) == 26 and gl["nodes"][6]["name"] == "Head" and gl["skins"][0]["joints"] == list(range(25))
    attrs = gl["meshes"][0]["primitives"][0]["attributes"]
    assert gl["accessors"][attrs["JOINTS_0"]]["type"] == "VEC4" and gl["accessors"][attrs["WEIGHTS_0"]]["type"] == "VEC4"
    assert gl["accessors"][attrs["POSITION"]]["count"] == 24 * 8 and gl.get("images")
    from gbox.characters import rig_from_gltf
    rig = rig_from_gltf(out, {"head": "Head", "hip": "Spine", "l_hand": "L Hand"})
    assert rig["roles"] == {"head": 6, "hip": 3, "l_hand": 10}
    assert np.allclose(rig["joints"][6], (0, 0.62, 0), atol=1e-6)         # GTA z up -> glTF y up


def test_exe_from_hyperspin_launcher(tmp_path):
    bat = tmp_path / "Grand Theft Auto Vice City.bat"
    bat.write_text('@echo off\r\nset "GAMENAME=gta-vc.exe"\r\nset "GAMEPATH=\\GTA Vice City\\\\"\r\nset HOME="%~dp0"\r\n'
                   'set "GAMEROOT=%~dp0%GAMEPATH%"\r\ncd %GAMEROOT%\r\nstart "" /WAIT "%GAMEROOT%%GAMENAME%"\r\nexit')
    assert M.exe_from_launcher(bat) == tmp_path / "GTA Vice City" / "gta-vc.exe"
    assert M.exe_from_launcher(tmp_path / "x.exe") == tmp_path / "x.exe" and M.exe_from_launcher(tmp_path / "x.chd") is None
    (tmp_path / "plain.bat").write_text("start game.exe")
    assert M.exe_from_launcher(tmp_path / "plain.bat") is None


def test_locate_install_tells_classic_from_definitive(tmp_path):
    inst = S.install(tmp_path / "classic")
    assert inst["kind"] == "classic" and inst["img"].endswith("gta3.img") and inst["ide"].endswith("default.ide")
    de = tmp_path / "de" / "Gameface" / "Content" / "Paks"
    de.mkdir(parents=True)
    (de / "gta.pak").write_bytes(b"\0" * 16)
    exe = tmp_path / "de" / "Gameface" / "Binaries" / "Win64" / "ViceCity.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    d = M.locate_install(exe)
    assert d["kind"] == "definitive" and d["pak"] == str(de / "gta.pak") and "Unreal" in d["engine"]
    assert M.locate_install(tmp_path / "nothing" / "x.exe")["kind"] == "unknown"


def test_extract_from_a_synthetic_install(tmp_path):
    inst = S.install(tmp_path / "vc")
    r = M.extract(inst, "cop", tmp_path / "cop.glb")
    assert r["glb"].exists() and r["roles"]["head"] == "Head" and r["stats"]["bones"] == 24
    assert r["raster"].startswith("cop: 64x64 PAL8") and r["source_files"] == ["models/gta3.img: cop.dff, cop.txd"]
    assert "gtavc_tommy" in {e["slug"] for e in M.roster()} and M.roster()[0]["key"] == "player"


# ------------------------------------------------------------------------------------------------ owned install
@pytest.mark.skipif(not OWNED_BAT.exists(), reason="HyperSpin share with the owned Vice City not reachable")
def test_owned_install_is_identified():
    inst = M.locate_install(OWNED_BAT)
    assert inst["exe"] and Path(inst["exe"]).name.lower() in ("vicecity.exe", "gta-vc.exe")
    assert inst["kind"] in ("classic", "definitive"), inst
    if inst["kind"] == "definitive":
        assert Path(inst["pak"]).is_file() and Path(inst["mods"]).is_dir()


@pytest.mark.skipif(not OWNED_BAT.exists() or M.locate_install(OWNED_BAT)["kind"] != "classic",
                    reason="no owned classic (RenderWare) Vice City install")
def test_owned_classic_player_extracts(tmp_path):
    inst = M.locate_install(OWNED_BAT)
    r = M.extract(inst, "player", tmp_path / "tommy.glb")
    assert r["glb"].exists() and set(M.REQUIRED_ROLES) <= set(r["roles"]) and r["stats"]["skinned_atomics"] >= 1
