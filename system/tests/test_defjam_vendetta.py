"""Def Jam: Vendetta (GDTE69) native mesh/texture reader: synthetic format tests plus the owned-disc check."""
import json
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import defjam_vendetta as D

ISO = Path.home() / "gbox-cache/modbase/8b37766f557e1f5f/Def Jam - Vendetta (USA).iso"


def _pad(b: bytearray, a=32):
    b.extend(bytes(-len(b) % a))


def make_gpl(pos, nrm, uvs, dl: bytes, vcd: int, frac=6, tex="t_m0.tpl", mesh="t_m0-body") -> bytes:
    """Same layout as the disc files: rel offsets from 0x1C, vertex header at 0x34, data at 0x40."""
    b = bytearray(0x40)
    struct.pack_into(">IIIII", b, 0, D.GPL_MAGIC, 0, 0, 1, 0x14)
    struct.pack_into(">IHBB", b, 0x34, 0x40 - D.BASE, len(pos), 0x3A, frac)
    for p, n in zip(pos, nrm):
        b += struct.pack(">6h", *[int(round(v * (1 << frac))) for v in p], *[int(round(v * 1024)) for v in n])
    _pad(b)
    uh = len(b)
    b += struct.pack(">IHHII", uh + 0x10 - D.BASE, len(uvs), 0x4002, 0, 0)
    for u in uvs:
        b += struct.pack(">ff", *u)
    dh = len(b)
    b += bytes(0x54)
    dl_off = len(b)
    b += dl
    _pad(b)
    struct.pack_into(">I", b, dh, 42)
    struct.pack_into(">IIII", b, dh + 0x38, 0x03000000, vcd, dl_off - D.BASE, len(b) - dl_off)
    b += tex.encode() + b"\0" + mesh.encode() + b"\0"
    struct.pack_into(">III", b, 0x1C, 0x34 - D.BASE, 0, uh - D.BASE)
    struct.pack_into(">I", b, 0x28, dh - D.BASE)
    return bytes(b)


QUAD = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)]
UP = [(0, 0, -1)] * 4                     # GX front faces are clockwise: this strip faces -Z when read CCW


def test_decode_dl_strip_triangles_and_index_widths():
    strip = bytes([0x98, 0, 4]) + bytes(sum(([i, i, i] for i in range(4)), []))
    tris, prims = D.decode_dl(strip + b"\0\0", 0x0828, 4, 4)
    assert prims == 1 and [[c[0] for c in t] for t in tris] == [[0, 1, 2], [2, 1, 3]]
    wide = bytes([0x90, 0, 3]) + struct.pack(">9H", 0, 0, 1, 1, 1, 2, 2, 2, 3)
    tris, _ = D.decode_dl(wide, 0x0C3C, 3, 4)
    assert tris == [((0, 0, 1), (1, 1, 2), (2, 2, 3))]
    mixed = bytes([0x90, 0, 3]) + b"".join(struct.pack(">HHB", i, i, i + 1) for i in range(3))   # pos/nrm 16, tex 8
    tris, _ = D.decode_dl(mixed, 0x083C, 3, 4)
    assert tris == [((0, 0, 1), (1, 1, 2), (2, 2, 3))]
    with pytest.raises(D.FormatError, match="index"):
        D.decode_dl(bytes([0x90, 0, 3, 0, 0, 0, 1, 1, 1, 9, 9, 9]), 0x0828, 4, 4)
    with pytest.raises(D.FormatError, match="opcode"):
        D.decode_dl(bytes([0x61, 0, 0, 0, 0]), 0x0828, 4, 4)


def test_parse_gpl_synthetic_matches_disc_layout():
    strip = bytes([0x98, 0, 4]) + bytes(sum(([i, i, i] for i in range(4)), []))
    m = D.parse_gpl(make_gpl(QUAD, UP, [(0, 0), (1, 0), (0, 1), (1, 1)], strip, 0x0828))
    assert m["vertex_count"] == 4 and m["uv_count"] == 4 and m["bones"] == 42 and len(m["triangles"]) == 2
    assert np.allclose(m["positions"], QUAD) and np.allclose(m["normals"], UP)
    assert m["texture"] == "t_m0.tpl" and m["mesh_name"] == "t_m0-body"
    assert D.winding(m) == 0.0                 # clockwise (GX) -> the exporter flips it
    with pytest.raises(D.FormatError):
        D.parse_gpl(b"\0" * 64)


