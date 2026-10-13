import math
import os
import struct
from pathlib import Path

import pytest

from gbox import nightfire_model as nm

LEVEL = Path(os.environ.get("GBOX_NIGHTFIRE_LEVEL",
                            Path.home() / "gbox-cache/744ba3bc797403bf/unpacked/07000001.unpacked"))


def _skin(n=3, att=1):
    head = struct.pack("<I3f", 0x05000099, 1, 1, 1) + bytes([1, 0, 0, att, 0])
    par = bytes([0xFF] + [0x80 | (i - 1) for i in range(1, n)])
    body = head + par
    body += b"\0" * (((len(body) + 3) & ~3) - len(body))
    body += struct.pack("<7f", 0, 0, 0, 0, 0, 0, -1.0)
    for _ in range(1, n):
        body += struct.pack("<7f", 0, 0.5, 0, 0, 0, 0, 1.0)
    for k in range(att):
        body += struct.pack("<2I7f", 0x34 + k, n - 1, 0.1, 0, 0, 0, 0, 0, 1.0)
    return body + b"\0" * ((-len(body)) % 16)


def test_synthetic_skin():
    sk = nm.skin_skeleton(_skin())
    assert sk["bones"] == 3 and sk["parents"] == [-1, 0, 1] and len(sk["attachments"]) == 1
    assert sk["attachments"][0]["bone"] == 2


def test_synthetic_object_and_blocks():
    node = nm.NODE_TAG + b"\0\0\0\x0f" + b"polySurface1".ljust(20, b"\0") + struct.pack(">40I", 9, 30, 2, *([0] * 37))
    obj = b"\0\0\0\0\x14\0\0\x0e\x01\0\0\x75" + b"\0" * 20 + node
    nodes = nm.object_nodes(obj)
    assert nodes[0]["name"] == "polySurface1" and nodes[0]["n_verts"] == 2
    static = b"\xfa" * 32 + struct.pack(">6h", 1, 2, 3, 16384, 0, 0) * 2 + b"\xfa" * 32 + b"\1" * 36
    off = nm.vertex_block(static, 2)
    assert off == 32
    v = nm.vertices(static, off, 2)
    assert v[0][:3] == (1, 2, 3) and nm.normal_stats(v)["mean"] == 1.0


@pytest.fixture(scope="module")
def level():
    if not LEVEL.exists():
        pytest.skip("decompressed Nightfire level 07000001 not cached")
    from gbox.nightfire_inventory import pack_index
    data = LEVEL.read_bytes()
    return data, {e["name"].lower(): e for e in pack_index(data)["entries"]}, pack_index(data)["entries"]


def _payload(data, e):
    return data[e["offset"]:e["offset"] + e["size"]]


def test_owned_bondcombat_skeleton(level):
    data, by, _ = level
    sk = nm.skin_skeleton(_payload(data, by["05000007"]))
    assert sk["hash"] == "0x05000007" and sk["bones"] == 73 and sk["bind_offset"] == 0x64
    assert len(sk["attachments"]) == 60 == sk["head"][3]
    assert all(p < i for i, p in enumerate(sk["parents"]) if i)


def test_owned_bond_model_vertices(level):
    data, by, entries = level
    e = by["01000075"]
    assert e["type"] == 2
    nodes = nm.object_nodes(_payload(data, e))
    assert [n["name"] for n in nodes] == ["bond_generic_head_g"]
    n = nodes[0]
    assert (n["n_verts"], n["n_index"], n["groups"]) == (1278, 0xD40, 22)
    # vertex pointer -> next pointer spans exactly the 12-byte vertex array plus a 0x20 pad run
    assert n["pointers"][5] - n["pointers"][3] == 1278 * 12 + 0x20
    static = _payload(data, next(x for x in entries if x["type"] == 13))
    off = nm.vertex_block(static, n["n_verts"])
    assert off == 0x4ACC0
    st = nm.normal_stats(nm.vertices(static, off, n["n_verts"]))
    assert 0.98 < st["mean"] < 1.02


def test_synthetic_strips_runs_and_quats():
    groups = [{"strips": 2}]
    # strip 1: 2 triangles over 4 entries, strip 2: 1 triangle + a degenerate restart window
    tris, deg = nm.strip_triangles(groups, [2, 2], [0, 1, 2, 3, 4, 4, 5, 6])
    assert deg == 1
    assert tris == [(0, 0, 2, 1), (0, 1, 2, 3), (0, 5, 6, 7)]
    j, w = nm.run_weights([(3, 7, 1), (5, nm.NO_BONE, 1)], [8192, 8192, 16384, 0])
    assert j == [(3, 7), (5, 0)] and w == [(0.5, 0.5), (1.0, 0.0)]
    with pytest.raises(ValueError):
        nm.run_weights([(5, nm.NO_BONE, 1)], [8192, 8192])
    import numpy as np
    m = nm._quat_matrix([0, 0, math.sqrt(0.5), math.sqrt(0.5)])
    assert np.allclose(nm._quat_matrix(nm._matrix_quat(m)), m)
    ibm, world, local = nm.skeleton_matrices(nm.skin_skeleton(_skin()))
    # bind records are absolute inverse binds: bones 1 and 2 both sit at -t, so bone 2 is local zero
    assert np.allclose(world[2][:3, 3], [0, -0.5, 0]) and np.allclose(local[1][:3, 3], [0, -0.5, 0])
    assert np.allclose(local[2], np.eye(4)) and np.allclose(ibm[2] @ world[2], np.eye(4))


