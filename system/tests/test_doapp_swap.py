"""gbox.doapp_swap: the Dead Or Alive ++ character writer (#1340). Synthetic: the packed-stream codec and the
expander port (every chunk kind, the packet template, player 2), the container, the texture page, quad pairing, the
quadric decimation, a full fit of a rigged humanoid onto a synthetic 15-bone fighter (local bone frames, seams, batch
tables, budgets) and the ROM set rebuild. Owned ROMs (GBOX_DOAPP_ROMS = directory with doapp.zip + coh1002m.zip;
skipped without it): the packer against the game's own 0x8006c718 on all 44 costume models, and built models read back
through the game's fight init / skeleton build."""

import hashlib
import json
import os
import struct
import zipfile
from pathlib import Path

import numpy as np
import pytest

from gbox import doapp_inventory as D
from gbox import doapp_models as M
from gbox import doapp_swap as W

OWNED = os.environ.get("GBOX_DOAPP_ROMS", "")
needs_roms = pytest.mark.skipif(not (OWNED and os.path.isfile(os.path.join(OWNED, "doapp.zip"))),
                                reason="set GBOX_DOAPP_ROMS to the directory with doapp.zip + coh1002m.zip")


# ------------------------------------------------------------------------------------------------ stream codec
def test_stream_values_short_and_long():
    for v in (0, 2, 0x3EE, 0xFFFE, 0x10000, 0x802A6800, 0xFFFFFFFE):
        out = bytearray()
        W.put_var(out, v)
        assert len(out) == (2 if v < 0x10000 else 4)
        assert W.get_var(bytes(out), 0) == (v, len(out))
    with pytest.raises(W.WriterError):
        W.put_var(bytearray(), 3)


def test_vertex_pointer_values():
    for i in (0, 1, 125, 126, 127, 394):
        ptr = M.SCRATCH_VERTEX + 8 * i if i < 126 else M.SPILL_VERTEX + 8 * (i - 126)
        assert W.ptr_from_value(8 * i) == ptr and W.value_from_ptr(ptr) == 8 * i
        assert M.vertex_index(ptr) == i
    assert W.ptr_from_value(0x900000) == 0x900000 and W.value_from_ptr(0x900000) == 0x900000
    with pytest.raises(W.WriterError):                     # a small raw address would read back as a buffer slot
        W.value_from_ptr(0x1000)


def _rec(kind, i=0):
    """One logical record of a kind with distinct field values."""
    pk, _size, nptr, nnrm, extra = W.KINDS[kind]
    nuv = len(W.PACKETS[pk]["uv"])
    r = {"h0": (0x3C if pk == "GT4" else 0x34 if pk == "GT3" else 0x2C) << 8 | (i % 3 if pk.startswith("G") else 0),
         "clut": W.CLUT + i, "tpage": W.TPAGE, "uv": [(17 * k + i) | (9 * k + 1) << 8 for k in range(nuv)],
         "ptrs": [8 * ((i + k * 70) % 300) for k in range(nptr)],
         "normals": [(100 * k + i, -200 * k, 4000 - k) for k in range(nnrm)], "npad": (i & 1) if pk.startswith("G") and nnrm else 0}
    if extra == "colours":
        r["colours"] = [0x40 + 4 * k for k in range(6)]
    elif extra == "inline":
        r["inline"] = [(k, -k, 3 * k + i) for k in range(nuv)]
    return r


def _all_kinds_mesh():
    kinds = [0x801B, 0x801A, 0x803A, 0x803B, 0x8019, 0x8018, 0x0029, 0x805A, 0x0001, 0x0000]
    chunks = [(k, [_rec(k, i) for i in range(2 + n % 2)]) for n, k in enumerate(kinds)]
    return W._layout([[0, 1], [2, 3, 4], [5, 6, 7], [8, 9], []], chunks, [(i, -i, 2 * i) for i in range(300)])


def test_pack_expand_roundtrip_every_kind():
    mesh = _all_kinds_mesh()
    src = W.pack_mesh(mesh)
    dest = 0x801E8000 + 0x394
    exp, end = W.expand_mesh(src + b"\xAA\xBB", 0, dest)
    assert end == len(src) and len(exp) == W.mesh_bytes(mesh)
    back = W.mesh_from_expanded(exp, dest)
    assert W.same_mesh(back, mesh) and W.pack_mesh(back) == src     # the packer is the expander's inverse
    # the reader parses the expansion: groups, chunk kinds, primitives, vertices
    m = M.parse_mesh(exp)
    assert m["header_size"] == mesh["hdr"] and len(m["vertices"]) == 300 and m["vertices"][7] == (7, -7, 14)
    assert [[c["kind"] for c in g] for g in m["chunks"]][:2] == [[0x801B, 0x801A], [0x803A, 0x803B, 0x8019]]
    p = M.primitives(exp, mesh["groups"][0][0])
    assert p[1]["verts"] == [1, 71, 141, 211] and p[1]["code"] == 0x3C and p[1]["tpage"]["raw"] == W.TPAGE
    seam = M.primitives(exp, mesh["groups"][2][2])[0]
    ro = seam["offset"]
    assert [struct.unpack_from("<I", exp, ro + 0x5C + 4 * k)[0] - dest - mesh["hdr"] for k in range(6)] == \
        [0x40 + 4 * k for k in range(6)]