def test_tpl_palette_and_cmpr_decode():
    b = bytearray(struct.pack(">III", D.TPL_MAGIC, 2, 12))
    b += struct.pack(">IIII", 0x40, 0x2C, 0x60, 0)
    b += bytes(0x2C - len(b)) + struct.pack(">HBBII", 2, 0, 0, 1, 0x38)        # palette: 2 x RGB565
    b += bytes(0x38 - len(b)) + struct.pack(">HH", 0xF800, 0x07E0)
    b += bytes(0x40 - len(b)) + struct.pack(">HHII", 4, 8, 9, 0x80)          # 8x4 C8
    b += bytes(0x60 - len(b)) + struct.pack(">HHII", 8, 8, 14, 0xA0)         # 8x8 CMPR
    b += bytes(0x80 - len(b)) + bytes([0, 1] * 16)
    b += bytes(0xA0 - len(b)) + struct.pack(">HHI", 0x001F, 0xF800, 0) * 4
    imgs = D.parse_tpl(bytes(b))
    c8 = D.decode_image(bytes(b), imgs[0])
    assert c8.shape == (4, 8, 4) and tuple(c8[0, 0]) == (255, 0, 0, 255) and tuple(c8[0, 1]) == (0, 255, 0, 255)
    cm = D.decode_image(bytes(b), imgs[1])
    assert cm.shape == (8, 8, 4) and (cm[..., 2] == 255).all() and (cm[..., 0] == 0).all()


def test_write_glb_roundtrip(tmp_path):
    strip = bytes([0x98, 0, 4]) + bytes(sum(([i, i, i] for i in range(4)), []))
    m = D.parse_gpl(make_gpl(QUAD, UP, [(0, 0), (1, 0), (0, 1), (1, 1)], strip, 0x0828))
    img = np.full((4, 4, 4), 200, np.uint8)
    out = D.write_glb(tmp_path / "t.glb", [{"name": "t_body", "mesh": m, "flip": True, "image": img}], "t")
    raw = out.read_bytes()
    magic, ver, total = struct.unpack_from("<III", raw, 0)
    jl = struct.unpack_from("<I", raw, 12)[0]
    gl = json.loads(raw[20:20 + jl])
    assert magic == 0x46546C67 and ver == 2 and total == len(raw)
    prim = gl["meshes"][0]["primitives"][0]
    assert gl["accessors"][prim["indices"]]["count"] == 6 and "TEXCOORD_0" in prim["attributes"]
    assert gl["images"][0]["mimeType"] == "image/png" and gl["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"]


def test_normal_scale_accepts_1024_and_2048_fixed_point():
    assert D.normal_scale_ok(1023.3) and D.normal_scale_ok(2047.7) and D.normal_scale_ok(954.1)
    assert not D.normal_scale_ok(805.3) and not D.normal_scale_ok(0) and not D.normal_scale_ok(1.0)


def test_registered_reader_and_roster():
    from gbox import characters as C
    r = next(r for r in C.DEDICATED if r[0] == "defjam_vendetta")
    assert r[1]("def jam - vendetta (usa)", "gamecube") and not r[1]("def jam - fight for ny (usa)", "gamecube")
    ros = r[2]()
    assert len(ros) == 58 and len({e["slug"] for e in ros}) == 58