def test_owned_bond_mesh_faces(level):
    data, by, _ = level
    mesh = nm.object_mesh(data, "01000075")
    tab = mesh["tables"]
    assert mesh["vertex_block_offset"] == 0x4ACC0 and mesh["runtime_base"] == 4093296
    assert [(g["strips"], g["tri_slots"], g["material"]) for g in tab["groups"]][:2] == [(29, 865, 0), (2, 78, 1)]
    assert len(tab["strip_tris"]) == 127 and len(tab["pos_idx"]) == 3392
    assert len(mesh["faces"]) == 2449 and tab["degenerate"] == tab["degenerate_header"] == 689
    assert len(tab["uvs"]) == 1141 and max(tab["uv_idx"]) == 1140
    assert len(tab["runs"]) == 96 and sum(c for *_, c in tab["runs"]) == 1278
    assert sum(c for _, b, c in tab["runs"] if b != nm.NO_BONE) == 415


@pytest.mark.parametrize("obj,faces,deg,groups", [("01000075", 2449, 689, 7), ("01000145", 2408, 680, 5),
                                                  ("0100006f", 2081, 599, 8)])
def test_owned_roster_rigs(level, obj, faces, deg, groups):
    data, by, _ = level
    sk = nm.skin_skeleton(_payload(data, by["05000007"]))
    mesh = nm.object_mesh(data, obj)
    r = nm.rig_report(mesh, sk)
    assert (r["faces"], r["degenerate"], r["degenerate_header"], r["groups"]) == (faces, deg, deg, groups)
    assert r["max_bone"] < sk["bones"] == 73
    assert r["rigid_run_own_bone_top4"] >= 0.75 and r["rigid_run_median_dist_m"] < 0.1
    assert r["edge_max_m"] < 0.3 and r["winding_agrees_with_normals"] > 0.98
    if obj == "0100006f":  # grunt has two-texture groups (strip-count high nibble)
        assert any(g["flags"] and len(g["materials"]) == 2 for g in mesh["tables"]["groups"])


def test_owned_bond_glb(level, tmp_path):
    import json
    import numpy as np
    data, by, _ = level
    out = tmp_path / "bond.glb"
    nm.export_glb(data, str(out), "01000075", "05000007")
    d = out.read_bytes()
    jl = struct.unpack_from("<I", d, 12)[0]
    gltf = json.loads(d[20:20 + jl])
    b0 = 20 + jl + 8

    def acc(i):
        a = gltf["accessors"][i]
        v = gltf["bufferViews"][a["bufferView"]]
        dt = {5126: np.float32, 5121: np.uint8, 5123: np.uint16, 5125: np.uint32}[a["componentType"]]
        n = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[a["type"]]
        return np.frombuffer(d, dt, a["count"] * n, b0 + v["byteOffset"]).reshape(a["count"], n)

    prims = gltf["meshes"][0]["primitives"]
    at = prims[0]["attributes"]
    assert len(prims) == 7 and set(at) == {"POSITION", "NORMAL", "TEXCOORD_0", "JOINTS_0", "WEIGHTS_0"}
    assert sum(gltf["accessors"][p["indices"]]["count"] for p in prims) == 2449 * 3
    pos, jnt, wgt = acc(at["POSITION"]), acc(at["JOINTS_0"]), acc(at["WEIGHTS_0"])
    assert len(pos) == 1664 and np.allclose(wgt.sum(1), 1.0) and jnt.max() < 73
    skin = gltf["skins"][0]
    assert len(skin["joints"]) == 73
    # rest pose: world(joint) @ inverseBind(joint) must be identity for every joint
    ibm = acc(skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
    nodes = gltf["nodes"]
    parent = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}

    def world(i):
        m = np.eye(4)
        while i is not None and i < 73:
            n = nodes[i]
            loc = np.eye(4)
            loc[:3, :3] = nm._quat_matrix(n["rotation"])
            loc[:3, 3] = n["translation"]
            m = loc @ m
            i = parent.get(i)
        return m

    assert max(np.abs(world(j) @ ibm[j] - np.eye(4)).max() for j in range(73)) < 1e-5
    # every Bond material carries its embedded CMPR texture as a PNG
    assert [i["name"] for i in gltf["images"]] == [n for n, *_ in BOND_TEX]
    assert all("baseColorTexture" in m["pbrMetallicRoughness"] for m in gltf["materials"])
    v = gltf["bufferViews"][gltf["images"][0]["bufferView"]]
    assert d[b0 + v["byteOffset"]:b0 + v["byteOffset"] + 8] == b"\x89PNG\r\n\x1a\n"