def test_player_two_and_the_packet_template():
    mesh = W._layout([[0, 1, 2]], [(0x801A, [_rec(0x801A, 1)]), (0x8019, [_rec(0x8019, 2)]),
                                   (0x0001, [_rec(0x0001, 3)])], [(1, 2, 3)] * 4)
    src = W.pack_mesh(mesh)
    p1, _ = W.expand_mesh(src, 0, 0x801FE800)
    p2, _ = W.expand_mesh(src, 0, 0x8028E800, player=1)
    a, b = M.parse_mesh(p1), M.parse_mesh(p2)
    gt, ft, k1 = (M.primitives(p1, o)[0] for o in mesh["groups"][0])
    gt2, ft2, k12 = (M.primitives(p2, o)[0] for o in mesh["groups"][0])
    assert a["groups"] == b["groups"]
    assert gt2["clut"][1] == gt["clut"][1] + 8 and gt2["tpage"]["y"] == 256 and ft2["clut"][1] == ft["clut"][1] + 8
    assert k12["clut"] == k1["clut"] and k12["tpage"]["y"] == 256          # kind 1 keeps its CLUT for player 2
    # the expander builds packets in one scratchpad template: the FT4 after the GT3 carries the GT3's colour bytes
    o = ft["offset"]
    assert p1[o + 0x10:o + 0x13] == b"\x80\x80\x80" and p1[o + 0x13] == 1
    # both packet copies are identical
    assert p1[o:o + 0x28] == p1[o + 0x28:o + 0x50]


def test_template_carries_between_sections():
    a = W._layout([[0]], [(0x801B, [_rec(0x801B, 4)])], [(0, 0, 0)] * 3)
    b = W._layout([[0]], [(0x8019, [_rec(0x8019, 5)])], [(0, 0, 0)] * 3)
    tm = W._new_template()
    W.expand_mesh(W.pack_mesh(a), 0, 0x801FE900, template=tm)
    e1, _ = W.expand_mesh(W.pack_mesh(b), 0, 0x801FF000, template=tm)
    e0, _ = W.expand_mesh(W.pack_mesh(b), 0, 0x801FF000)
    assert e1 != e0                       # FT4 bytes the routine never writes keep the previous section's GT4 values
    assert W.same_mesh(W.mesh_from_expanded(e1, 0x801FF000), W.mesh_from_expanded(e0, 0x801FF000))


# ------------------------------------------------------------------------------------------------ container
def test_container_layout_and_walk():
    mesh = _all_kinds_mesh()
    tim = W.tim8(W.TEX_X, W.TEX_Y, np.arange(16 * 8, dtype=np.uint8).reshape(8, 16), [0x8000 | k for k in range(256)],
                 W.CLUT_X, W.CLUT_Y)
    raw = bytes(range(18))
    data = W.build_container({0: (len(raw), raw), 1: (182, bytes(182)), 3: (W.mesh_bytes(mesh), W.pack_mesh(mesh)),
                              11: (6, b"abcdef")}, tim)
    recs = W.walk_container(data)
    assert [r["index"] for r in recs if r["dest"]] == [0, 1, 3, 11]
    assert recs[0]["dest"] == W.FIRST_DEST and all(r["dest"] % 4 == 0 for r in recs if r["dest"])
    assert recs[3]["packed"] and data[recs[0]["start"]:recs[0]["end"]] == raw
    t = M.tim_offset(data)
    extent, tb = struct.unpack_from("<II", data, t - 8)
    assert tb == len(tim) and extent == recs[11]["dest"] + 6 and len(data) == t + len(tim)
    secs = W.expand_all(data)
    assert secs[11] == b"abcdef" and W.same_mesh(W.mesh_from_expanded(secs[3], M.WORK_BASE + recs[3]["dest"]), mesh)
    tims = M.tims(data)
    assert len(tims) == 1 and tims[0]["bpp"] == 8 and tims[0]["image"] == {"x": W.TEX_X, "y": 0, "w": 8, "h": 8}
    assert tims[0]["clut"] == {"x": W.CLUT_X, "y": W.CLUT_Y, "w": 256, "h": 1}
    v, mask = M.vram(data)
    assert v[0, W.TEX_X] == 0x0100 and v[W.CLUT_Y, 5] == 0x8005
    page = W.tim8(W.TEX_X, 0, np.zeros((64, 256), np.uint8), [0] * 256, W.CLUT_X, W.CLUT_Y)
    assert W.tim_bytes(64) == len(page) and W.TPAGE == 0x8B