@pytest.mark.skipif(not ISO.is_file(), reason="owned Def Jam Vendetta ISO is not unpacked on this node")
def test_owned_disc_s000a(tmp_path):
    from gbox.gcdisc import GCDisc
    ident = D.identify(ISO)
    assert ident["game_id"] == "GDTE69" and ident["revision"] == 0 and ident["exact_build"]
    disc = GCDisc(ISO)
    inv = D.inventory(disc)
    assert [f["dir"] for f in inv["fighter_dirs"]] == D.FIGHTER_DIRS
    assert len(inv["crowd"]) == 23 and len(inv["stages"]) == 16
    r = D.extract_model(disc, "data/s000a", "s000a", tmp_path / "s000a.glb")
    assert r["verified"] and len(r["parts"]) == 5
    body = r["parts"][0]
    assert body["mesh_name"] == "s000a_m0-body" and body["triangles"] == 1277 and body["winding"] > 0.99
    assert body["texture_file"] == "data/s000a/s000a_m0.tpl" and Path(r["glb"]).stat().st_size > 100000
    assert r["skinned"] and r["joints"] == 73 and len(r["roles"]) == 18 and r["bind_error"] < 1e-3
    assert r["skeleton"] == {"pelvis_y": 10.56, "head_end_y": 20.711, "hands_x": [8.569, -8.563]}


# --- skeleton (.act) and weights (.skn): synthetic files in the disc layout ------------------------------------------
def make_act(nodes, names) -> bytes:
    """nodes: [(parent, translation, quaternion xyzw)] -> .act bytes (records at 0x40, transforms, ACTU)."""
    n = len(nodes)
    recs, xf0 = 0x40, 0x40 + 0x1C * n
    actu = xf0 + 0x34 * n
    b = bytearray(actu)
    struct.pack_into(">II", b, 0, D.ACT_MAGIC, n)
    struct.pack_into(">I", b, 0x0C, recs)
    struct.pack_into(">II", b, 0x1C, actu, xf0)
    for i, (parent, t, q) in enumerate(nodes):
        struct.pack_into(">5IHHI", b, recs + 0x1C * i, xf0 + 0x34 * i, 0, 0,
                         recs + 0x1C * parent if parent >= 0 else 0, 0, 0xFFFF, i, 0x01000000)
        struct.pack_into(">I10f", b, xf0 + 0x34 * i, 0x0D000000, 1, 1, 1, *q, *t)
    names_at = 20 + 4 * n
    blob = bytearray()
    offs = []
    for s in names:
        offs.append(names_at + len(blob))
        blob += s.encode() + b"\0"
    b += b"ACTU" + struct.pack(">IIII", 0, 0, n, 0) + struct.pack(f">{n}I", *offs) + blob
    return bytes(b)


def make_skn(raw, frac, singles=(), pairs=(), lists=()) -> bytes:
    """raw: (nv, 6) int16 .gpl vertex block. singles [(bone, start, count)], pairs [(a, b, start, count, [(wa, wb)])],
    lists [(bone, [vertex], [weight])]. Pair groups use the disc's 32-byte aligned dst + skip encoding."""
    t1 = 0x18
    t2 = t1 + 0x40 * len(singles)
    t3 = t2 + 0x74 * len(pairs)
    b = bytearray(t3 + 0x44 * len(lists))
    struct.pack_into(">HHHBBIII", b, 0, len(singles), len(pairs), len(lists), frac, 0, t1, t2, t3)

    def blob(data: bytes) -> int:
        _pad(b)
        o = len(b)
        b.extend(data)
        return o
    for i, (bone, st, n) in enumerate(singles):
        src = blob(np.asarray(raw[st:st + n], ">i2").tobytes())
        struct.pack_into(">IIHHB", b, t1 + 0x40 * i + 0x30, src, 12 * st, bone, n, 0)
    for i, (a, c, st, n, w) in enumerate(pairs):
        dst = 12 * st
        skip = dst % 32
        src = blob(bytes(skip) + np.asarray(raw[st:st + n], ">i2").tobytes())
        wp = blob(bytes(np.asarray(w, np.uint8).reshape(-1)))
        struct.pack_into(">IIIHHHB", b, t2 + 0x74 * i + 0x60, src, wp, dst - skip, a, c, n, skip)
    for i, (bone, verts, w) in enumerate(lists):
        src = blob(np.asarray(raw[list(verts)], ">i2").tobytes())
        vp = blob(struct.pack(f">{len(verts)}H", *verts))
        wp = blob(bytes(w))
        struct.pack_into(">IIIIHH", b, t3 + 0x44 * i + 0x30, src, vp, 0, wp, bone, len(verts))
    return bytes(b)


