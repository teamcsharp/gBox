"""Tests for the 007 Agent Under Fire GC character writer (gbox.auf_gcm encoder, gbox.auf_swap writer).

Synthetic tests build a skeleton, a .gcm, a whole level package (.men scripts, script dictionary, textures, shaders,
BSP, restable) and a tiny GameCube disc image, so they pin the encoder (reader -> writer -> reader), the package and
texture-chunk rebuild with their offsets, the disc layout and the slot/cast parsing without the game.  The owned-disc
tests run where the GCZ is cached (GBOX_AUF_GCZ or ~/gbox-cache/gc/<game>/source.gcz) and skip elsewhere.
"""
import hashlib
import json
import os
import struct
import types
from pathlib import Path

import numpy as np
import pytest

from gbox import auf_gcm as G
from gbox import auf_ngc as N
from gbox import auf_ngc_writer as W
from gbox import auf_swap as S

GCZ = os.environ.get("GBOX_AUF_GCZ", os.path.expanduser("~/gbox-cache/gc/65b7187589166b26/source.gcz"))

# AUF frame: Z up, the character faces +X, its left is +Y (as on the disc)
BONES = [  # (parent, world position)
    (-1, (0, 0, 50)), (0, (0, 0, 50)),
    (1, (0, -6, 47)), (2, (0, -6, 25)), (3, (0, -6, 4)), (4, (4, -6, 1)),
    (1, (0, 6, 47)), (6, (0, 6, 25)), (7, (0, 6, 4)), (8, (4, 6, 1)),
    (1, (0, 0, 55)), (10, (0, 0, 62)), (11, (0, 0, 70)), (12, (0, 0, 80)), (13, (0, 0, 84)),
    (12, (0, -2, 76)), (15, (0, -9, 76)), (16, (0, -22, 76)), (17, (0, -35, 76)),
    (12, (0, 2, 76)), (19, (0, 9, 76)), (20, (0, 22, 76)), (21, (0, 35, 76)),
    (-1, (0, 0, 0)),
]


def _blk(w0, body, extra=0):
    body = body + b"\0" * (-len(body) % 8)
    return struct.pack(">II", w0, (len(body) << 8) | extra) + b"\0" * extra + body