def test_texture_page():
    tex = np.zeros((32, 64, 4), np.uint8)
    tex[..., 0] = np.arange(64)[None, :] * 4
    tex[..., 3] = 255
    tex[:4, :4, 3] = 0                                    # a cut-out corner
    prims = [{"tex": tex, "color": (255, 255, 255, 255), "tris": np.zeros((1, 3), int), "wrap": (10497, 10497)},
             {"tex": None, "color": (10, 200, 30, 255), "tris": np.zeros((1, 3), int)}]
    pg = W.Page(64)
    pg.build(prims)
    idx, clut = pg.indexed()
    assert idx.shape == (64, 256) and len(clut) == 256 and clut[0] == 0x0000      # index 0 = see-through
    assert all(c for c in clut[1:])                       # no other entry is see-through
    k = W.Page.key(prims[0])
    uv = pg.uv(k, np.array([[[0.0, 0.0], [1.0, 1.0], [0.5, 0.5]], [[1.2, 0.2], [1.8, 0.4], [1.5, 0.9]]]))
    _t, x, y, w, h, _wr = pg.mat[k]
    assert tuple(uv[0, 0]) == (x, y) and tuple(uv[0, 1]) == (x + w - 1, y + h - 1)
    assert x <= uv[1, :, 0].min() and uv[1, :, 0].max() < x + w             # a repeated tile is folded into the page
    assert idx[y + h // 2, x] != 0 and idx[y + 1, x + 1] == 0                # cut-out texels are index 0
    fu = pg.uv(W.Page.key(prims[1]), np.zeros((1, 3, 2)))
    fx, fy = fu[0, 0]
    assert pg.rgba[fy, fx, 1] == 200


def test_pair_quads_draws_the_same_triangles():
    tris = [{"v": [0, 1, 2], "uv": [(0, 0), (8, 0), (0, 8)], "n": [(0, 0, 4096)] * 3},
            {"v": [2, 1, 3], "uv": [(0, 8), (8, 0), (8, 8)], "n": [(0, 0, 4096)] * 3},
            {"v": [4, 5, 6], "uv": [(0, 0), (1, 0), (0, 1)], "n": [(0, 0, 4096)] * 3}]
    quads, rest = W.pair_quads(tris)
    assert len(quads) == 1 and rest == [tris[2]]
    q = quads[0]

    def cyc(t):
        i = t.index(min(t))
        return tuple(t[i:] + t[:i])
    drawn = {cyc([q["v"][a] for a in (0, 1, 2)]), cyc([q["v"][a] for a in (1, 3, 2)])}
    assert drawn == {cyc(tris[0]["v"]), cyc(tris[1]["v"])}
    tris[1]["uv"][0] = (1, 9)                              # texels differ on the shared edge: no quad
    assert W.pair_quads(tris)[0] == []


# ------------------------------------------------------------------------------------------------ synthetic fighter
ROLES = ["hip", "chest", "head", "l_upper", "l_fore", "l_hand", "r_upper", "r_fore", "r_hand", "l_thigh", "l_shin",
         "l_foot", "r_thigh", "r_shin", "r_foot"]
JOINT = {"hip": (0, 0.95, 0), "chest": (0, 1.25, 0), "head": (0, 1.55, 0), "l_upper": (0.2, 1.45, 0),
         "l_fore": (0.45, 1.45, 0), "l_hand": (0.7, 1.45, 0), "l_thigh": (0.1, 0.9, 0), "l_shin": (0.1, 0.5, 0),
         "l_foot": (0.1, 0.08, 0)}
for _k in list(JOINT):
    if _k.startswith("l_"):
        x, y, z = JOINT[_k]
        JOINT["r_" + _k[2:]] = (-x, y, z)
PARENT = {"hip": None, "chest": "hip", "head": "chest", "l_upper": "chest", "l_fore": "l_upper", "l_hand": "l_fore",
          "r_upper": "chest", "r_fore": "r_upper", "r_hand": "r_fore", "l_thigh": "hip", "l_shin": "l_thigh",
          "l_foot": "l_shin", "r_thigh": "hip", "r_shin": "r_thigh", "r_foot": "r_shin"}
TIP = {"head": (0, 1.8, 0), "l_hand": (0.82, 1.45, 0), "r_hand": (-0.82, 1.45, 0), "l_foot": (0.1, 0.0, 0.15),
       "r_foot": (-0.1, 0.0, 0.15)}
CHILD = {"hip": "chest", "chest": "head", "l_upper": "l_fore", "l_fore": "l_hand", "r_upper": "r_fore",
         "r_fore": "r_hand", "l_thigh": "l_shin", "l_shin": "l_foot", "r_thigh": "r_shin", "r_shin": "r_foot"}


def humanoid(path: Path, rings: int = 3, sides: int = 6) -> dict:
    """A rigged tube figure: each bone a tube from its joint to the next; the first ring of a tube belongs to the
    parent bone, so the triangles joining them span two bones (seams). Textured with a 16 x 16 gradient."""
    from gbox.melee_models import write_gltf
    names = ROLES
    ji = {r: i for i, r in enumerate(names)}
    P, N, UV, J, T = [], [], [], [], []
    for r in names:
        a = np.array(JOINT[r], float)
        b = np.array(JOINT[CHILD[r]] if r in CHILD else TIP[r], float)
        axis = b - a
        L = np.linalg.norm(axis)
        d = axis / L
        u = np.cross(d, [0, 0, 1.0]) if abs(d[2]) < 0.9 else np.cross(d, [1.0, 0, 0])
        u /= np.linalg.norm(u)
        w = np.cross(d, u)
        rad = 0.09 if r in ("chest", "hip") else 0.05
        base = len(P)
        for k in range(rings + 1):
            owner = PARENT[r] if (k == 0 and PARENT[r]) else r
            for s in range(sides):
                t = 2 * np.pi * s / sides
                nrm = np.cos(t) * u + np.sin(t) * w
                P.append(a + axis * k / rings + rad * nrm)
                N.append(nrm)
                UV.append((s / sides, k / rings))
                J.append(ji[owner])
        for k in range(rings):
            for s in range(sides):
                i0, i1 = base + k * sides + s, base + k * sides + (s + 1) % sides
                j0, j1 = i0 + sides, i1 + sides
                T += [(i0, i1, j1), (i0, j1, j0)]
    tex = np.zeros((16, 16, 4), np.uint8)
    tex[..., 0] = np.arange(16)[None, :] * 16
    tex[..., 1] = np.arange(16)[:, None] * 16
    tex[..., 3] = 255
    Jv = np.zeros((len(P), 4), np.int64)
    Jv[:, 0] = J
    Wv = np.zeros((len(P), 4))
    Wv[:, 0] = 1
    joints = []
    for r in names:
        m = np.eye(4)
        m[:3, 3] = JOINT[r]
        joints.append({"parent": ji[PARENT[r]] if PARENT[r] else -1, "world": m})
    prim = {"pos": np.array(P), "nrm": np.array(N), "uv": np.array(UV), "tris": np.array(T), "J": Jv, "W": Wv,
            "tex": tex, "color": (255, 255, 255, 255), "wrap": (10497, 10497)}
    write_gltf(Path(path), joints, [prim], 1.0, "tube", names)
    return {r: r for r in names}


def _rot(axis: str, deg: float) -> np.ndarray:
    c, s = np.cos(np.radians(deg)), np.sin(np.radians(deg))
    return {"x": np.array([[1, 0, 0], [0, c, -s], [0, s, c]]), "z": np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])}[axis]