BODY_NAMES = ["body", "root", "tophip", "hip", "waist", "chest", "neck", "head"] + [f"n{k}" for k in range(8, 42)]
QZ90 = (0.0, 0.0, float(np.sqrt(0.5)), float(np.sqrt(0.5)))       # 90 degrees about +Z


def body_act() -> bytes:
    """42 nodes: a spine 0..8 rising 2.5 units per node above y 10 (tophip turned 90 degrees about Z like the disc,
    so its children step along local +X), the rest hanging off the chest."""
    nodes = [(-1, (0, 0, 0), (0, 0, 0, 1)), (0, (0, 10.0, 0), (0, 0, 0, 1)), (1, (0, 0, 0), QZ90)]
    nodes += [(k - 1, (2.5, 0, 0), (0, 0, 0, 1)) for k in range(3, 9)]
    nodes += [(5, (0.25 * k, 0, 0), (0, 0, 0, 1)) for k in range(9, 42)]
    return make_act(nodes, BODY_NAMES)


def face_act(head_world_t) -> bytes:
    nodes = [(-1, (0, 0, 0), (0, 0, 0, 1)), (0, tuple(float(v) for v in head_world_t), QZ90)]   # = BODY head
    nodes += [(1, (0.1 * k, 0.5, 0.2), (0, 0, 0, 1)) for k in range(2, 11)]
    return make_act(nodes, ["face", "head_bone", "squint", "R_lip", "L_lip", "sneer", "miken_brow", "mabuta_blink",
                            "jaw", "L_eyeball", "R_eyeball"])


TRI_STRIP = bytes([0x98, 0, 4]) + bytes(sum(([i, i, i] for i in range(4)), []))


def test_parse_act_tree_names_and_t_pose():
    a = D.parse_act(body_act())
    assert a["count"] == 42 and a["names"][:8] == BODY_NAMES[:8] and a["parent"][:4] == [-1, 0, 1, 2]
    assert np.allclose(a["world"][8][:3, 3], (0, 25.0, 0), atol=1e-5)        # 10 + 6 x 2.5 up the turned spine
    assert np.allclose(a["world"][5][:3, :3], D._quat_matrix(*QZ90), atol=1e-6)
    with pytest.raises(D.FormatError, match="magic"):
        D.parse_act(b"\0" * 64)
    bad = bytearray(body_act())
    struct.pack_into(">I", bad, 0x40 + 0x0C, 0x12345)                        # node 0's parent -> not a record
    with pytest.raises(D.FormatError, match="parent"):
        D.parse_act(bytes(bad))


def _quad_mesh(frac=10):
    pts = [(0, 20, 0), (1, 20, 0), (0, 21, 0), (1, 21, 0)]
    m = D.parse_gpl(make_gpl(pts, UP, [(0, 0), (1, 0), (0, 1), (1, 1)], TRI_STRIP, 0x0828, frac=frac))
    return pts, m


def test_skn_pair_weights_first_byte_is_first_bone_and_lists_accumulate():
    _, m = _quad_mesh()
    skn = D.parse_skn(make_skn(m["raw"], 10, singles=[(7, 0, 1)], pairs=[(6, 7, 1, 2, [(192, 64), (64, 192)])],
                               lists=[(5, [3], [77]), (6, [3], [179])]))
    assert skn["fraction_bits"] == 10 and [g["kind"] for g in skn["groups"]] == ["single", "pair"]
    assert skn["groups"][1]["start"] == 1                                    # dst + skip lands on vertex 1
    J, W, rep = D.skin_weights(skn, m, 8)
    assert J.shape == W.shape == (4, 4) and np.allclose(W.sum(1), 1)
    assert (J[0, 0], W[0, 0]) == (7, 1.0)
    assert (J[1, 0], J[1, 1]) == (6, 7) and np.allclose(W[1, :2], (0.75, 0.25))   # first byte -> bone a
    assert (J[2, 0], J[2, 1]) == (7, 6) and np.allclose(W[2, :2], (0.75, 0.25))
    assert sorted(J[3, :2].tolist()) == [5, 6] and np.allclose(sorted(W[3, :2]), (77 / 256, 179 / 256))
    assert rep["max_influences"] == 2 and rep["over_four"] == 0


