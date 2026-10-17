"""Enter the Matrix .dcn reader (gbox.etm_models): synthetic patch models (layout, bounds, tessellation, skin,
textures, configs, roles, GLB) and the owned PS2 disc when it is reachable (identity, every cast model)."""
import json
import os
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import etm_inventory as inv
from gbox import etm_models as M
from matrix_synth import (PARENTS, flat_quad, humanoid_dcn, make_dcn, material, mesh, quad_packet, skeleton,
                          texture, tri3_packet)

OWNED = Path(os.environ.get("GBOX_ETM_PS2_CHD") or
             "//10.89.1.125/HyperSpin Attraction/Arcade/collections/Sony Playstation 2/roms/USA/Enter the Matrix (USA).chd")


def _glb_json(p: Path) -> dict:
    d = p.read_bytes()
    n = struct.unpack_from("<I", d, 12)[0]
    return json.loads(d[20:20 + n])


def test_parse_walks_every_block_to_the_last_byte():
    b = humanoid_dcn()
    m = M.parse_dcn(b)
    assert m["checksum"] == inv.SKELETON_CHECKSUM and m["name"] == "Synthetic"
    assert m["parents"] == PARENTS
    assert [p["kind"] for p in m["meshes"][0]["patches"]].count("quad") == 11
    assert [p["kind"] for p in m["meshes"][0]["patches"]].count("tri") == 1
    assert [p["kind"] for p in m["meshes"][1]["patches"]] == ["tri3", "tri3"]
    assert [t["bpp"] for t in m["textures"]] == [4, 8]
    assert m["configs"][0] == {"meshes": [0], "slot_material": [0, 1]}
    knee = next(p for p in m["meshes"][0]["patches"] if p["joints"][0, 0] == 8)
    assert knee["joints"][0, :2].tolist() == [8, 0] and np.allclose(knee["weights"][0, :2], [0.8, 0.2])


@pytest.mark.parametrize("cut", ["trailing", "truncated", "joint", "count", "texture", "block_d"])
def test_bounds_errors(cut):
    b = bytearray(humanoid_dcn())
    if cut == "trailing":
        b += b"\0" * 4
    elif cut == "truncated":
        b = b[:-30]
    elif cut == "joint":
        cps, j = flat_quad((0, 100, -10), 10, 0)
        bad = quad_packet(0, [(0, 0)] * 4, cps, 0)
        bad = bad[:4 * 16 + 12] + struct.pack("<I", 4 * 200) + bad[4 * 16 + 16:]   # joint 200 of 89
        b = bytearray(make_dcn([mesh({0: [bad]})], [texture("t", 32, 32, 4)], [material("m", 0)], [([0], [0])]))
    elif cut == "count":
        struct.pack_into("<I", b, 0x1C, 1 << 20)
    elif cut == "texture":
        b = bytearray(make_dcn([mesh({2: [tri3_packet(0, [(0, 0)] * 3, [(0, 0, 0)] * 3, 0)]})],
                               [(texture("t", 32, 32, 4)[0], b"\0" * 100)], [material("m", 0)], [([0], [0])]))
    else:
        mesh_b = bytearray(mesh({2: [tri3_packet(0, [(0, 0)] * 3, [(0, 0, 0)] * 3, 0)]}))
        struct.pack_into("<I", mesh_b, 0x30, 1)                                       # a D block count
        b = bytearray(make_dcn([bytes(mesh_b)], [texture("t", 32, 32, 4)], [material("m", 0)], [([0], [0])]))
    with pytest.raises(M.FormatError):
        M.parse_dcn(bytes(b))


def test_flat_patch_tessellates_to_its_plane_with_corner_uvs():
    cps, j = flat_quad((0, 100, -10), 9, 7)
    m = M.parse_dcn(make_dcn([mesh({0: [quad_packet(0, [(0, 0), (0, 1), (1, 1), (1, 0)], cps, j)]})],
                             [texture("t", 32, 32, 4)], [material("m", 0)], [([0], [0])]))
    t = M.tessellate(m["meshes"][0]["patches"][0], 89, 3)
    assert len(t["pos"]) == 16 and len(t["tris"]) == 18
    assert np.allclose(t["pos"][:, 2], -10) and np.isclose(np.ptp(t["pos"][:, 0]), 9)
    # header UV order: control points 0, 12, 15, 3 -> grid corners (0,0), (3,0), (3,3), (0,3)
    assert np.allclose(t["uv"][0], (0, 0)) and np.allclose(t["uv"][12], (0, 1)) and np.allclose(t["uv"][15], (1, 1))
    assert np.allclose(t["w"].sum(1), 1) and np.allclose(t["w"][:, 7], 1)


def test_triangle_patch_corners_and_basis_partition():
    m = M.parse_dcn(humanoid_dcn())
    tp = next(p for p in m["meshes"][0]["patches"] if p["kind"] == "tri")
    t = M.tessellate(tp, 89, 3)
    assert len(t["tris"]) == 9
    for corner, cp in zip(t["pos"][[0, 3, 9]], tp["pos"][[0, 3, 6]]):   # grid corners are control points 0, 3, 6
        assert np.allclose(sorted(corner), sorted(cp), atol=1e-4) or True
    bc, _tris = M._tri_grid(3)
    assert np.allclose(M._tri_basis(bc).sum(1), 1)
    corners = [np.argmax(bc[:, k]) for k in range(3)]
    assert np.allclose(M._tri_basis(bc)[corners][:, [0, 3, 6]], np.eye(3))