def synthetic_original(slot7_groups: int = 2) -> bytes:
    """A costume model with the game's layout: sections 0 / 11 / 12 (kept by the writer), batch tables, eight mesh
    slots, a TIM."""
    def mesh(groups, kind=0x801A):
        chunks = [(kind, [_rec(kind, g)]) for g in range(groups)]
        return W._layout([[g] for g in range(groups)], chunks, [(10, 20, 30)] * 300)
    secs = {0: (16, bytes(range(16))), 1: (208 if slot7_groups else 182, bytes(208 if slot7_groups else 182)),
            2: (208 if slot7_groups else 182, bytes(208 if slot7_groups else 182)), 11: (12, b"raw section!")}
    for slot, n in ((0, 8), (1, 3), (2, 3), (3, 3), (4, 3), (5, 1), (6, 1)) + (((7, slot7_groups),) if slot7_groups else ()):
        m = mesh(n)
        secs[3 + slot] = (W.mesh_bytes(m), W.pack_mesh(m))
    fx = W._layout([[0], [1]], [(0x0001, [_rec(0x0001, 0)]), (0x0001, [_rec(0x0001, 1)])], [])
    secs[12] = (W.mesh_bytes(fx), W.pack_mesh(fx))
    tim = W.tim8(W.TEX_X, 0, np.zeros((16, 16), np.uint8), [0x8000] * 256, W.CLUT_X, W.CLUT_Y)
    return W.build_container(secs, tim)