def test_skn_refuses_mismatched_copies_and_unweighted_vertices():
    _, m = _quad_mesh()
    other = m["raw"].copy()
    other[1, 0] += 1
    with pytest.raises(D.FormatError, match="differs from the .gpl"):
        D.skin_weights(D.parse_skn(make_skn(other, 10, singles=[(7, 0, 4)])), m, 8)
    with pytest.raises(D.FormatError, match="no skin weight"):
        D.skin_weights(D.parse_skn(make_skn(m["raw"], 10, singles=[(7, 0, 3)])), m, 8)
    with pytest.raises(D.FormatError, match="sum to 256"):
        D.skin_weights(D.parse_skn(make_skn(m["raw"], 10, singles=[(7, 0, 3)], lists=[(6, [3], [100])])), m, 8)
    with pytest.raises(D.FormatError, match="bone 9 of a 8-node"):
        D.skin_weights(D.parse_skn(make_skn(m["raw"], 10, singles=[(9, 0, 4)])), m, 8)


class FakeDisc:
    def __init__(self, files: dict):
        self.files = files

    def read(self, n):
        return self.files[n]


def synthetic_fighter(key="s000a") -> FakeDisc:
    body_pts = [(-1, 0, 0), (1, 0, 0), (-1, 22, 0), (1, 22, 0)]
    body = make_gpl(body_pts, UP, [(0, 0), (1, 0), (0, 1), (1, 1)], TRI_STRIP, 0x0828, frac=10,
                    tex=f"{key}_m0.tpl", mesh=f"{key}_m0-body")
    bm = D.parse_gpl(body)
    head_t = D.parse_act(body_act())["world"][7][:3, 3]
    face_pts = [(-0.5, 20, 0), (0.5, 20, 0), (-0.5, 21, 0), (0.5, 21, 0)]
    face = make_gpl(face_pts, UP, [(0, 0), (1, 0), (0, 1), (1, 1)], TRI_STRIP, 0x0828, frac=10, mesh=f"{key}_m1-face")
    fm = D.parse_gpl(face)
    d = f"data/{key}/{key}"
    return FakeDisc({
        f"{d}_m0.gpl": body, f"{d}_m0.act": body_act(),
        f"{d}_m0.skn": make_skn(bm["raw"], 10, singles=[(1, 0, 2)], pairs=[(5, 6, 2, 2, [(128, 128), (200, 56)])]),
        f"{d}_m1.gpl": face, f"{d}_m1.act": face_act(head_t),
        f"{d}_m1.skn": make_skn(fm["raw"], 10, singles=[(1, 0, 2)], pairs=[(1, 8, 2, 2, [(64, 192), (64, 192)])])})


def _glb(path):
    raw = Path(path).read_bytes()
    jl = struct.unpack_from("<I", raw, 12)[0]
    gl = json.loads(raw[20:20 + jl])
    bin_ = raw[28 + jl:]

    def acc(i):
        a = gl["accessors"][i]
        v = gl["bufferViews"][a["bufferView"]]
        dt = {5126: np.float32, 5123: np.uint16, 5125: np.uint32}[a["componentType"]]
        k = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[a["type"]]
        return np.frombuffer(bin_, dt, a["count"] * k, v["byteOffset"]).reshape(a["count"], k)
    return gl, acc