def template(bones=BONES, names=("body_mat",), palette=40, hash_seed=0x1000) -> bytes:
    """A minimal .gcm: header + bones + rest pose + empty palette/geometry + material names."""
    nb = len(bones)
    bone_tab = b"".join(struct.pack(">iI", p, hash_seed + i) for i, (p, _w) in enumerate(bones))
    rest = b""
    for i, (p, w) in enumerate(bones):
        loc = np.subtract(w, bones[p][1]) if p >= 0 else np.asarray(w, float)
        rest += struct.pack(">8f", *loc, 0.0, 0.0, 0.0, 0.0, 1.0)
    pal = struct.pack(">hhf", 0, -2, 1.0)
    ngc_body = struct.pack(">12f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0) + struct.pack(">f", 1.11) + b"\0" * (0x9C - 0x34)
    nm = b"".join(n.encode().ljust(64, b"\0") for n in names)
    hdr = bytearray(0x98)
    parts = [(0x74, _blk(0x64, bone_tab)), (0x78, _blk(0x67, rest)), (0x7C, _blk(0x3EC, pal, 8)),
             (0x80, _blk(0x3ED, ngc_body, 8)), (0x94, _blk(0x44C, nm, 8))]
    out = bytearray(_blk(0x48400001, bytes(hdr), 8))
    for f, b in parts:
        struct.pack_into(">I", out, 0x10 + f, len(out))
        out += b
    struct.pack_into(">I", out, 0x10 + 8, 0x01000000)
    struct.pack_into(">I", out, 0x10 + 0x0C, len(out))
    struct.pack_into(">HHHHHH", out, 0x10 + 0x50, nb, 0, 1, 0, 0, len(names))
    struct.pack_into(">HH", out, 0x10 + 0x54, palette, 0)
    return bytes(out)


def body_mesh(bones=BONES):
    """A box per limb segment; corners near the parent joint blend 50/50 with the parent bone."""
    P, Nn, UV, J, Wt, F = [], [], [], [], [], []
    for i, (p, w) in enumerate(bones):
        kids = [k for k, (q, _w) in enumerate(bones) if q == i]
        if p < 0 or not kids:
            continue
        a, b = np.asarray(w, float), np.asarray(bones[kids[0]][1], float)
        d = b - a
        if np.linalg.norm(d) < 1e-6:
            continue
        u = np.cross(d, [1.0, 0, 0] if abs(d[0]) < 0.9 * np.linalg.norm(d) else [0, 1.0, 0])
        u = u / np.linalg.norm(u) * 1.5
        v = np.cross(d / np.linalg.norm(d), u)
        base = len(P)
        for t in (0.0, 1.0):
            for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                q = a + t * d + su * u + sv * v
                P.append(q)
                Nn.append((su * u + sv * v) / np.linalg.norm(su * u + sv * v))
                UV.append((0.25 * (su + 2), t))
                J.append((i, p if t == 0.0 else -1))
                Wt.append(0.5 if t == 0.0 else 1.0)
        for k in range(4):
            a0, a1, b0, b1 = base + k, base + (k + 1) % 4, base + 4 + k, base + 4 + (k + 1) % 4
            F += [(a0, a1, b1), (a0, b1, b0)]
    return (np.asarray(P), np.asarray(Nn), np.asarray(UV), np.asarray(J), np.asarray(Wt), np.asarray(F))


def _faces(m):
    P = np.asarray(m["positions"])
    return P[np.asarray([f[:3] for f in m["faces"]])]


def _match(src, dst, tol):
    """every dst triangle equals some src triangle, same winding (rotations only)"""
    for t in dst:
        d = np.min([np.abs(src - np.roll(t, r, 0)[None]).max((1, 2)) for r in range(3)], 0)
        assert d.min() < tol


# ----------------------------------------------------------------------------------------------- encoder

def test_auto_roles_on_a_biped():
    tpl = template()
    roles = G.auto_roles(N.skeleton(tpl))
    assert roles == {"hip": 1, "r_thigh": 2, "r_shin": 3, "r_foot": 4, "l_thigh": 6, "l_shin": 7, "l_foot": 8,
                     "chest": 12, "neck": 13, "head": 14, "r_clav": 15, "r_upper": 16, "r_fore": 17, "r_hand": 18,
                     "l_clav": 19, "l_upper": 20, "l_fore": 21, "l_hand": 22}
    with pytest.raises(ValueError):
        G.auto_roles(N.skeleton(template([(-1, (0, 0, 0)), (0, (0, 0, 10))])))


def test_synthetic_round_trip_reader_writer_reader():
    tpl = template()
    P, Nn, UV, J, Wt, F = body_mesh()
    gcm, rep = G.encode_gcm(tpl, P, Nn, UV, J, Wt, F, np.zeros(len(F), int), ["body_mat"])
    info = N.gcm_info(gcm)
    assert N.tile_check(info) == [] and rep["triangles"] == len(F) and rep["palette"] <= 40
    assert G.section_names(gcm) == ["body_mat"]
    secs = N._array(gcm, info, 9, ">IIHHI")
    assert secs[0][1] == W.hash_string("body_mat")
    m = N.mesh(gcm)
    assert len(m["faces"]) == len(F)
    _match(P[F], _faces(m), 0.01)
    assert N.winding_agreement(m) > 0.95
    # header: size, bounds, radius, counts
    assert struct.unpack_from(">I", gcm, 0x1C)[0] == len(gcm) and len(gcm) % 32 == 0
    c = np.array(struct.unpack_from(">3f", gcm, 0x30))
    r = struct.unpack_from(">f", gcm, 0x50)[0]
    assert abs(r - np.linalg.norm(P - c, axis=1).max()) < 1e-3
    assert struct.unpack_from(">I", gcm, 0x10 + 0x68)[0] == len(F)
    # blends survive: some vertices decode with two bones
    assert any(w[1] > 0 for w in m["weights"])
    # reader -> writer -> reader again is stable
    J2 = np.asarray(m["joints"])
    W2 = np.asarray([w[0] for w in m["weights"]])
    J2[:, 1] = np.where(np.asarray([w[1] for w in m["weights"]]) > 0, J2[:, 1], -1)
    F2 = np.asarray([f[:3] for f in m["faces"]])
    gcm2, _ = G.encode_gcm(gcm, m["positions"], m["normals"], m["uvs"], J2, W2, F2, np.zeros(len(F2), int), ["body_mat"])
    _match(_faces(m), _faces(N.mesh(gcm2)), 0.01)


def test_palette_respects_the_slot_limit():
    bones = N.skeleton(template())
    J = np.array([[17, 16], [17, 16], [21, 20], [3, 2], [3, -1]])
    W_ = np.array([0.53, 0.86, 0.5, 0.2, 1.0])
    recs, idx, step = G.palette_records(bones, J, W_, 10)
    assert step == 0.1 and recs[idx[0]] == (17, 16, 0.5) and recs[idx[1]] == (17, 16, 0.9)
    assert recs[idx[4]] == (3, -2, 1.0)
    # parent-first pairs are turned so the record rotates about the child's joint
    recs, idx, _ = G.palette_records(bones, np.array([[16, 17]]), np.array([0.3]), 10)
    assert recs[0] == (17, 16, 0.7)
    recs, idx, step = G.palette_records(bones, J, W_, 3)     # coarser weights until it fits
    assert len(recs) <= 3
    with pytest.raises(ValueError):
        G.palette_records(bones, np.array([[1, -1], [2, -1], [3, -1]]), np.ones(3), 2)


def test_stripify_keeps_every_triangle_and_its_winding():
    faces = [(0, 1, 2), (2, 1, 3), (2, 3, 4), (4, 3, 5), (7, 8, 9)]
    strips = G.stripify(faces)
    got = []
    for vs in strips:
        for k in range(len(vs) - 2):
            a, b, c = vs[k], vs[k + 1], vs[k + 2]
            got.append((b, a, c) if not k & 1 else (a, b, c))
    norm = {tuple(np.roll(f, -int(np.argmin(f)))) for f in faces}
    assert {tuple(np.roll(f, -int(np.argmin(f)))) for f in got} == norm and len(got) == len(faces)
    assert len(strips) < len(faces) and max(len(s) for s in strips) == 4


def test_empty_model_draws_nothing_and_keeps_the_skeleton():
    gcm = G.empty_gcm(template())
    assert N.mesh(gcm)["faces"] == [] and len(N.skeleton(gcm)) == len(BONES)
    assert struct.unpack_from(">H", gcm, 0x10 + 0x54)[0] == 1 and G.section_names(gcm) == ["body_mat"]


def test_cmpr_encoder_decodes_back():
    rng = np.random.default_rng(3)
    img = np.zeros((32, 16, 4), np.uint8)
    img[..., 3] = 255
    img[:16, :, :3] = (200, 30, 40)
    img[16:, :, :3] = rng.integers(0, 255, (16, 16, 3))
    data = G.encode_cmpr(img)
    assert len(data) == N.gx_image_size(N.GX_CMPR, 16, 32)
    back = np.frombuffer(N.decode_gx(N.GX_CMPR, 16, 32, data), np.uint8).reshape(32, 16, 4)
    assert np.abs(back[:16, :, :3].astype(int) - (200, 30, 40)).max() <= 8      # flat colour: 565 rounding only
    assert np.abs(back[16:, :, :3].astype(int) - img[16:, :, :3]).mean() < 60
    chain = G.encode_texture(np.full((64, 64, 4), 128, np.uint8), 4)
    assert len(chain) == N.gx_chain_size(N.GX_CMPR, 64, 64, 4)


# ----------------------------------------------------------------------------------------------- a synthetic level

def _restxtrs(texs):
    """[(id, w, h, fill rgb, second plane?)] -> restxtrs payload (CMPR, no mips)."""
    n = len(texs)
    ido, reco = 0x10, 0x10 + ((4 * n + 15) & ~15)
    out = bytearray(reco + 0x44 * n)
    struct.pack_into(">fIII", out, 0, 1.2, n, ido, reco)
    for i, (tid, w, h, rgb, plane2) in enumerate(texs):
        struct.pack_into(">I", out, ido + 4 * i, tid)
        out += b"\0" * (-len(out) % 32)
        img = np.zeros((h, w, 4), np.uint8)
        img[..., :3] = rgb
        data = G.encode_cmpr(img)
        off = len(out)
        out += data
        r = reco + 0x44 * i
        struct.pack_into(">IHHIIII", out, r, N.GX_CMPR, w, h, 1, 1, off, len(data))
        if plane2:
            p2 = G.encode_texture(np.full((h, w), 9, np.uint8), 1, N.GX_I8)
            out += b"\0" * (-len(out) % 32)
            struct.pack_into(">III", out, r + 0x18, N.GX_I8, len(out), len(p2))
            out += p2
    return bytes(out)


def _shaders(table):
    """{shader id: texture id} -> shaders payload (one group, one pass each)."""
    n = len(table)
    so, go, po = 0x60, 0x60 + 16 * n, 0x60 + 16 * n + 0x14 * n
    out = bytearray(po + 0x14 * n)
    struct.pack_into(">fIIIIII", out, 0, 0.95, so, n, go, n, po, n)
    for i, (sid, tid) in enumerate(table.items()):
        struct.pack_into(">IB", out, so + 16 * i, sid, 1)
        struct.pack_into(">I", out, so + 16 * i + 12, go + 0x14 * i)
        struct.pack_into(">IH", out, go + 0x14 * i, po + 0x14 * i, 1)
        struct.pack_into(">II", out, po + 0x14 * i, 0x20000, tid)
    return bytes(out)


WORDS = ["MEAN", "setup", "{", "}", "path", "models/actors", "lod_model", "test/body_l.o3d", "lod_head",
         "actorheads/head_l.o3d", "init", "server", "classname", "DeathmatchPlayer", "animations", "mp_player_male",
         "other/other_l.o3d", "actorheads/head2_l.o3d", "actor"]


def _men(words):
    toks = [WORDS.index(w) for w in words]
    body = b"".join(struct.pack(">HH", t, 0xFFFF) for t in toks)
    return b"CS\x02\x01\x01" + b"\0" * (0x24 - 5) + body


def _model(names, mesh=True):
    tpl = template(names=names)
    if not mesh:
        return tpl
    P, Nn, UV, J, Wt, F = body_mesh()
    return G.encode_gcm(tpl, P, Nn, UV, J, Wt, F, np.arange(len(F)) % len(names), list(names))[0]


def level_package() -> bytes:
    hb, hh, hs, ho = (W.hash_string(n) for n in ("body_mat", "head_mat", "hand_mat", "other_mat"))
    head = template(names=("head_mat",))
    P, Nn, UV, J, Wt, F = body_mesh()
    sel = np.all(np.isin(J[F, 0], [13, 14]), axis=1) | np.all(np.isin(J[F, 0], [12]), axis=1)
    head = G.encode_gcm(head, P, Nn, UV, J, Wt, F[sel], np.zeros(sel.sum(), int), ["head_mat"])[0]
    files = {
        "models/actors/test/body_l.gcm": _model(("body_mat", "hand_mat")),
        "models/actors/actorheads/head_l.gcm": head,
        "models/actors/other/other_l.gcm": _model(("other_mat", "hand_mat")),
        "models/actors/actorheads/head2_l.gcm": template(names=("other_mat",)),
        "models/mp_player_test.men": _men(["MEAN", "setup", "{", "path", "models/actors", "lod_model", "{",
                                           "test/body_l.o3d", "}", "lod_head", "{", "actorheads/head_l.o3d", "}", "}",
                                           "init", "{", "server", "{", "classname", "DeathmatchPlayer", "}", "}",
                                           "animations", "mp_player_male"]),
        "models/mp_player_other.men": _men(["MEAN", "setup", "{", "path", "models/actors", "lod_model", "{",
                                            "other/other_l.o3d", "}", "lod_head", "{", "actorheads/head2_l.o3d", "}",
                                            "}", "init", "{", "server", "{", "classname", "actor", "}", "}",
                                            "animations", "mp_player_male"]),
        "script_dictionary": b"CS\x06\x01" + b"\0" * 28 + b"\0".join(w.encode() for w in WORDS) + b"\0",
    }
    tx = _restxtrs([(0xA1, 64, 64, (10, 200, 10), False), (0xA2, 32, 32, (200, 10, 10), True),
                    (0xA3, 32, 32, (0, 0, 200), False), (0xA4, 64, 32, (90, 90, 90), False)])
    sh = _shaders({hb: 0xA1, hh: 0xA2, hs: 0xA3, ho: 0xA4})
    return (W.encode_chunk("restxtrs", tx) + W.encode_chunk("shaders", sh)
            + W.encode_chunk("bspfile", b"BSP!" * 64, 1.0, False)
            + W.encode_chunk("restable", W.build_restable(files.items())))


@pytest.fixture(scope="module")
def donor(tmp_path_factory):
    """A rigged donor GLB: the synthetic body, exported by the reader (bones named bone%02d_<hash>)."""
    d = tmp_path_factory.mktemp("donor")
    m = N.mesh(_model(("body_mat",)))
    glb = d / "donor.glb"
    N.to_glb(m, glb, "donor")
    roles = {r: "bone%02d_%08x" % (i, 0x1000 + i) for r, i in G.auto_roles(N.skeleton(template())).items()}
    return S.load_donor("synthetic_wrestler", glb, roles, "Synthetic Wrestler")


def test_level_cast_reads_the_entity_scripts():
    pkg = N.NgcPackage(level_package())
    cast = {c.key: c for c in S.level_cast(pkg)}
    assert set(cast) == {"body", "other"}
    assert cast["body"].cls == "deathmatchplayer" and cast["body"].bodies == ["models/actors/test/body_l.gcm"]
    assert cast["body"].heads == ["models/actors/actorheads/head_l.gcm"] and cast["other"].cls == "actor"


def test_free_shaders_skip_shared_and_bsp_textures():
    pkg = N.NgcPackage(level_package())
    free = G.free_shaders(pkg, {"models/actors/test/body_l.gcm", "models/actors/actorheads/head_l.gcm"})
    assert [f["texture"] for f in free] == [0xA1, 0xA2]           # hand_mat is shared with 'other'
    assert G.free_shaders(pkg, {"models/actors/actorheads/head_l.gcm"})[0]["texture"] == 0xA2


def test_level_rebuild_offsets_textures_and_models(donor):
    data = level_package()
    out, rep = S.swap_level(data, {"body": donor}, "synthetic")
    q = N.NgcPackage(out)
    # package: 32-aligned chunks, restable sorted by hash with 16-aligned files, every replaced file decodes
    assert all(c.offset % 32 == 0 for c in q.chunks) and [c.id for c in q.chunks] == \
        [c.id for c in N.NgcPackage(data).chunks]
    assert W.check_package(out)["problems"] == []
    body = q.read("models/actors/test/body_l.gcm")
    m = N.mesh(body)
    pages = rep["textures"]["synthetic_wrestler"]
    assert len(m["faces"]) > 50 and G.section_names(body) == [p["shader"] for p in pages]
    assert len(N.mesh(q.read("models/actors/actorheads/head_l.gcm"))["faces"]) == 0      # head stub
    assert rep["stub_heads"] == ["models/actors/actorheads/head_l.gcm"]
    assert q.read("models/actors/other/other_l.gcm") == N.NgcPackage(data).read("models/actors/other/other_l.gcm")
    # texture chunk: the donor's page written over a texture only the replaced models used, in place (same record,
    # size, offset, chunk length); the shared hand texture and the other model's texture untouched
    p0 = N.NgcPackage(data)
    t0, t1 = N.textures(p0), N.textures(q)
    tid = int(pages[0]["texture"], 16)
    assert tid == 0xA1 and t1 == t0 and len(q.payload("restxtrs")) == len(p0.payload("restxtrs"))
    assert N.texture_rgba(q, t1[tid]) != N.texture_rgba(p0, t0[tid])
    assert N.texture_check(q) == []
    for i in (0xA2, 0xA3, 0xA4):
        assert N.texture_rgba(q, t1[i]) == N.texture_rgba(p0, t0[i])
    secs = N.section_textures(q, m)
    assert all(t is not None and t.id == tid for t in secs)
    # the donor stands on the slot's skeleton: feet near the ground, head near the head bone
    P = np.asarray(m["positions"])
    assert P[:, 2].min() < 6 and 75 < P[:, 2].max() < 100
    # nothing assigned in this level -> unchanged bytes
    assert S.swap_level(data, {"nobody": donor}, "synthetic")[0] == data


def test_static_t_pose_donor_is_rigged_to_the_slot(tmp_path):
    """An unskinned T-pose donor (like the Def Jam Vendetta GC wrestlers) twice the slot's size lands on the slot's
    proportions, each limb on its own bones."""
    body = _model(("body_mat",))
    m = N.mesh(body)
    P = np.asarray(m["positions"]) * 2.0
    glb = tmp_path / "static.glb"
    N.to_glb(m | {"positions": P.tolist()}, glb, "static")
    d = S.load_donor("static_wrestler", glb, {})
    assert d.rig.get("static") and len(d.mats) == 1
    fit = S.fit_static(d, body, None)
    X = fit["P"]
    src = np.asarray(m["positions"])
    assert np.abs(X[:, 2].min() - src[:, 2].min()) < 1.0 and np.abs(X[:, 2].max() - src[:, 2].max()) < 1.0
    assert np.abs(np.abs(X[:, 1]).max() - np.abs(src[:, 1]).max()) < 1.0
    roles = fit["roles"]
    hand = X[:, 1] > 30
    assert set(fit["J"][hand, 0]) <= {roles["l_fore"], roles["l_hand"]}
    foot = (X[:, 2] < 10) & (X[:, 1] < 0)
    assert set(fit["J"][foot, 0]) <= {roles["r_shin"], roles["r_foot"]}
    out, rep = S.swap_level(level_package(), {"body": d}, "synthetic")
    assert rep["replaced"][0]["fit"]["static"] is True and N.texture_check(N.NgcPackage(out)) == []


def test_decimate_reaches_the_budget_without_flips():
    P, Nn, UV, J, Wt, F = body_mesh()
    P2, F2 = S.decimate(P, F, len(F) // 2)
    assert len(F2) <= len(F) // 2 + 2 and len(F2) > 0
    n0 = np.cross(P[F2][:, 1] - P[F2][:, 0], P[F2][:, 2] - P[F2][:, 0])
    n1 = np.cross(P2[F2][:, 1] - P2[F2][:, 0], P2[F2][:, 2] - P2[F2][:, 0])
    assert ((n0 * n1).sum(1) >= 0).mean() > 0.9


def test_atlas_uvs_shift_repeats_into_the_tile():
    uv = S.atlas_uvs(np.array([[1.25, 2.5], [1.75, 2.5], [1.5, 3.0]]), (128, 0, 128, 64), (256, 128))
    assert np.all((uv[:, 0] >= 0.5) & (uv[:, 0] <= 1.0) & (uv[:, 1] >= 0) & (uv[:, 1] <= 0.5))


def test_pages_pack_materials_by_area():
    red = np.zeros((64, 64, 3), np.uint8)
    red[..., 0] = 255
    mats = [(("a", (255, 255, 255)), red, (255, 255, 255), 4096), (("b", (0, 0, 255)), None, (0, 0, 255), 64),
            (("c", (255, 255, 255)), red, (128, 128, 128), 4096)]
    imgs, layout = S.build_pages(mats, [(128, 128), (64, 32)])
    assert [i.shape for i in imgs] == [(128, 128, 4), (32, 64, 4)]
    assert {v[0] for v in layout.values()} == {0, 1} and set(layout) == {m[0] for m in mats}
    page, (x0, y0, tw, th), size = layout[("b", (0, 0, 255))]
    assert tuple(imgs[page][y0 + th // 2, x0 + tw // 2, :3]) == (0, 0, 255)
    page, (x0, y0, tw, th), size = layout[("c", (255, 255, 255))]
    assert tuple(imgs[page][y0 + th // 2, x0 + tw // 2, :3]) == (128, 0, 0)          # colour factor applied


def test_texture_written_in_place_keeps_the_chunk_layout():
    tx = _restxtrs([(0xA1, 64, 64, (10, 200, 10), False), (0xA2, 32, 32, (200, 10, 10), True)])
    img = np.zeros((64, 64, 4), np.uint8)
    img[..., 2] = 250
    out = G.write_texture_in_place(tx, 0xA1, img)
    assert len(out) == len(tx)
    n, ido, reco = G.texture_records(out)
    assert out[reco:reco + 0x44 * n] == tx[reco:reco + 0x44 * n]
    off, size = struct.unpack_from(">II", out, reco + 0x10)
    back = np.frombuffer(N.decode_gx(N.GX_CMPR, 64, 64, out[off:off + size]), np.uint8).reshape(64, 64, 4)
    assert abs(int(back[..., 2].mean()) - 250) < 8
    off2, size2 = struct.unpack_from(">II", out, reco + 0x44 + 0x10)
    assert out[off2:off2 + size2] == tx[off2:off2 + size2]
    with pytest.raises(ValueError):
        G.write_texture_in_place(tx, 0xA1, np.zeros((32, 32, 4), np.uint8))
    with pytest.raises(KeyError):
        G.write_texture_in_place(tx, 0xBB, img)


# ----------------------------------------------------------------------------------------------- the disc

def gc_image(path: Path, files: dict) -> Path:
    """A tiny GameCube image: header, empty DOL header, FST with directories, files from 0x8000 (32 KiB apart)."""
    tree: dict = {}
    for k in files:
        parts = k.split("/")
        d = tree
        for p in parts[:-1]:
            d = d.setdefault(p, {})
        d[parts[-1]] = k
    entries, names = [], bytearray(b"\0")
    data_off = 0x8000
    layout = {}

    def walk(d, parent):
        nonlocal data_off
        for name in sorted(d):
            noff = len(names)
            names.extend(name.encode() + b"\0")
            if isinstance(d[name], dict):
                idx = len(entries)
                entries.append([(1 << 24) | noff, parent, 0])
                walk(d[name], idx)
                entries[idx][2] = len(entries)
            else:
                b = files[d[name]]
                entries.append([noff, data_off, len(b)])
                layout[d[name]] = data_off
                data_off = (data_off + len(b) + 0x7FFF) & ~0x7FFF
    entries.append([1 << 24, 0, 0])
    walk(tree, 0)
    entries[0][2] = len(entries)
    fst = b"".join(struct.pack(">III", *e) for e in entries) + bytes(names)
    img = bytearray(data_off)
    img[0:6] = b"GW7E69"
    img[0x20:0x40] = b"007: Agent Under Fire (tm)".ljust(32, b"\0")
    struct.pack_into(">III", img, 0x420, 0x2440, 0x2600, len(fst))
    img[0x2600:0x2600 + len(fst)] = fst
    for k, off in layout.items():
        img[off:off + len(files[k])] = files[k]
    path.write_bytes(bytes(img))
    return path


def test_disc_rebuild_in_place_and_moved(tmp_path):
    from gbox import filemods
    from gbox.gcdisc import GCDisc
    src = gc_image(tmp_path / "auf.iso", {"maps/a.ngc": b"A" * 1000, "maps/b.ngc": b"B" * 3000,
                                          "opening.bnr": b"BNR" * 10})
    before = hashlib.sha256(src.read_bytes()).hexdigest()
    cfg = types.SimpleNamespace(cache=tmp_path / "cache")
    b = filemods.build_image(cfg, S.GAME_ID, src, "t", {"maps/a.ngc": {"bytes": b"a" * 800},
                                                       "maps/b.ngc": {"bytes": b"b" * 50000}})
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before          # never in place
    d0, d1 = GCDisc(src), GCDisc(b["image"])
    try:
        assert d1.files["maps/a.ngc"] == (d0.files["maps/a.ngc"][0], 800)    # fits its slot
        off, size = d1.files["maps/b.ngc"]
        assert size == 50000 and off >= max(o + s for o, s in d0.files.values()) and off % 0x8000 == 0
        assert d1.read("maps/a.ngc") == b"a" * 800 and d1.read("maps/b.ngc") == b"b" * 50000
        assert d1.read("opening.bnr") == d0.read("opening.bnr") and d1.game_id == "GW7E69"
    finally:
        d0.f.close()
        d1.f.close()


def test_build_mod_end_to_end_on_a_synthetic_disc(tmp_path, donor):
    from gbox.gcdisc import GCDisc
    level = level_package()
    src = gc_image(tmp_path / "auf.iso", {"maps/dm1.ngc": level, "maps/dm2.ngc": level, "maps/dm3.ngc": level,
                                          "opening.bnr": b"x" * 64})
    plan = {("dm1", "body"): "synthetic_wrestler", ("dm2", "body"): "synthetic_wrestler"}
    r = S.build_mod(tmp_path / "cache", src, "auf_test", plan, {"synthetic_wrestler": donor}, workers=2)
    d = GCDisc(r["image"])
    try:
        for lv in ("dm1", "dm2"):
            q = N.NgcPackage(d.read(f"maps/{lv}.ngc"))
            assert len(N.mesh(q.read("models/actors/actorheads/head_l.gcm"))["faces"]) == 0
            assert len(N.mesh(q.read("models/actors/test/body_l.gcm"))["faces"]) > 50
        assert d.read("maps/dm1.ngc") == d.read("maps/dm2.ngc")              # deterministic across processes
        assert d.read("maps/dm3.ngc") == level                                # untouched level
    finally:
        d.f.close()
    marker = json.loads((Path(r["dir"]) / ".gbox-mod.json").read_text())
    assert marker["writer"] == "gbox.auf_swap" and marker["cast"] == [["dm1", "body", "synthetic_wrestler"],
                                                                      ["dm2", "body", "synthetic_wrestler"]]
    assert S._disc_reader(Path(r["image"]))("maps/dm1.ngc") == d.__class__(r["image"]).read("maps/dm1.ngc")


# ----------------------------------------------------------------------------------------------- slots

def test_slot_parsing_and_groups():
    lv = S.level_keys()
    assert len(lv) == 37 and "frontend" not in lv
    player = S.select("player")
    assert {k for _l, k in player} == {"bond_tux", "bond_combat", "bond_graysuit", "bond_jetpack"}
    assert ("m6_1", "bond_tux") in player and ("dm1", "bond_combat") in player
    enemies = S.select("enemies")
    assert ("m6_1", "henchmen_vest") in enemies and ("dm1", "henchmen_vest") not in enemies   # bots are not enemies
    assert {k for _l, k in enemies} == {k for k, (_n, kind) in S.NAMES.items() if kind == "enemy"}
    bots = S.select("bots")
    assert {k for _l, k in bots} == set(S.MP_KEYS) and {l for l, _k in bots} == set(S.MP_MAPS)
    assert ("dmescort", "vip_body") not in bots and ("dmescort", "vip_body") in S.select("npcs")
    assert S.select("model:Thug_Orchid_h.o3d") == S.select("thug_orchid") and len(S.select("model:thug_orchid")) == 21
    assert S.select("all") == S.select("cast")
    with pytest.raises(ValueError):
        S.select("model:nobody")
    with pytest.raises(ValueError):
        S.select("the rock")
    assert all(S.is_slot(s) for s in ("player", "enemies", "bots", "cast", "model:zero", "zoe_body"))
    assert not S.is_slot("driver:axel")


def test_cast_plan_fixed_targets_and_seeded_deal():
    plan = S.plan_cast([("player", "sd2_the_rock"), ("", "nm_kane"), ("", "nm_undertaker"),
                        ("thug_orchid", "sd2_mankind")], seed="wwf")
    assert plan[("m6_1", "bond_tux")] == "sd2_the_rock" and plan[("orc_1", "thug_orchid")] == "sd2_mankind"
    assert plan[("dm1", "thug_orchid")] == "sd2_mankind"
    dealt = {v for (lv, k), v in plan.items() if k not in ("bond_tux", "bond_combat", "bond_graysuit", "bond_jetpack",
                                                           "thug_orchid")}
    assert dealt == {"nm_kane", "nm_undertaker"}
    assert len(plan) == len(S.select("all"))
    per_key = {}
    for (lv, k), v in plan.items():
        per_key.setdefault(k, set()).add(v)
    assert all(len(v) == 1 for v in per_key.values())                     # one donor per body, in every level
    assert S.plan_cast([("player", "sd2_the_rock"), ("", "nm_kane"), ("", "nm_undertaker"),
                        ("thug_orchid", "sd2_mankind")], seed="wwf") == plan
    # a narrower target beats a group
    p2 = S.plan_cast([("enemies", "a"), ("thug_uwb", "b")])
    assert p2[("uwb_2a", "thug_uwb")] == "b" and p2[("m6_1", "henchmen_vest")] == "a"
    with pytest.raises(ValueError):
        S.plan_cast([("player", "")])
    assert S.mod_name("cast", plan) == S.mod_name("cast", dict(plan)) and S.mod_name("player", plan).startswith("auf_player_")


def test_entity_model_strings_map_to_slots():
    # the attract-mode bot match on JAYBUILTFINALE (docs/auf-entity-analysis.md section 6)
    assert S.slot_for_entity("models/mp_player_bondtux.men") == "model:bond_tux"
    assert S.slot_for_entity("models/mp_player_griffen.men") == "model:griffin_body"
    assert S.slot_for_entity("models/mp_player_bloch.men") == "model:zero_body"
    assert S.slot_for_entity("MODELS\\\\ACTOR_THUG_ORCHID2_EXP.MEN") == "model:thug_orchid"
    assert S.slot_for_entity("models/fx_steam.men") is None
    assert set(S.MEN) == set(S.NAMES)
    pkg = N.NgcPackage(level_package())
    assert S.slot_for_entity("models/mp_player_other.men", pkg) == "model:other"


def test_roster_and_cast_slots_list_without_collecting():
    ros = S.roster()
    assert len(ros) == len(S.NAMES) and all(r["kind"] == "slot" and r["collect"] is False for r in ros)
    cast = S.cast_slots()
    assert [c["slot"] for c in cast[:7]] == ["player", "enemies", "bosses", "npcs", "bots", "all", "cast"]
    assert len({c["slot"] for c in cast}) == len(cast)


def test_use_builds_the_mod_and_records_the_target(tmp_path, monkeypatch):
    """characters op=use on the control plane: donor from the collection, plan from the slot, disc mod built, target
    recorded; the plan's mod name is stable so a second use reuses the build."""
    from gbox import characters as C
    lib = tmp_path / "lib" / "synthetic_wrestler"
    lib.mkdir(parents=True)
    N.to_glb(N.mesh(_model(("body_mat",))), lib / "donor.glb", "donor")
    roles = {r: "bone%02d_%08x" % (i, 0x1000 + i) for r, i in G.auto_roles(N.skeleton(template())).items()}
    meta = {"slug": "synthetic_wrestler", "name": "Synthetic Wrestler", "model": "donor.glb", "rig": {"roles": roles},
            "source": {}}
    (lib / "meta.json").write_text(json.dumps(meta))
    iso = gc_image(tmp_path / "auf.iso", {"maps/dm1.ngc": level_package(), "opening.bnr": b"x" * 64})
    calls = []
    monkeypatch.setattr(C, "library_root", lambda cfg=None: tmp_path / "lib")
    monkeypatch.setattr(C, "_gc_iso", lambda ctx, game: iso)
    monkeypatch.setattr(C, "_api", lambda ctx, method, path, **kw: calls.append((method, path, kw.get("json"))) or {})
    monkeypatch.setattr(S, "NAMES", {"body": ("Body", "bot")})
    monkeypatch.setattr(S, "level_keys", lambda: {"dm1": {"body": "deathmatchplayer"}})
    ctx = types.SimpleNamespace(config=types.SimpleNamespace(cache=tmp_path / "cache"), progress=lambda p, m: None)
    inp = types.SimpleNamespace(slot="bots", pairs=[], rebuild=False, launch=False, session_id="", title="")
    game = {"game_id": S.GAME_ID, "title": "007 - Agent Under Fire (USA)", "platform": "gamecube"}
    r = S.use(ctx, meta, game, inp)
    assert r["status"] == "built_unverified" and r["mod"].startswith("auf_bots_") and r["cast"] == [("body", meta["slug"])]
    assert (tmp_path / "cache" / "mods" / S.GAME_ID / r["mod"] / ".gbox-mod.json").exists()
    assert calls and calls[0][1] == "/api/characters/synthetic_wrestler/targets" and calls[0][2]["slot"] == "bots"
    again = S.use(ctx, meta, game, inp)
    assert again["status"] == "ready" and again["mod"] == r["mod"] and len(calls) == 1


def test_writer_is_registered_and_routed():
    from gbox import char_coverage as CC
    from gbox import characters as C
    game = {"game_id": S.GAME_ID, "title": "007 - Agent Under Fire (USA)", "platform": "gamecube"}
    w = CC.writer_for(game)
    assert w["writer"] == "gbox.auf_swap" and w["routed"] is True
    assert {"player", "enemies", "bots", "cast", "model:<body>"} <= set(w["slots"])
    slots = CC.cast_slots(game)
    assert slots[0]["slot"] == "player" and any(s["slot"] == "model:zero" for s in slots)
    name, test, roster, _run = next(d for d in C.DEDICATED if d[0] == "auf")
    assert test("007 - agent under fire (usa)", "gamecube") and len(roster()) == len(S.NAMES)


# ----------------------------------------------------------------------------------------------- owned disc

def _owned_level(tmp_path, name):
    from gbox import au_inventory
    au_inventory.extract(GCZ, [name], str(tmp_path))
    return (tmp_path / name).read_bytes()


@pytest.mark.skipif(not os.path.exists(GCZ), reason="owned AUF GCZ not cached")
def test_owned_levels_cast_matches_the_snapshot(tmp_path):
    for lv in ("dm1", "m6_1", "alp2_2"):
        pkg = N.NgcPackage(_owned_level(tmp_path, lv + ".ngc"))
        got = {}
        for c in S.level_cast(pkg):
            got.setdefault(c.key, set()).add("actor" if c.cls in ("actor", "player") else c.cls)
        want = S.level_keys()[lv]
        assert set(got) == set(want)
        assert all(want[k] in got[k] for k in want)


@pytest.mark.skipif(not os.path.exists(GCZ), reason="owned AUF GCZ not cached")
def test_owned_dm1_player_slot_takes_a_donor(tmp_path):
    data = _owned_level(tmp_path, "dm1.ngc")
    pkg = N.NgcPackage(data)
    thug = N.mesh(pkg.read("models/actors/thugs/thug_uwb_l.gcm"))
    glb = tmp_path / "thug.glb"
    N.to_glb(thug, glb, "thug")
    bones = N.skeleton(pkg.read("models/actors/thugs/thug_uwb_l.gcm"))
    roles = {r: "bone%02d_%08x" % (i, bones[i]["hash"]) for r, i in G.auto_roles(bones).items()}
    d = S.load_donor("thug_uwb_donor", glb, roles)
    out, rep = S.swap_level(data, {k: d for _l, k in S.select("player") if _l == "dm1"}, "dm1")
    q = N.NgcPackage(out)
    assert {r["body"] for r in rep["replaced"]} == {"models/actors/bond/bond_combat_l.gcm",
                                                     "models/actors/bond/bond_tux_l.gcm"}
    assert rep["stub_heads"] == ["models/actors/actorheads/bond_head_l.gcm"]
    for r in rep["replaced"]:
        g = q.read(r["body"])
        assert r["palette"] <= r["palette_limit"] and N.tile_check(N.gcm_info(g)) == []
        assert all(t is not None for t in N.section_textures(q, N.mesh(g)))
    assert len(out) <= len(data) + 64 * 1024 and N.texture_check(q) == []
    changed = [r.name for r in pkg.resources() if q.read(r.name) != pkg.read(r.name)]
    assert sorted(changed) == sorted([r["body"] for r in rep["replaced"]] + rep["stub_heads"])