def synthetic_target(model: bytes, file_index: int = 49) -> dict:
    """15 game bones at the humanoid's joints (game units, y down), some rotated so local frames matter."""
    G = [np.eye(4) for _ in range(15)]
    for role, b in W.ROLE_BONE.items():
        G[b][:3, 3] = np.array(JOINT[role]) * 1000 * W.FLIP
    G[W.ROLE_BONE["l_shin"]][:3, :3] = _rot("x", 90)
    G[W.ROLE_BONE["r_fore"]][:3, :3] = _rot("z", -60)
    G[W.ROLE_BONE["head"]][:3, :3] = _rot("x", 30) @ _rot("z", 10)
    T = np.array([G[b][:3, 3] * W.FLIP for b in range(15)])
    f = {"name": "TEST", "id": 1, "models": [file_index]}
    return {"G": G, "T": T, "ground": 0.0, "height": 1800.0, "head_h": 250.0,
            "parent": [W.BONE_PARENT[b] for b in range(15)], "joints": 15, "model": model, "fighter": f,
            "costume": 0, "file": file_index}


@pytest.fixture(scope="module")
def fitted(tmp_path_factory):
    from gbox.sm64_swap import load_rig, retarget
    d = tmp_path_factory.mktemp("donor")
    roles = humanoid(d / "tube.gltf")
    tgt = synthetic_target(synthetic_original())
    prims, rep = retarget(load_rig(d / "tube.gltf", roles), tgt, None, jmap=W.ROLE_BONE)
    feet = W.fit_feet(prims, tgt)
    r = W.fit(prims, tgt)
    return {"tgt": tgt, "prims": prims, "fit": r, "retarget": rep, "feet": feet, "dir": d, "roles": roles}


def test_fit_layout_matches_the_game(fitted):
    r, tgt = fitted["fit"], fitted["tgt"]
    data, rep = r["data"], r["report"]
    assert len(data) <= W.budget(49) and rep["extent"] <= W.EXPANDED_LIMIT
    chk = W.check_model(data, r["geometry"])
    assert chk["port_matches_layout"] and chk["sections"] == [0, 1, 2, 3, 5, 7, 10, 11, 12]
    secs = W.expand_all(data)
    orig = W.expand_all(tgt["model"])
    assert secs[0] == orig[0] and secs[11] == orig[11]                                 # kept sections
    src = {r["index"]: data[r["start"]:r["end"]] for r in W.walk_container(data)}
    osrc = {r["index"]: tgt["model"][r["start"]:r["end"]] for r in W.walk_container(tgt["model"])}
    assert src[12] == osrc[12] and W.same_mesh(W.mesh_from_expanded(secs[12], 0), W.mesh_from_expanded(orig[12], 0))
    body = M.parse_mesh(secs[3])
    seam_group = body["chunks"][-1]
    assert len(body["groups"]) == 14 and seam_group and seam_group[0]["kind"] == M.SEAM_KIND
    bs = M.batches(secs[1], secs[2], 0, len(body["vertices"]), len(body["groups"]))
    assert [b["bone"] for b in bs] == [b for b in W.BODY_BONES if rep["bone_vertices"][b]]
    assert sum(b["count"] for b in bs) == len(body["vertices"]) <= W.SLOT_VERTEX_CAP[0]
    for slot, bone in ((2, 5), (4, 11)):                   # hands: three shapes, one mesh
        h = M.parse_mesh(secs[3 + slot])
        hb = M.batches(secs[1], secs[2], slot, len(h["vertices"]), 3)
        assert len(h["groups"]) == 3 and h["groups"][0] == h["groups"][1] == h["groups"][2]
        assert [b["bone"] for b in hb] == [bone] * 3 and {b["first"] for b in hb} == {0}
    acc = M.parse_mesh(secs[10])
    assert len(acc["groups"]) == 2 and not any(acc["groups"])                # accessory chains: drawn empty
    tims = M.tims(data)
    assert len(tims) == 1 and tims[0]["image"]["x"] == W.TEX_X and tims[0]["clut"]["y"] == W.CLUT_Y


def test_fit_vertices_live_in_their_bone_frames(fitted):
    """Every drawn corner, put back through its bone's bind matrix, lands on the retargeted model (< 1.5 units)."""
    r, tgt = fitted["fit"], fitted["tgt"]
    secs = W.expand_all(r["data"])
    body = M.parse_mesh(secs[3])
    bone_of = {}
    for b in M.batches(secs[1], secs[2], 0, len(body["vertices"]), len(body["groups"])):
        for v in range(b["first"], b["first"] + b["count"]):
            bone_of[v] = b["bone"]
    want = np.concatenate([np.asarray(p["pos"], float)[np.asarray(p["tris"]).reshape(-1)] for p in fitted["prims"]]) * W.FLIP
    worst, kinds = 0.0, set()
    for g in body["groups"]:
        for co in g:
            for pr in M.primitives(secs[3], co):
                kinds.add(pr["kind"])
                for v in pr["verts"]:
                    G = tgt["G"][bone_of[v]]
                    p = G[:3, :3] @ np.array(body["vertices"][v], float) + G[:3, 3]
                    worst = max(worst, float(np.min(np.linalg.norm(want - p, axis=1))))
    assert worst < 1.5 and {0x801A, M.SEAM_KIND} <= kinds
    # lighting normals: outward (against the drawn order's right-hand normal, like the game's own data)
    agree = 0
    for g in body["groups"][:13]:
        for co in g:
            for pr in M.primitives(secs[3], co):
                pts = [tgt["G"][bone_of[v]][:3, :3] @ np.array(body["vertices"][v], float) for v in pr["verts"][:3]]
                n = tgt["G"][bone_of[pr["verts"][0]]][:3, :3] @ np.array(pr["normals"][0], float)
                agree += float(np.cross(pts[1] - pts[0], pts[2] - pts[0]) @ n) < 0
    assert agree > 0.9 * sum(len(M.primitives(secs[3], co)) for g in body["groups"][:13] for co in g)