def test_extract_model_writes_one_skinned_mesh_with_body_roles(tmp_path):
    r = D.extract_model(synthetic_fighter(), "data/s000a", "s000a", tmp_path / "s000a.glb")
    assert r["skinned"] and r["joints"] == 42 + 9 and r["bind_error"] < 1e-4 and r["verified"]
    assert len(r["roles"]) == 18 and r["roles"]["hip"] == "body_02" and r["roles"]["l_foot"] == "body_29"
    assert r["parts"][1]["skin"] == {"attach_offset": 0.0, "max_influences": 2, "over_four": 0, "groups": 2, "lists": 0}
    gl, acc = _glb(r["glb"])
    names = [n["name"] for n in gl["nodes"]]
    assert names[:42] == [f"body_{k:02d}" for k in range(42)] and names[42:51] == [f"face_{k:02d}" for k in range(2, 11)]
    assert 42 in gl["nodes"][7]["children"]                                   # face nodes hang off the head
    assert len(gl["meshes"]) == 1 and len(gl["meshes"][0]["primitives"]) == 2 and gl["nodes"][-1]["skin"] == 0
    skin = gl["skins"][0]
    assert skin["joints"] == list(range(51)) and acc(skin["inverseBindMatrices"]).shape == (51, 16)
    prim = gl["meshes"][0]["primitives"][0]["attributes"]
    assert gl["accessors"][prim["JOINTS_0"]]["type"] == "VEC4" and gl["accessors"][prim["WEIGHTS_0"]]["type"] == "VEC4"
    assert np.allclose(acc(prim["WEIGHTS_0"]).sum(1), 1)
    P = acc(prim["POSITION"])
    assert np.isclose(P[:, 1].max(), 22 * D.GLTF_SCALE, atol=1e-4)            # metres at the PS2 scale
    assert np.isclose(gl["nodes"][1]["translation"][1], 10 * D.GLTF_SCALE)
    ibm = acc(skin["inverseBindMatrices"])[8].reshape(4, 4, order="F")        # head end: world (0, 25) units
    assert np.allclose(np.linalg.inv(ibm)[:3, 3], (0, 25 * D.GLTF_SCALE, 0), atol=1e-5)


def test_posed_skin_moves_only_weighted_vertices():
    disc = synthetic_fighter()
    parts = {}
    for k in (0, 1):
        stem = f"data/s000a/s000a_m{k}"
        parts[k] = {"mesh": D.parse_gpl(disc.read(stem + ".gpl")), "act": D.parse_act(disc.read(stem + ".act")),
                    "skn": D.parse_skn(disc.read(stem + ".skn"))}
    s = D.assemble_skin(parts)
    assert D.bind_error(s) < 1e-4
    J = s["joints"]
    J[6]["q"] = np.array([np.sqrt(0.5), 0, 0, np.sqrt(0.5)])               # neck +90 degrees about local X
    world = []
    for j in J:
        L = D._trs_matrix(j["t"], j["q"], j["s"])
        world.append(L if j["parent"] < 0 else world[j["parent"]] @ L)
    M = np.array([w @ np.linalg.inv(j["world"]) for w, j in zip(world, J)])
    p = s["parts"][0]
    X = np.einsum("nkij,nj->nki", M[p["joints"].astype(int)], np.c_[p["positions"], np.ones(4)])
    S = (X[..., :3] * p["weights"][..., None]).sum(1)
    assert np.allclose(S[:2], p["positions"][:2], atol=1e-5)                 # root-weighted feet stay put
    assert not np.allclose(S[2:], p["positions"][2:], atol=1e-2)            # neck-weighted top moves


def test_run_result_reports_reader_v2_and_registry(tmp_path):
    from gbox import characters as C
    r = D.extract_model(synthetic_fighter(), "data/s000a", "s000a", tmp_path / "x.glb")
    res = D.run_result(r, "s000a")
    assert res["extra"] == {"djv_gc_reader": 2} and len(res["roles"]) == 18
    assert "data/s000a/s000a_m0.act" in res["source_files"] and "data/s000a/s000a_m1.skn" in res["source_files"]
    assert C.READER_VERSIONS["defjam_vendetta"] == ("gbox.defjam_vendetta", "djv_gc_reader")
    old = {"source": {"game_title": "Def Jam - Vendetta (USA)", "platform": "gamecube"}}
    assert C.reader_status(old) == {"extractor": "defjam_vendetta", "entry": 1, "current": 2, "stale": True}
    assert not C.reader_status({**old, "djv_gc_reader": 2})["stale"]
    static = D.extract_model(synthetic_fighter(), "data/s000a", "s000a", tmp_path / "y.glb", rig=False)
    with pytest.raises(D.FormatError, match="no skeleton"):
        D.run_result(static, "s000a")