def _tex_chunk(name, w, h, fmt, mips, dt_id=None, data=b""):
    gx = nm.ENGINE_GX[fmt]
    size = nm.mip_bytes(gx, w, h, mips)
    ref = b"DT" + struct.pack(">H", dt_id) if dt_id is not None else b"\0" * 4
    head = nm.TEX_MAGIC + struct.pack(">IHHI", size, w, h, 8) + struct.pack(">4I", 0, 1, 0, 0)
    head += struct.pack(">3I", fmt, mips, 0xFFFFFFFF) + bytes(0x48 - 0x2C)
    return b"\0\x0b\0\x17" + ref + name.encode().ljust(16, b"\0") + head + data


def test_synthetic_texture_chunks():
    assert nm.mip_bytes(14, 256, 256, 6) == 43680 and nm.mip_bytes(14, 64, 64, 4) == 2720
    assert nm.mip_bytes(5, 64, 32, 4) == 5440 and nm.mip_bytes(6, 64, 64, 5) == 21824
    cmpr = struct.pack(">HHI", 0xF800, 0x001F, 0) * 4          # 8x8 CMPR: 4 blocks, colour0 red
    obj = b"\0\0\0\0\x14\0\0\x0e" + struct.pack(">IIIII", 0x01000001, 1, 0, 2, 0x58000010)
    obj += struct.pack(">4HI", 0, 7, 7, 0x100, 0xFFFFFFFF) + struct.pack(">4HI", 0, 31, 31, 0x100, 0xFFFFFFFF)
    obj += _tex_chunk("skin", 8, 8, 1, 1, data=cmpr) + _tex_chunk("shared", 32, 32, 1, 3, dt_id=0xFD)
    texs = nm.object_textures(obj)
    assert [(t["name"], t["gx_format"], t["dt_id"]) for t in texs] == [("skin", 14, None), ("shared", 14, 0xFD)]
    assert texs[1]["data_offset"] is None and nm.texture_rgba(obj, texs[1]) is None
    rgba = nm.texture_rgba(obj, texs[0])
    assert rgba.shape == (8, 8, 4) and tuple(rgba[0, 0]) == (255, 0, 0, 255)
    with pytest.raises(ValueError):                              # table/chunk dimension mismatch
        nm.object_textures(obj.replace(struct.pack(">4HI", 0, 7, 7, 0x100, 0xFFFFFFFF),
                                       struct.pack(">4HI", 0, 15, 7, 0x100, 0xFFFFFFFF)))


BOND_HEAD_SHA = "a86c1a4651774dfb"  # bond_head CMPR mip chain, level 07000001
BOND_TEX = [("bond_head", 256, 256), ("bond_tongue", 32, 32), ("Bond_eyeball", 64, 32), ("male_hand", 128, 128),
            ("bond_bluesuit_c", 256, 256), ("bond_bluesuit_p", 128, 128), ("sleeve", 128, 64)]


def test_owned_roster_textures(level):
    import hashlib
    data, by, _ = level
    bond = _payload(data, by["01000075"])
    texs = nm.object_textures(bond)
    assert [(t["name"], t["width"], t["height"]) for t in texs] == BOND_TEX
    assert all(t["gx_format"] == 14 and t["dt_id"] is None and t["data_offset"] for t in texs)
    assert texs[0]["chunk"] == 0xAC and texs[0]["size"] == 43680 and texs[0]["mips"] == 6
    o = texs[0]["data_offset"]
    assert hashlib.sha256(bond[o:o + 43680]).hexdigest().startswith(BOND_HEAD_SHA)
    head = nm.texture_rgba(bond, texs[0])
    r, g, b = head[..., :3].reshape(-1, 3).mean(0)
    assert r > g > b and head[..., 3].min() == 255               # opaque skin-toned face map
    may = nm.object_textures(_payload(data, by["01000145"]))
    assert [t["name"] for t in may] == ["mayhew", "mayhew_eye", "mayhewtrousers", "Mayhewshirt", "male_hand"]
    grunt = nm.object_textures(_payload(data, by["0100006f"]))
    assert len(grunt) == 10 and [t["dt_id"] for t in grunt if t["dt_id"] is not None] == [0xFD, 0x101, 0x104]
    assert [t["gx_format"] for t in grunt[-3:]] == [5, 5, 5]