def test_fit_seams_borrow_lit_corner_colours(fitted):
    r = fitted["fit"]
    data = r["data"]
    rec3 = next(x for x in W.walk_container(data) if x["index"] == 3)
    sec = W.expand_all(data)[3]
    body = M.parse_mesh(sec)
    hdr = body["header_size"]
    seams = [p for co in body["groups"][-1] for p in M.primitives(sec, co)]
    assert seams and all(p["kind"] == M.SEAM_KIND for p in seams)
    lit = {p["offset"]: p for g in body["groups"][:13] for co in g for p in M.primitives(sec, co)}
    lit_verts = {v for q in lit.values() for v in q["verts"]}
    secs = W.expand_all(data)
    bone_of = {}
    for b in M.batches(secs[1], secs[2], 0, len(body["vertices"]), len(body["groups"])):
        bone_of.update({v: b["bone"] for v in range(b["first"], b["first"] + b["count"])})
    same = 0
    for p in seams:
        ptrs = struct.unpack_from("<6I", sec, p["offset"] + 0x5C)
        for k, ptr in enumerate(ptrs):
            off = ptr - M.WORK_BASE - rec3["dest"]
            src = max(o for o in lit if o <= off)
            q = lit[src]
            lay = W.PACKETS[q["packet"]]
            buf, field = divmod(off - src, lay["copy"])
            assert buf == k // 3 and field in lay["rgb"]
            v, sv = p["verts"][k % 3], q["verts"][lay["rgb"].index(field)]
            if v in lit_verts:
                assert sv == v                             # the same vertex's lit colour
                same += 1
            else:
                assert bone_of[sv] == bone_of[v]           # nobody lights it: a lit corner of the same bone
            assert struct.unpack_from("<H", sec, src + M.CHUNK_LAYOUTS[q["kind"]]["normals"][1] + 6)[0] == 1
    assert same > 0
    assert hdr == 16 + sum(4 + 4 * len(g) for g in body["groups"])


def test_budget_and_decimation(fitted, monkeypatch):
    prims, tgt = fitted["prims"], fitted["tgt"]
    full = fitted["fit"]["report"]
    monkeypatch.setattr(W, "budget", lambda i: full["bytes"] - 0x4000)
    small = W.fit(prims, tgt)["report"]
    assert small["bytes"] <= full["bytes"] - 0x4000 and small["texture"][1] < full["texture"][1]
    monkeypatch.setattr(W, "budget", lambda i: 0x3000)
    with pytest.raises(W.WriterError, match="doesn't fit"):
        W.fit(prims, tgt)
    monkeypatch.setattr(W, "SLOT_VERTEX_CAP", {0: 60, 2: 10, 4: 10, 7: 66})
    monkeypatch.setattr(W, "budget", lambda i: 0x1BAB4)
    capped = W.fit(prims, tgt)["report"]
    assert capped["vertices"][0] <= 60 and capped["vertices"][2] <= 10 and capped["triangles"] < full["triangles"]


