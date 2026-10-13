"""gbox.doapp_chars: DOA++ rigged GLB reader. Synthetic primitives / skeleton / GLB with roles, plus the owned-ROM
extraction (GBOX_DOAPP_ROMS = directory with doapp.zip + coh1002m.zip; skipped without it)."""

import json
import os
import struct

import numpy as np
import pytest

from gbox import characters as C
from gbox import doapp_chars as R
from gbox import doapp_inventory as D
from gbox import doapp_models as M

OWNED = os.environ.get("GBOX_DOAPP_ROMS", "")
needs_roms = pytest.mark.skipif(not (OWNED and os.path.isfile(os.path.join(OWNED, "doapp.zip"))),
                                reason="set GBOX_DOAPP_ROMS to the directory with doapp.zip + coh1002m.zip")


def _gt4_record(verts, uv=((0, 0), (31, 0), (0, 31), (31, 31)), clut=(0, 480), tpage=(640, 0), normals=None):
    rec = bytearray(0x98)
    for copy in (0, 0x34):
        rec[copy + 7] = 0x3C
        for k, (u, v) in enumerate(uv):
            rec[copy + (0x0C, 0x18, 0x24, 0x30)[k]] = u
            rec[copy + (0x0C, 0x18, 0x24, 0x30)[k] + 1] = v
        struct.pack_into("<H", rec, copy + 0x0E, (clut[0] // 16) | (clut[1] << 6))
        struct.pack_into("<H", rec, copy + 0x1A, (tpage[0] // 64) | ((tpage[1] // 256) << 4))
    for k, v in enumerate(verts):
        ptr = M.SCRATCH_VERTEX + 8 * v if v < 126 else M.SPILL_VERTEX + 8 * (v - 126)
        struct.pack_into("<I", rec, 0x68 + 4 * k, ptr)
    for k, n in enumerate(normals or [(0, 0, -4096)] * 4):
        struct.pack_into("<3h", rec, 0x78 + 8 * k, *n)
    return bytes(rec)


def test_primitive_records_decode():
    sec = struct.pack("<HH", 2, 0x801B) + _gt4_record([0, 1, 2, 3]) + _gt4_record([126, 127, 2, 130])
    p = M.primitives(sec, 0)
    assert len(p) == 2 and p[0]["packet"] == "GT4" and p[0]["code"] == 0x3C
    assert p[0]["verts"] == [0, 1, 2, 3] and p[1]["verts"] == [126, 127, 2, 130]
    assert p[0]["uv"][3] == (31, 31) and p[0]["clut"] == (0, 480) and p[0]["tpage"]["x"] == 640
    assert p[0]["tpage"]["bpp"] == 4 and p[0]["normals"][0] == (0, 0, -4096) and not p[0]["double_sided"]
    assert M.chunk_end(sec, 0) == len(sec)
    assert M.corner_triangles(4) == [(0, 2, 1), (1, 2, 3)] and M.corner_triangles(3) == [(0, 2, 1)]
    assert M.texture_rect(p[0]) == (640, 0, 647, 31)
    with pytest.raises(M.FormatError):
        M.primitives(sec[:-4], 0)
    with pytest.raises(M.FormatError):
        M.vertex_index(0x1F800004)
    with pytest.raises(M.FormatError):
        M.primitives(struct.pack("<HH", 1, 0x7777) + b"\0" * 0x98, 0)


def test_texture_page_uses_the_clut_and_ps1_transparency():
    v = np.zeros((512, 1024), np.uint16)
    v[480, 0:16] = [0] + [0x7C00 | k for k in range(1, 16)]         # palette: entry 0 = 0x0000 (transparent)
    v[0, 640] = 0x2110                                              # texels 0,1,2,3 = indices 0,1,1,2
    page = M.texture_page(v, M.tpage_fields(10), (0, 480))
    assert page.shape == (256, 256, 4)
    assert page[0, 0, 3] == 0 and page[0, 1, 3] == 255 and page[0, 3, 2] == 255 and page[0, 1, 0] == 8


def _pose(n=26):
    pose = []
    for b in range(n):
        if b >= 16:
            pose.append(((0,) * 9, (0, 0, 0)))
            continue
        y = {2: -900, 0: -1100, 1: -1350}.get(b, -500)
        pose.append(((4096, 0, 0, 0, 4096, 0, 0, 0, 4096), (10 * b, y, 0)))
    return pose


def test_skeleton_parents_roles_and_chains():
    pose = _pose()
    joints = R.skeleton(pose, set(range(16)), [(1, 1)])
    names = [j["name"] for j in joints]
    assert names[0] == "pelvis" and len(joints) == 16
    by = {j["name"]: j for j in joints}
    assert joints[by["head"]["parent"]]["name"] == "torso" and joints[by["l_foot"]["parent"]]["name"] == "l_shin"
    assert joints[by["acc_00"]["parent"]]["name"] == "head"                    # chain link -> its anchor bone
    assert all(j["parent"] < i for i, j in enumerate(joints))
    roles = {j["role"] for j in joints if j["role"]}
    assert roles == {"hip", "chest", "head", "l_upper", "l_fore", "l_hand", "r_upper", "r_fore", "r_hand",
                     "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot"}
    with pytest.raises(R.ReaderError):
        R.skeleton(pose, {17}, [])                                         # used bone the game never set


def test_gltf_frame_faces_plus_z_and_keeps_handedness():
    G = R.game_matrix(((4096, 0, 0, 0, 4096, 0, 0, 0, 4096), (100, -1000, -50)))
    W = R.to_gltf(G)
    assert np.allclose(W[:3, 3], [0.1, 1.0, 0.05]) and np.isclose(np.linalg.det(W[:3, :3]), 1)


def _read_glb(path):
    b = open(path, "rb").read()
    n = struct.unpack_from("<I", b, 12)[0]
    gl = json.loads(b[20:20 + n])
    return gl, b[20 + n + 8:]


def test_glb_with_roles_skin_and_clip(tmp_path):
    pose = _pose()
    joints = R.skeleton(pose, set(range(15)), [])
    tri_pos = np.array([[0, -1000, 0], [50, -1000, 0], [0, -1100, 0]], float)
    tex = {"key": (10, (0, 480), False), "rgba": np.full((4, 4, 4), 200, np.uint8), "origin": (0, 0), "size": (4, 4),
           "mask": False, "double_sided": False}
    tris = [{"bones": [0, 0, 1], "pos": tri_pos, "nrm": None, "uv": [(0, 0), (3, 0), (0, 3)], "mat": tex["key"],
             "seam": False, "slot": 0}]
    a = {"joints": joints, "tris": tris, "textures": [tex], "pose": pose,
         "roles": {j["role"]: j["name"] for j in joints if j["role"]}}
    moved = [list(pose), [(m, (t[0], t[1] - 10, t[2])) if b == 2 else (m, t) for b, (m, t) in enumerate(pose)]]
    out = R.write_glb(tmp_path / "f.glb", a, "f", {"stance": moved})
    gl, bin_ = _read_glb(out)
    assert len(gl["skins"][0]["joints"]) == 15 and gl["nodes"][0]["name"] == "pelvis"
    assert gl["animations"][0]["name"] == "stance" and len(gl["animations"][0]["channels"]) == 30
    acc = gl["accessors"][gl["meshes"][0]["primitives"][0]["attributes"]["POSITION"]]
    view = gl["bufferViews"][acc["bufferView"]]
    P = np.frombuffer(bin_, np.float32, 9, view["byteOffset"]).reshape(3, 3)
    assert np.allclose(P[1], [0.05, 1.0, 0.0])                       # game (50, -1000, 0) -> metres, y up
    ib = gl["accessors"][gl["skins"][0]["inverseBindMatrices"]]
    ibm = np.frombuffer(bin_, np.float32, 16 * 15, gl["bufferViews"][ib["bufferView"]]["byteOffset"]).reshape(15, 4, 4)
    assert np.allclose(ibm[0].T[:3, 3], [-0.02, -0.9, 0], atol=1e-6)  # pelvis (bone 2) bind at (0.02, 0.9, 0) m
    assert set(a["roles"]) >= {"hip", "head", "l_hand", "r_foot"}


def test_roster_and_registration():
    ros = R.roster()
    assert len(ros) == 44 and len({e["slug"] for e in ros}) == 44
    assert {e["fighter"] for e in ros} == {f["id"] for f in D.FIGHTERS}
    hit = [r for r in C.DEDICATED if r[1]("dead or alive ++ (japan)", "arcade")]
    assert [r[0] for r in hit] == ["doapp"]
    assert not any(r[0] == "doapp" for r in C.DEDICATED if r[1]("dead or alive 2", "dreamcast"))


@needs_roms
def test_owned_extract_is_verified(tmp_path):
    banked, ram, _ = D.decode_owned(OWNED)
    r = R.extract(ram, banked, D.fighter("tina"), 0, tmp_path / "tina.glb", clips={"stance": 0})
    assert r["verified"], r
    assert r["joints"] == 15 and r["untextured_prims"] == 0 and r["seam_triangles"] > 50
    assert len(r["roles"]) == 15 and 1450 < r["height"] < 1650
    gl, _ = _read_glb(r["glb"])
    assert gl["animations"][0]["name"] == "stance" and len(gl["images"]) == r["textures"]
    k = R.extract(ram, banked, D.fighter("kasumi"), 0, tmp_path / "kasumi.glb", clips={})
    assert k["verified"] and k["joints"] > 15                    # the ponytail chain joints