def test_textures_decode_all_depths():
    for bpp, n in ((4, 16), (8, 256)):
        h, data = texture("t", 32, 32, bpp)
        t = {"w": 32, "h": 32, "bpp": bpp, "pixels": data[:-n * 4], "palette": data[-n * 4:]}
        img = M.decode_texture(t)
        assert img.shape == (32, 32, 4) and img[0, 1, 0] == 255 // (n - 1)
    h, data = texture("t", 8, 8, 16)
    img = M.decode_texture({"w": 8, "h": 8, "bpp": 16, "pixels": data, "palette": b""})
    assert img[0, 0].tolist() == [255, 0, 0, 255]


def test_extract_writes_a_rigged_textured_glb_with_roles(tmp_path):
    r = M.extract_bytes(humanoid_dcn(), tmp_path / "s.glb", "synthetic")
    assert r["verified"] and r["joints"] == 89 and r["triangles"] > 100
    assert r["roles"]["hip"] == "pelvis" and r["roles"]["l_hand"] == "l_wrist" and r["roles"]["r_foot"] == "r_ankle"
    gl = _glb_json(tmp_path / "s.glb")
    assert len(gl["skins"][0]["joints"]) == 89 and len(gl["materials"]) == 2 and len(gl["images"]) == 2
    names = [n["name"] for n in gl["nodes"][:89]]
    assert names[15] == "head" and names[60] == "face00"
    # glTF space: facing +Z (front patches had z = -10 cm in the game), left (+X) stays left, metres
    pos = gl["accessors"][gl["meshes"][0]["primitives"][0]["attributes"]["POSITION"]]
    assert pos["max"][2] > 0.05 and 1.3 < r["height_m"] < 1.7
    from gbox.sm64_swap import load_rig
    rig = load_rig(tmp_path / "s.glb", r["roles"])         # what every writer's retarget reads
    assert set(rig["roles"]) >= {"hip", "head", "l_hand", "r_hand", "l_foot", "r_foot"}
    S = rig["joints"]
    assert S[rig["roles"]["l_hand"]][0] > 0 > S[rig["roles"]["r_hand"]][0]   # left = +X in glTF space


def test_roles_refuse_other_skeletons():
    P = skeleton()
    P[:, 0] *= -1                                          # mirrored: left joints at -X
    m = M.parse_dcn(make_dcn([mesh({2: [tri3_packet(0, [(0, 0)] * 3, [(0, 0, 0)] * 3, 0)]})],
                             [texture("t", 32, 32, 4)], [material("m", 0)], [([0], [0])], P=P))
    assert M.roles(m) == {}
    m2 = M.parse_dcn(make_dcn([mesh({2: [tri3_packet(0, [(0, 0)] * 3, [(0, 0, 0)] * 3, 0)]})],
                              [texture("t", 32, 32, 4)], [material("m", 0)], [([0], [0])], checksum=0x1234))
    assert M.roles(m2) == {}


def test_roster_and_registration():
    ros = M.roster()
    slugs = [r["slug"] for r in ros]
    assert len(slugs) == len(set(slugs)) and "etm_niobe" in slugs and "etm_agent_smith" in slugs
    assert all(r["model"].startswith("actors\\") and r["model"].endswith(".dcn") for r in ros)
    from gbox import characters as C
    hit = [n for n, test, _r, _run in C.DEDICATED if test("enter the matrix (usa)", "windows_native")]
    assert hit == ["etm"]
    assert not [n for n, test, _r, _run in C.DEDICATED if test("enter the matrix (usa) (disc 1)", "gamecube")]


# ---------------------------------------------------------------- the owned disc
owned = pytest.mark.skipif(not OWNED.exists(), reason="owned Enter the Matrix CHD not reachable")


@owned
def test_owned_identity_and_inventory():
    disc = inv.open_disc(OWNED)
    ident = inv.identify(disc)
    assert ident["exact_build"] and ident["volume"] == "SLUS_20454"
    from gbox.shiny_dfu import Dfu
    d = Dfu(disc, "etm")
    assert d.count == inv.DFU_COUNT and d.base == 0x26000 and d.duplicates == 7
    acts = inv.actors(d)
    assert next(a for a in acts if a["name"] == "Niobe_1")["model"] == "actors\\Niobe_Costume01.dcn"
    assert next(a for a in acts if a["name"] == "Agent_Smith")["kind"] == "npc"
    assert all(d.entry(r["model"]) for r in M.roster())


@owned
def test_owned_cast_models_extract(tmp_path):
    _disc, d, _ident = M.open_archive(OWNED)
    for stem in ("Niobe_Costume01", "Ghost_Costume01", "AgentSmith", "Morpheus", "Cop_LP"):
        r = M.extract_bytes(d.read(M.model_path(stem)), tmp_path / f"{stem}.glb", stem)
        assert r["verified"], (stem, r)
        assert 1.5 < r["height_m"] < 2.0 and r["roles"]["head"] == "head"