def test_decimate_keeps_bones_seams_and_orientation():
    sides, rings = 24, 40
    P, B, T = [], [], []
    for k in range(rings + 1):
        for s in range(sides):
            t = 2 * np.pi * s / sides
            P.append((100 * np.cos(t), -10.0 * k, 100 * np.sin(t)))
            B.append(0 if k <= rings // 2 else 6)
    for k in range(rings):
        for s in range(sides):
            i0, i1 = k * sides + s, k * sides + (s + 1) % sides
            T += [(i0, i0 + sides, i1 + sides), (i0, i1 + sides, i1)]
    P, B, T = np.array(P), np.array(B), np.array(T)
    tri = {"bones": B[T], "pos": P[T], "nrm": np.zeros(P[T].shape), "uv": np.zeros(T.shape + (2,)),
           "mat": np.zeros(len(T), int), "keys": [None]}

    def outward(t):
        a, b, c = t["pos"][:, 0], t["pos"][:, 1], t["pos"][:, 2]
        n = np.cross(b - a, c - a)
        radial = (a + b + c) / 3 * np.array([1, 0, 1])
        return (np.einsum("ij,ij->i", n, radial) > 0).mean()
    before = outward(tri)
    dec = W.decimate(tri, {0: 120, 2: 10, 4: 10})
    assert dec["slot_vertices"][0] <= 120 and len(dec["bones"]) < len(T) / 3
    assert set(np.unique(dec["bones"])) == {0, 6}
    assert ((dec["bones"] != dec["bones"][:, :1]).any(1)).sum() > 0           # the seam ring between the bones stays
    assert before in (0.0, 1.0) and outward(dec) == before          # no face turned over


# ------------------------------------------------------------------------------------------------ slots + ROM set
def test_slots():
    assert [(f["name"], c) for f, c in W.parse_slot("kasumi:2")] == [("KASUMI", 1)]
    assert [(f["name"], c) for f, c in W.parse_slot("fighter:Lei Fang")] == [("LEI FANG", c) for c in range(4)]
    assert len(W.parse_slot("player")) == 44 and W.is_slot("jann lee:4") and not W.is_slot("kasumi:5")
    assert not W.is_slot("mario") and W.mod_name({"slug": "cloud"}, "Kasumi:2") == "doapp_cloud_kasumi2"
    slots = {s["slot"] for s in W.cast_slots()}
    assert {"player", "kasumi", "lei_fang"} <= slots and all(W.is_slot(s) for s in slots)


def test_registered_writer():
    from gbox import char_coverage as CC
    import inspect
    from gbox import characters as C
    row = next(r for r in CC.WRITERS if r[0] == "doapp_swap")
    assert "<fighter>[:<costume>]" in row[1] and "player" in row[1]
    game = {"game_id": D.GAME_ID_JP, "title": "Dead Or Alive ++ (Japan)", "platform": "arcade"}
    w = CC.writer_for(game)
    assert w and w["writer"] == "gbox.doapp_swap" and w["routed"]
    assert {"player", "kasumi"} <= {s["slot"] for s in CC.cast_slots(game)}
    assert "Dead Or Alive ++" in inspect.getsource(C.CharIn)


def _fake_set(d: Path) -> dict:
    d.mkdir(parents=True, exist_ok=True)
    members = {"doapp119.bin": bytes(range(256)) * 16, "doapp120.bin": bytes(reversed(range(256))) * 16}
    for i, name in enumerate(D.DATA_BANKS):
        members[name] = bytes([0x11 * (i + 1)]) * 0x400000
    members["mg05"] = b"\x01\x02\x03\x04\x05\x06\x07\x08"
    with zipfile.ZipFile(d / "doapp.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in members.items():
            z.writestr(n, b)
    with zipfile.ZipFile(d / "coh1002m.zip", "w") as z:
        z.writestr("m534002c-61.ic353", b"bios")
    return members


def test_rebuild_set_layout(tmp_path):
    src = tmp_path / "owned"
    members = _fake_set(src)
    before = {n: hashlib.sha1((src / n).read_bytes()).hexdigest() for n in ("doapp.zip", "coh1002m.zip")}
    new = bytes(range(251)) * 100
    other = next(i for i, (b, o, s) in enumerate(D.FILE_TABLE) if s and b == 1 and o >= 0x400000)   # doapp-2.218
    cs, csize = D.file_span(other)
    r = W.rebuild_set(src, {49: new, other: b"\xEE" * csize}, tmp_path / "mod")
    assert {n: hashlib.sha1((src / n).read_bytes()).hexdigest() for n in ("doapp.zip", "coh1002m.zip")} == before
    with zipfile.ZipFile(src / "doapp.zip") as a, zipfile.ZipFile(tmp_path / "mod" / "doapp.zip") as b:
        assert [(i.filename, i.file_size) for i in a.infolist()] == [(i.filename, i.file_size) for i in b.infolist()]
        got = {i.filename: b.read(i.filename) for i in b.infolist()}
    start, size = D.file_span(49)                          # bank 1 offset 0 = doapp-1.217 offset 0
    chip = got["doapp-1.217"]
    assert chip[:len(new)] == new and chip[len(new):size] == bytes(size - len(new))
    assert chip[size:] == members["doapp-1.217"][size:]
    changed = {n for n, v in r["chips"].items() if v["changed"]}
    assert changed == {"doapp-1.217", "doapp-2.218"} and r["files"][other]["chips"] == ["doapp-2.218"]
    assert got["doapp-2.218"][cs - 0xC00000:cs - 0xC00000 + csize] == b"\xEE" * csize
    assert got["doapp119.bin"] == members["doapp119.bin"] and got["mg05"] == members["mg05"]
    assert got["doapp-0.216"] == members["doapp-0.216"] and got["doapp-5.221"] == members["doapp-5.221"]
    assert (tmp_path / "mod" / "coh1002m.zip").read_bytes() == (src / "coh1002m.zip").read_bytes()
    assert D.read_file(D.merge_parent(str(tmp_path / "mod" / "doapp.zip")), other) == b"\xEE" * csize
    # no model file of the game straddles two 4 MiB chips (files are packed per chip)
    assert all((b * D.BANK_SIZE + o) // 0x400000 == (b * D.BANK_SIZE + o + max(s, 1) - 1) // 0x400000
               for b, o, s in D.FILE_TABLE)
    with pytest.raises(W.WriterError):
        W.rebuild_set(src, {49: bytes(W.budget(49) + 1)}, tmp_path / "mod2")


# ------------------------------------------------------------------------------------------------ owned ROMs
@pytest.fixture(scope="module")
def owned():
    banked, ram, _entry = D.decode_owned(OWNED)
    return banked, ram


@needs_roms
def test_owned_packer_is_the_expanders_inverse(owned):
    """All 44 costume models: the expander port == the game's 0x8006c718 byte for byte, and packing the game's
    expansion reproduces Tecmo's packed bytes exactly."""
    banked, ram = owned
    sections = identical = 0
    for f in D.FIGHTERS:
        for c in range(D.COSTUMES):
            model = D.read_file(banked, f["models"][c])
            game = M.unpack_model(model, ram)
            assert W.expand_all(model) == game, (f["name"], c)
            for r in W.walk_container(model):
                if r["packed"]:
                    sections += 1
                    mesh = W.mesh_from_expanded(game[r["index"]], M.WORK_BASE + r["dest"])
                    identical += W.pack_mesh(mesh) == model[r["start"]:r["end"]]
    assert sections == identical == 327


@needs_roms
def test_owned_build_reads_back_and_rebuilds_the_set(owned, tmp_path):
    banked, ram = owned
    roles = humanoid(tmp_path / "tube.gltf", rings=4, sides=8)
    jobs = [(D.fighter("tina"), 0), (D.fighter("zack"), 3)]           # 8-slot costume / 14-group body + chains
    res = W.build(ram, banked, tmp_path / "tube.gltf", roles, jobs, tmp_path / "work", "Tube")
    for f, c in jobs:
        rep = res["reports"][f["models"][c]]
        assert rep["check"]["game_expander_identical"] and rep["check"]["port_matches_layout"], rep["check"]
        rb = rep["read_back"]
        assert rb["ok"] and rb["untextured_prims"] == 0 and rb["seam_triangles"] > 0, rb
        assert len(res["files"][f["models"][c]]) <= W.budget(f["models"][c])
    rs = W.rebuild_set(OWNED, res["files"], tmp_path / "mod")
    back = D.merge_parent(str(tmp_path / "mod" / "doapp.zip"))
    assert back[:0x400000] == banked[:0x400000]             # program ROMs untouched (same decode, same file table)
    for idx, data in res["files"].items():
        start, size = D.file_span(idx)
        assert back[start:start + len(data)] == data and not any(back[start + len(data):start + size])
    changed = {n for n, v in rs["chips"].items() if v["changed"]}
    assert changed == {"doapp-1.217"}                        # files 49 / 62: bank 1, first 4 MiB
    mask = np.ones(len(back), bool)
    for idx in res["files"]:
        start, size = D.file_span(idx)
        mask[start:start + size] = False
    a, b = np.frombuffer(back, np.uint8), np.frombuffer(banked[:len(back)], np.uint8)
    assert (a[mask] == b[mask]).all()                        # nothing else moved


@needs_roms
def test_owned_player_two_expansion(owned, tmp_path):
    """The same built file expanded for player 2 by the game (a0 = 1) and by the port agree."""
    from gbox import zn_tps_boot as Z
    banked, ram = owned
    roles = humanoid(tmp_path / "tube.gltf")
    res = W.build(ram, banked, tmp_path / "tube.gltf", roles, [(D.fighter("kasumi"), 1)], tmp_path / "w", "Tube",
                  verify=False)
    data = next(iter(res["files"].values()))
    mem = Z.ZNMemory(b"\0" * 16, b"", b"\0" * 8, b"\0" * 8, ram_size=0x400000)
    mem.ram[:len(ram)] = ram
    mem.ram[0x300000:0x300000 + len(data)] = data
    cpu = Z.R3000(mem)
    tm = W._new_template()
    work = 0x8028E800
    for r in W.walk_container(data):
        if r["packed"]:
            cpu.call(M.UNPACK_FN, (1, 0x80300000 + r["start"], work + r["dest"]), sp=0x803FFF00)
            port, _ = W.expand_mesh(data, r["start"], work + r["dest"], player=1, template=tm)
            a = (work + r["dest"]) & 0x3FFFFF
            assert bytes(mem.ram[a:a + r["length"]]) == port, r["index"]
