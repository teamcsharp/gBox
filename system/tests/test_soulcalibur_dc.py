"""SoulCalibur (Dreamcast) reader and writer (gbox.soulcalibur_dc / gbox.soulcalibur_swap) and the chdman-free GD-ROM
CHD unpacker (gbox.chd.write_gdi), on synthetic data: Namco LZ, olnk archives and counted tables, YUV422 twiddled
pages, an accumulation-skinned fighter model (bones, store / add rows, strips, tail), the 18 body roles, the GLB export,
the donor encoder (positions, winding, budgets, the tail kept in place), strips, the HUMAN.DAT slot rewrite, the
random costume hook (assembled, read back and interpreted), plans, and the registration in characters / char_coverage /
cast_swap / replacement_readiness; then the owned disc (skipped without it)."""
import hashlib
import os
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import chd, soulcalibur_dc as D, soulcalibur_swap as W

GID = "c747331797369f74"


# ---------------------------------------------------------------- LZ

def test_lz_hand_made_stream():
    # flag 0b1110: match then 2 literals... build: literals 'ab' (flag bits 1,1), then a match of 6 back 2
    v = (6 << 11) | 2                                          # count 6, back 2
    stream = bytes([0b1011, ord("a"), ord("b"), v >> 8, v & 0xFF, 0x00])
    assert D.lz_decompress(stream) == b"ababab" + b"ab"
    # 0xff = seven literals in one go; count 0 in the token means 32, back 0 means 2048
    lit = bytes(range(1, 8))
    assert D.lz_decompress(b"\xff" + lit + b"\x00") == lit
    data = bytes(range(256)) * 9
    v = (0 << 11) | 0                                          # 32 bytes from 2048 back
    s = D.lz_compress(data)
    assert D.lz_decompress(s + b"") == data
    with pytest.raises(ValueError):
        D.lz_decompress(bytes([0b10, 0x08, 0x05]))           # a reference before the start
    with pytest.raises(ValueError):
        D.lz_decompress(b"\x03a")                            # no end marker


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_lz_round_trip(seed):
    rng = np.random.default_rng(seed)
    parts = [rng.integers(0, 256, rng.integers(1, 300), dtype=np.uint8).tobytes() for _ in range(40)]
    data = b"".join(p * int(rng.integers(1, 5)) for p in parts) + bytes(5000)
    packed = D.lz_compress(data)
    assert D.lz_decompress(packed) == data
    assert len(packed) < len(data)


# ---------------------------------------------------------------- containers

def test_table_and_olnk_round_trip():
    parts = [b"model" * 7, bytes(64), b"", b"x" * 33]
    t = D.build_table(parts)
    n, hdr = struct.unpack_from("<II", t, 0)
    assert n == 4 and hdr == 32 and t[24:32] == D.FILLER[:8]           # the game's "32byte" padding
    assert D.table(t) == parts
    arch = D.build_olnk([t, b"", b"abc"])
    assert D.olnk(arch) == [t, b"", b"abc"]
    layout = D.olnk_layout(arch)
    assert layout[0][1] == len(t) and layout[2] == (layout[1][0], 3)
    with pytest.raises(ValueError):
        D.table(struct.pack("<II", 0, 8))
    with pytest.raises(ValueError):
        D.olnk(b"\0" * 32)


def test_yuv_page_round_trip_and_twiddle():
    tw = D._tw()
    assert sorted(tw.tolist()) == list(range(256 * 256))
    y, x = np.mgrid[0:256, 0:256]
    rgb = np.stack([x, y, (x + y) // 2], -1).astype(np.uint8)
    rgb[:, :, :] = (rgb // 2 + 60)                                     # stay inside the YUV gamut
    page = D.page_encode(rgb)
    assert len(page) == 131072
    back = D.page_rgb(page)
    assert np.abs(back.astype(int) - rgb.astype(int)).mean() < 3.0


# ---------------------------------------------------------------- a synthetic fighter

CORE = D.CORE_PARENTS
# rest positions of the 18 motion bones (game space; arms on +-X, legs down) as bone-local translations
TRANS = {1: (2000, 0, 0), 2: (4800, 0, 0), 3: (3500, 0, -1600), 4: (2200, 0, 0), 5: (4800, 0, 0), 6: (3600, 0, 0),
         7: (3500, 0, 1600), 8: (2200, 0, 0), 9: (4800, 0, 0), 10: (3600, 0, 0), 12: (2500, 0, -1600),
         13: (7000, 0, 0), 14: (6700, 0, 0), 15: (2500, 0, 1600), 16: (7000, 0, 0), 17: (6700, 0, 0), 18: (900, 0, 0)}
ANG = {0: (16383, 0, 16382), 2: (16383, 0, 16382), 3: (-22891, 16383, -6507), 4: (-16385, 56, 16382),
       7: (-7576, -16383, -8809), 8: (-16385, 56, -16384), 11: (-16385, 0, -16384)}


def _row(p, w, slot):
    bits = int(np.float32(w).view(np.uint32)) & ~0xFFF | slot
    return struct.pack("<3fI", *p, bits)


def synthetic_model(tail: bytes = b"TAILDATA" * 4) -> bytes:
    """19 bones (the shared skeleton + a head under the neck), one vertex per bone stored there and a few weighted
    ones, a strip per section, a tail the records' extra offset points at."""
    nb = 19
    parents = CORE + [2]
    recs, body = [], bytearray()
    base = 0x20 + 32 * nb
    slot = 0
    for i in range(nb):
        off = base + len(body)
        rows = [_row((0.01 * i, 0.02, 0.0), 1.0, slot)]
        nrows = [_row((0.0, -1.0, 0.0), 1.0, slot)]
        body += b"".join(rows) + b"".join(nrows)
        tr = TRANS.get(i, (0, 0, 0)) if i != 18 else (900, 0, 0)
        ang = ANG.get(i, (0, 0, 0))
        recs.append([1, 0, off, 0, 1, 1, *ang, 0, *tr, parents[i]])
        slot += 1
    strips_at = base + len(body)
    strips = bytearray()
    strips += bytes((0x31, 0, 0, 4)) + b"".join(struct.pack("<4H", s, s | (0x8000 if k == 3 else 0), 0x3f00, 0x3e80)
                                                for k, s in enumerate((0, 1, 2, 19 - 1)))
    strips += b"\0" * 4
    strips += bytes((0x30, 0, 0, 3)) + b"".join(struct.pack("<4H", s, s | (0x8000 if k == 2 else 0), 0x3e00, 0x3e00)
                                                for k, s in enumerate((11, 12, 13)))
    strips += b"\0" * 8
    tail_at = strips_at + len(strips)
    out = bytearray(struct.pack("<8H", 0x2007, 0x622, 0x710, 0x625, 0, 0, 0, 0))
    out += struct.pack("<HHHH", 0, 0x200, nb, nb) + struct.pack("<IHH", strips_at, nb, 0x414)
    for r in recs:
        r[3] = tail_at if r is recs[11] else 0
        out += struct.pack("<HHIIHH4h3hh", *r)
    out += body + strips + tail
    return bytes(out)


def test_parse_skin_and_roles():
    m = D.parse_model(synthetic_model())
    assert len(m["bones"]) == 19 and len(m["sections"]) == 2
    assert [len(s) for s in m["sections"]] == [1, 1] and m["tail"].startswith(b"TAILDATA")
    sk = D.skin(m)
    assert sk["positions"].shape == (19, 3) and np.isfinite(sk["positions"]).all()
    W0 = D.bone_world(m["bones"])
    assert np.allclose(sk["positions"][2], W0[2][:3, :3] @ [0.02, 0.02, 0] + W0[2][:3, 3])
    r = D.roles(m)
    assert r["hip"] == 11 and r["chest"] == 1 and r["neck"] == 2 and r["head"] == 18
    assert set(r) == set(D.CORE_ROLES) | {"head"} and len(r) == 18
    # the left arm (bones 3..6) sits on the game's -X side, i.e. +X in the library frame
    assert (W0[6][:3, 3] @ D.FRAME.T)[0] > 0 > (W0[10][:3, 3] @ D.FRAME.T)[0]
    assert D.glb_parents(m["bones"])[0] == 11
    with pytest.raises(ValueError):
        D.roles({"bones": m["bones"][:10]})


def test_strip_triangles_alternate():
    assert D.strip_triangles(5) == [(0, 1, 2), (2, 1, 3), (2, 3, 4)]


def test_export_glb_with_weapon(tmp_path):
    from gbox import characters as C
    body = synthetic_model()
    page = D.page_encode(np.full((256, 256, 3), 128, np.uint8))
    bank = D.build_table([D.pad32(D.lz_compress(body)), page, page])
    costume = D.build_table([bank, b"SOSB", b"", b"", b"", b"", b"", b"", b""])
    wmodel = synthetic_model()                                          # any model works as a weapon here
    weapon = D.build_table([D.pad32(D.lz_compress(wmodel)), page])
    entries = [b""] * D.GROUP
    entries[0], entries[5] = costume, weapon
    human = D.build_olnk(entries)
    r = D.export(human, 0, 0, tmp_path / "f.glb", "f")
    st = C.model_stats(r["glb"])
    assert st["rig"]["skinned"] and st["textures"] == 3 and st["triangles"] > 0
    assert r["weapon"]["entry"] == 5 and "r_hand" in r["weapon"]["attached_to"]
    names = st["rig"]["joint_names"]
    assert all(n in names for n in r["roles"].values()) and len(r["roles"]) == 18


# ---------------------------------------------------------------- the writer

def _donor_prims(stock: bytes):
    """A two-triangle donor already 'fitted' (library frame), bound to the chest and the hip."""
    pos = np.array([[0, 0.2, 0], [0.1, 0.2, 0], [0, 0.3, 0], [0.1, 0.3, 0]], float)
    tris = np.array([[0, 1, 2], [1, 3, 2]])
    J = np.array([[1, 11, 0, 0], [1, 0, 0, 0], [1, 0, 0, 0], [1, 11, 0, 0]])
    Wt = np.array([[0.75, 0.25, 0, 0], [1, 0, 0, 0], [1, 0, 0, 0], [0.5, 0.5, 0, 0]])
    nrm = np.tile([0, 0, 1.0], (4, 1))
    return [{"pos": pos, "nrm": nrm, "uv": np.array([[0, 0], [1, 0], [0, 1], [1, 1]], float), "tris": tris,
             "J": J, "W": Wt, "tex": np.full((8, 8, 4), 200, np.uint8), "color": (255, 255, 255, 255)}]


def test_encode_model_round_trip_and_tail():
    stock = synthetic_model()
    prims = _donor_prims(stock)
    at = W.atlas(prims, 1)
    for p in prims:
        p["_page"] = 1
        p["_uv"] = [W.map_uv(p["uv"][t], at["slots"][p["_texkey"]]) for t in p["tris"]]
    enc = W.encode_model(stock, prims, [1])
    new = enc["model"]
    assert len(new) == len(stock)
    m0, m1 = D.parse_model(stock), D.parse_model(new)
    assert new[m0["strips_end"]:] == stock[m0["strips_end"]:]                  # tail kept in place
    assert [b["parent"] for b in m1["bones"]] == [b["parent"] for b in m0["bones"]]
    assert [b["angles"] for b in m1["bones"]] == [b["angles"] for b in m0["bones"]]
    sk = D.skin(m1)
    got = sk["positions"] @ D.FRAME.T                                         # back to the library frame
    want = prims[0]["pos"]
    # within the weight quantisation the engine allows (the w word also carries the slot and the add flag)
    assert all(np.abs(got - w).sum(1).min() < 1e-3 for w in want)
    tris = [(s["pos"][a], s["pos"][b], s["pos"][c]) for sec in m1["sections"] for s in sec
            for a, b, c in D.strip_triangles(len(s["pos"]))]
    assert len(tris) == 2 and all(s["material"] == 0x31 for sec in m1["sections"] for s in sec)
    out_game = D.FRAME @ np.array([0, 0, 1.0])               # the donor's outward normal, in the game's space
    for a, b, c in tris:                                     # the game reads strip winding in its own space
        pa, pb, pc = (sk["positions"][i] for i in (a, b, c))
        assert np.cross(pb - pa, pc - pa) @ out_game > 0
    nrm = [s for sec in m1["sections"] for s in sec][0]["nrm"]
    assert (sk["normals"][nrm] @ out_game < 0).all()        # stored inward, like the stock rows
    assert enc["bones_used"] == [1, 11]


# ---------------------------------------------------------------- the engine's skinning maths (0x8c03cea0)

def _wrow(p, wbits):
    return struct.pack("<3fI", *np.asarray(p, np.float32), wbits)


def _bone(stores, adds, pos_rows, nrm_rows=()):
    raw = b"".join(pos_rows) + b"".join(nrm_rows)
    return {"index": 0, "record": bytes(32), "stores": stores, "adds": adds, "positions": stores + adds,
            "normals": len(nrm_rows), "raw": raw}


def test_engine_skin_follows_the_machine_code():
    """0x8c03c920: the store run goes to consecutive slots from the FIRST row's slot (later rows' slot bits are not
    read), adds go to their own slot, and ftrv uses the whole row so w scales the translation. 0x8c03cba0: normal rows
    store consecutively until the first row with bit 15 set, then everything adds; translation cleared."""
    one = 0x3F800000
    half = 0x3F000000
    b0 = _bone(2, 0, [_wrow((1, 0, 0), one | 0), _wrow((0, 1, 0), one | 3)],          # slot bits 3 are ignored
               [_wrow((0, 0, 1), one | 0), _wrow((0, 1, 0), one | 1), _wrow((1, 0, 0), one | D.ADD_FLAG | 0)])
    b1 = _bone(0, 2, [_wrow((0.5, 0, 0), half | D.ADD_FLAG | 1), _wrow((0, 0, 0), one | D.ADD_FLAG | 3)])
    empty = {"index": 2, "record": bytes(32), "stores": 0, "adds": 0, "positions": 0, "normals": 1,
             "raw": _wrow((9, 9, 9), one | 2)}                         # no positions: the engine skips its normals
    model = {"bones": [b0, b1, empty], "counts": (4, 3)}
    M0 = np.eye(4)
    M0[:3, 3] = (10, 0, 0)
    M1 = np.eye(4)
    M1[:3, :3] = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]                     # 90 degrees about Z
    M1[:3, 3] = (0, 5, 0)
    e = D.engine_skin(model, [M0, M1, np.eye(4)])
    P, N = e["positions"], e["normals"]
    assert np.allclose(P[0], (11, 0, 0))
    w1, w2 = D._w(one | 3), D._w(half | D.ADD_FLAG | 1)                 # the whole word is the 4th component
    assert np.allclose(P[1], np.array((0, 1, 0)) + w1 * M0[:3, 3] + M1[:3, :3] @ (0.5, 0, 0) + w2 * M1[:3, 3])
    assert np.isnan(P[2]).all()                                         # nothing stores slot 2
    assert np.isnan(P[3]).all() and e["stale_adds"] == 1                # the add into slot 3 reads stale memory
    assert np.allclose(N[0], (1, 0, 1)) and np.allclose(N[1], (0, 1, 0)) and np.isnan(N[2]).all()
    assert D.slot_counts(model) == (4, 2)


def _posed(bones, seed, amp=0.7):
    rng = np.random.default_rng(seed)
    out = []
    for b in bones:
        a = rng.normal(0, amp, 3)
        X = np.eye(4)
        X[:3, :3] = D._rot(2, a[2]) @ D._rot(1, a[1]) @ D._rot(0, a[0])
        L = D.bone_local(b) @ X
        out.append(out[b["parent"]] @ L if b["parent"] >= 0 else L)
    return out


def test_encoded_model_skins_like_linear_blend_in_any_pose():
    """The written rows run through the game's maths give linear blend skinning of the donor in the rest pose AND in
    random poses (premultiplied rows, consecutive store slots, flags), with every drawn slot stored first."""
    m0 = D.parse_model(synthetic_model())
    big = 130                                                           # a roomier stock: bone 0 gets 130 rows
    m0["bones"][0] = dict(m0["bones"][0], stores=big, adds=0, positions=big, normals=big,
                          raw=b"".join(_row((0, 0, 0), 1.0, i) for i in range(big)) * 2)
    m0["bones"][0].pop("wbits")
    stock = D.pack_model(m0)
    rng = np.random.default_rng(5)
    k = 14
    pos = rng.uniform(-0.3, 0.3, (k, 3))
    bones = [1, 2, 4, 5, 11, 12, 18]
    J = np.array([rng.choice(bones, 4, replace=False) for _ in range(k)])
    Wt = rng.dirichlet(np.ones(4) * 0.8, k)
    Wt[0] = (1, 0, 0, 0)
    tris = np.array([(i, i + 1, i + 2) for i in range(k - 2)])
    prim = {"pos": pos, "nrm": np.tile([0, 0, 1.0], (k, 1)), "uv": rng.random((k, 2)), "tris": tris, "J": J, "W": Wt,
            "tex": np.full((8, 8, 3), 90, np.uint8), "_page": 1}
    prim["_uv"] = [prim["uv"][t] for t in tris]
    enc = W.encode_model(stock, [prim], [1])
    m = D.parse_model(enc["model"])
    for b in m["bones"]:                                                # one consecutive store run per bone
        if b["stores"]:
            assert (b["slot"][:b["stores"]] == b["slot"][0] + np.arange(b["stores"])).all()
            assert not (b["wbits"][:b["stores"]] & D.ADD_FLAG).any()
        assert (b["wbits"][b["stores"]:b["positions"]] & D.ADD_FLAG).all()
    rest = D.bone_world(m["bones"])
    e = D.engine_skin(m, rest)
    assert e["stale_adds"] == 0
    drawn = sorted({int(i) for sec in m["sections"] for s in sec for i in s["pos"]})
    assert np.isfinite(e["positions"][drawn]).all() and max(drawn) < m["counts"][0]
    game = pos @ D.FRAME.T
    slot = [int(np.argmin(np.linalg.norm(e["positions"] - g, axis=1))) for g in game]
    assert np.allclose(e["positions"][slot], game, atol=1e-3)
    for seed in range(3):
        X = _posed(m["bones"], seed)
        got = D.engine_skin(m, X)["positions"][slot]
        want = np.array([sum(w * (X[j] @ np.linalg.inv(rest[j]) @ np.append(g, 1.0))[:3]
                             for j, w in zip(J[v], Wt[v]) if w > 1e-4) for v, g in enumerate(game)])
        assert np.abs(got - want).max() < 2e-3 * max(1.0, np.abs(want).max())
    # what the shipped v1 rows did instead: unweighted rows (R p + w t) summed over k influences
    v = int(np.argmax((Wt > 1e-4).sum(1)))
    v1 = sum((rest[j][:3, :3] @ (np.linalg.inv(rest[j]) @ np.append(game[v], 1.0))[:3]) + w * rest[j][:3, 3]
             for j, w in zip(J[v], Wt[v]) if w > 1e-4)
    assert np.linalg.norm(v1 - game[v]) > 0.05


def test_engine_light_follows_the_machine_code():
    """0x8c03c7c0 + 0x8c03c9ec: XMTRX = lights x bone rotation (4th column 0), each bone's 4 terms clamped at 0, then
    stored / added like the normals (a row lit from behind adds nothing)."""
    one = 0x3F800000
    half = 0x3F000000
    b0 = _bone(1, 0, [_wrow((0, 0, 0), one | 0)], [_wrow((0, 0, 0.5), half | 0)])
    b1 = _bone(0, 1, [_wrow((0, 0, 0), one | D.ADD_FLAG | 0)], [_wrow((0, 0, -0.5), half | D.ADD_FLAG | 0)])
    model = {"bones": [b0, b1], "counts": (1, 1)}
    R = np.eye(4)
    R[:3, :3] = [[1, 0, 0], [0, 0, -1], [0, 1, 0]]                    # 90 degrees about X: z -> -y
    I = D.engine_light(model, [np.eye(4), R], np.array([[0, 0, 1.0], [0, 1.0, 0]]))
    # bone 0: (0,0,.5) under light z -> .5, light y -> 0; bone 1: R (0,0,-.5) = (0,.5,0) -> light y .5, z clamped 0
    assert np.allclose(I[0], (0.5, 0.5, 0, 0))


def test_written_normals_light_like_the_surface():
    """Donor normals that disagree with the donor's own faces (the SM64DS library entries) are replaced by the
    smooth geometric normal; the written rows, lit with the engine's maths, light each corner as its surface faces."""
    m0 = D.parse_model(synthetic_model())
    big = 130
    m0["bones"][0] = dict(m0["bones"][0], stores=big, adds=0, positions=big, normals=big,
                          raw=b"".join(_row((0, 0, 0), 1.0, i) for i in range(big)) * 2)
    m0["bones"][0].pop("wbits")
    stock = D.pack_model(m0)
    # a closed octahedron around the chest, counter-clockwise (outward) in the library frame
    v = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]], float) * 0.2
    centre = D.bone_world(m0["bones"])[1][:3, 3] @ D.FRAME.T
    tris = np.array([[0, 2, 4], [2, 1, 4], [1, 3, 4], [3, 0, 4], [2, 0, 5], [1, 2, 5], [3, 1, 5], [0, 3, 5]])
    garbage = -v + np.random.default_rng(2).normal(0, 0.02, (6, 3))     # inverted: they disagree with the faces
    prim = {"pos": v + centre, "nrm": garbage, "uv": np.zeros((6, 2)), "tris": tris, "J": np.tile([1, 0, 0, 0], (6, 1)),
            "W": np.tile([1.0, 0, 0, 0], (6, 1)), "tex": np.full((8, 8, 3), 90, np.uint8), "_page": 1}
    prim["_uv"] = [prim["uv"][t] for t in tris]
    out = W.corner_normals([prim])[0]
    assert np.allclose(out, v / 0.2, atol=1e-6)                         # the octahedron's own vertex directions
    m = D.parse_model(W.encode_model(stock, [prim], [1])["model"])
    world = D.bone_world(m["bones"])
    P = D.engine_skin(m, world)["positions"].astype(float)
    lights = np.array([[0, -1.0, 0], [1.0, 0, 0], [0, 0, -1.0]])        # the way each light travels (library frame)
    I = D.engine_light(m, world, lights @ D.FRAME.T)
    for sec in m["sections"]:
        for s in sec:
            for p, n in zip(s["pos"], s["nrm"]):
                outward = (P[p] @ D.FRAME.T - centre) / 0.2               # game -> library frame
                want = np.maximum(-(lights @ outward), 0)
                assert np.allclose(I[n][:3], want, atol=2e-3)


def test_encode_budget_errors():
    stock = synthetic_model()
    many = _donor_prims(stock)[0]
    k = 40
    many = {**many, "pos": np.random.default_rng(1).random((k, 3)), "nrm": np.tile([0, 0, 1.0], (k, 1)),
            "uv": np.zeros((k, 2)), "tris": np.array([[i, i + 1, i + 2] for i in range(k - 2)]),
            "J": np.tile([1, 0, 0, 0], (k, 1)), "W": np.tile([1.0, 0, 0, 0], (k, 1)),
            "_page": 1}
    many["_uv"] = [np.zeros((3, 2))] * (k - 2)
    with pytest.raises(W.BudgetError):
        W.encode_model(stock, [many], [1])


def test_stripify_keeps_every_oriented_triangle():
    rng = np.random.default_rng(3)
    grid = [(r * 6 + c, r * 6 + c + 1, (r + 1) * 6 + c) for r in range(5) for c in range(5)] + \
           [(r * 6 + c + 1, (r + 1) * 6 + c + 1, (r + 1) * 6 + c) for r in range(5) for c in range(5)]
    rng.shuffle(grid)
    strips = W.stripify([tuple(t) for t in grid])
    got = set()
    for st in strips:
        for a, b, c in D.strip_triangles(len(st)):
            t = (st[a], st[b], st[c])
            i = t.index(min(t))
            got.add(t[i:] + t[:i])
    want = {t[t.index(min(t)):] + t[:t.index(min(t))] for t in grid}
    assert got == want and len(strips) < len(grid)


def test_atlas_spreads_pages_and_maps_uvs():
    prims = [{"tex": np.full((16, 16, 3), i * 40, np.uint8)} for i in range(5)]
    at = W.atlas(prims, 3)
    assert at["textures"] == 5 and len(at["images"]) == 3
    pages = [at["slots"][p["_texkey"]][0] for p in prims]
    assert sorted(set(pages)) == [0, 1, 2]
    slot = at["slots"][prims[0]["_texkey"]]
    uv = W.map_uv(np.array([[0, 0], [1, 1], [2.5, -0.5]]), slot)
    _p, x, y, w, h = slot
    assert (uv[:, 0] >= x / 256 - 1e-9).all() and (uv[:, 0] <= (x + w) / 256 + 1e-9).all()


def test_replace_entries_keeps_offsets():
    human = D.build_olnk([b"a" * 64, b"b" * 32, b"c" * 16])
    out = W.replace_entries(human, {1: b"B" * 20})
    assert len(out) == len(human) and D.olnk_layout(out)[2] == D.olnk_layout(human)[2]
    assert D.olnk(out) == [b"a" * 64, b"B" * 20, b"c" * 16]
    with pytest.raises(W.BudgetError):
        W.replace_entries(human, {2: b"x" * 17})


# ---------------------------------------------------------------- the random costume hook

def _synthetic_exe() -> bytes:
    size = (W.CAVE_B + 16) - W.BASE + 64
    exe = bytearray(b"\xAA" * size)
    o = W.LOADER_SITE - W.BASE
    exe[o:o + 4] = W.STOCK_SITE
    for cave, n in ((W.CAVE_A, 24), (W.CAVE_B, 16)):
        exe[cave - W.BASE:cave - W.BASE + n] = W.NOP * (n // 2)
    return bytes(exe)


def test_random_costume_hook_assembles_and_runs():
    exe = W.apply_random_costume(_synthetic_exe())
    assert W.verify_random_patch(exe)["patched"]
    # the site branches into cave A with a nop in the delay slot
    assert exe[W.LOADER_SITE - W.BASE + 2:W.LOADER_SITE - W.BASE + 4] == W.NOP
    for tcnt in (0, 1, 0x100, 0x101, 0x10000, 0x12345678, 0xFFFFFFFF):
        bit = (tcnt ^ (tcnt >> 8) ^ (tcnt >> 16)) & 1
        assert W.simulate_random_patch(exe, 0, tcnt) == bit
        assert W.simulate_random_patch(exe, 1, tcnt) == bit
        assert W.simulate_random_patch(exe, 2, tcnt) == 2 and W.simulate_random_patch(exe, 3, tcnt) == 3
    with pytest.raises(ValueError):
        W.apply_random_costume(exe)                                    # the caves are no longer free
    with pytest.raises(ValueError):
        W.patch_random_costume(_synthetic_exe())                       # not the verified executable


# ---------------------------------------------------------------- CHD -> GDI

def _raw_sector(lba: int, fill: int) -> bytes:
    m, rest = divmod(lba + 150, 75 * 60)
    s, f = divmod(rest, 75)
    bcd = lambda v: ((v // 10) << 4) | (v % 10)                       # noqa: E731
    return b"\x00" + b"\xff" * 10 + b"\x00" + bytes((bcd(m), bcd(s), bcd(f), 1)) + bytes([fill]) * 2048 + bytes(288)


def make_gd_chd_v4(track_frames=(2, 3, 4)) -> tuple[bytes, list[bytes]]:
    """A v4 CHD (uncompressed hunks of 4 frames) with a MODE1_RAW / AUDIO / MODE1_RAW GD-ROM layout."""
    frame = 2448
    lbas = [0, track_frames[0], 45000]
    tracks = []
    for t, n in enumerate(track_frames):
        if t == 1:
            tracks.append([bytes([(k * 7 + i) & 0xFF for i in range(2352)]) for k in range(n)])
        else:
            tracks.append([_raw_sector(lbas[t] + k, 0x10 * (t + 1) + k) for k in range(n)])
    frames = []
    for t, secs in enumerate(tracks):
        for s in secs:
            if t == 1:                                                  # audio is stored big endian in a CHD
                a = bytearray(s)
                a[0::2], a[1::2] = s[1::2], s[0::2]
                s = bytes(a)
            frames.append(s + bytes(96))
        frames += [bytes(frame)] * ((-len(secs)) % 4)
    hunks = [b"".join(frames[i:i + 4]) for i in range(0, len(frames), 4)]
    metas = []
    types = ["MODE1_RAW", "AUDIO", "MODE1_RAW"]
    for t, n in enumerate(track_frames):
        metas.append(f"TRACK:{t + 1} TYPE:{types[t]} SUBTYPE:NONE FRAMES:{n} PREGAP:0 PGTYPE:MODE1 PGSUB:RW "
                     f"POSTGAP:0".encode() + b"\0")
    hdr_len, map_len = 108, 16 * len(hunks)
    data_off = hdr_len + map_len
    meta_off = data_off + sum(len(h) for h in hunks)
    blob, offs = b"", []
    for i, m in enumerate(metas):
        offs.append(meta_off + len(blob))
        entry_len = 16 + len(m)
        nxt = meta_off + len(blob) + entry_len if i < len(metas) - 1 else 0
        blob += b"CHT2" + bytes([0]) + len(m).to_bytes(3, "big") + struct.pack(">Q", nxt) + m
    header = bytearray(hdr_len)
    header[:8] = b"MComprHD"
    struct.pack_into(">IIIII", header, 8, hdr_len, 4, 0, 0, len(hunks))
    struct.pack_into(">QQI", header, 28, len(hunks) * 4 * frame, offs[0], 4 * frame)
    mp = b"".join(struct.pack(">QIHBB", data_off + i * 4 * frame, 0, (4 * frame) & 0xFFFF, (4 * frame) >> 16, 2)
                  for i in range(len(hunks)))
    return bytes(header) + mp + b"".join(hunks) + blob, [b"".join(t) for t in tracks]


def test_chd_write_gdi_gd_layout(tmp_path):
    data, tracks = make_gd_chd_v4()
    src = tmp_path / "disc.chd"
    src.write_bytes(data)
    lay = chd.track_layout(src)
    assert [t["first_frame"] for t in lay] == [0, 4, 8] and [t["type"] for t in lay] == ["MODE1_RAW", "AUDIO", "MODE1_RAW"]
    gdi = chd.write_gdi(src, tmp_path / "out")
    lines = gdi.read_text().split("\n")
    assert lines[0] == "3" and lines[1].startswith("1 0 4 2352") and lines[2].startswith("2 2 0 2352")
    assert lines[3].startswith("3 45000 4 2352")
    assert (tmp_path / "out" / "disc01.bin").read_bytes() == tracks[0]
    assert (tmp_path / "out" / "disc02.raw").read_bytes() == tracks[1]          # little endian again
    assert (tmp_path / "out" / "disc03.bin").read_bytes() == tracks[2]
    assert not list((tmp_path / "out").glob("*.part"))


def test_chd_write_gdi_refuses_a_misplaced_track(tmp_path):
    data, _ = make_gd_chd_v4()
    bad = bytearray(data)
    i = bad.find(_raw_sector(45000, 0x30)[:16])
    bad[i + 12] = 0x11                                                   # the first HD sector now addresses elsewhere
    (tmp_path / "bad.chd").write_bytes(bytes(bad))
    with pytest.raises(chd.ChdError):
        chd.write_gdi(tmp_path / "bad.chd", tmp_path / "o")


# ---------------------------------------------------------------- plans and registration

def test_fighter_slots_and_plan():
    assert W.fighter_slot("fighter:MIT") == ("MIT", None)
    assert W.fighter_slot("Sophitia:2") == ("SOP", 2)
    assert W.fighter_slot("hwang") == ("HWA", None)
    for bad in ("player", "", "MIT:9", "nobody"):
        with pytest.raises(ValueError):
            W.fighter_slot(bad)
    entries = [b""] * (21 * D.GROUP)
    entries[0] = entries[1] = entries[40] = entries[41] = entries[42] = entries[43] = b"x"
    human = D.build_olnk(entries)
    plan = W.plan_costumes(human, {"MIT": ["sonic", "sm64ds_mario"], "VOL": ["sa2_chaos_0", "sm64ds_koopa_troopa"]})
    assert [(r["fighter"], r["costume"], r["character"]) for r in plan] == [
        ("MIT", 0, "sonic"), ("MIT", 1, "sm64ds_mario"), ("VOL", 0, "sa2_chaos_0"),
        ("VOL", 1, "sm64ds_koopa_troopa"), ("VOL", 2, "sa2_chaos_0"), ("VOL", 3, "sm64ds_koopa_troopa")]
    rows = W._plan_from_pairs(human, [("fighter:MIT", "a"), ("fighter:VOL:3", "b")])
    assert [(r["entry"], r["character"]) for r in rows] == [(0, "a"), (1, "a"), (43, "b")]
    with pytest.raises(ValueError):
        W._plan_from_pairs(human, [("fighter:MIT", "a"), ("fighter:MIT:0", "b")])
    # the Sonic vs Mario plan: SA2 on even costumes, SM64DS on odd ones, every fighter
    assert set(W.SONIC_VS_MARIO) == {k for _g, k, _n, _a in D.FIGHTERS}
    for donors in W.SONIC_VS_MARIO.values():
        assert [W.franchise(d) for d in donors] == [("SA2", "SM64DS")[i % 2] for i in range(len(donors))]


def test_registration():
    from gbox import characters as C, char_coverage, cast_swap, replacement_readiness as R
    pick = lambda t, p: next((n for n, test, _r, _run in C.DEDICATED if test(t, p)), None)     # noqa: E731
    assert pick("soulcalibur (usa)", "dreamcast") == "soulcalibur"
    assert pick("soul calibur v1.000", "dreamcast") == "soulcalibur"
    assert pick("soulcalibur ii", "gamecube") != "soulcalibur" and pick("soulcalibur ii", "dreamcast") is None
    roster = D.roster()
    assert len(roster) == 19 and len({r["slug"] for r in roster}) == 19
    assert C.reader_version("soulcalibur") == D.READER_VERSION
    w = char_coverage.writer_for({"game_id": GID, "title": "SoulCalibur (USA)", "platform": "dreamcast"})
    assert w and w["writer"] == "gbox.soulcalibur_swap" and w["routed"]
    slots = char_coverage.cast_slots({"game_id": GID, "title": "SoulCalibur (USA)", "platform": "dreamcast"})
    assert {s["slot"] for s in slots} >= {f"fighter:{k}" for _g, k, _n, _a in D.FIGHTERS}
    assert "gbox.soulcalibur_swap" in cast_swap.BUILDERS and "gbox.soulcalibur_swap" in cast_swap.STRATEGIES
    assert "gbox.soulcalibur_swap" in R.SPECS
    assert W.REQUIRED_ROLES <= set(D.CORE_ROLES) | {"head"}


# ---------------------------------------------------------------- the owned disc

def _owned_human() -> bytes | None:
    for c in (os.environ.get("GBOX_SC_HUMAN"), "D:/gBox/research/soulcalibur/disc/HUMAN.DAT"):
        try:
            if c and Path(c).is_file():
                return Path(c).read_bytes()
        except OSError:
            continue
    return None


@pytest.mark.skipif(_owned_human() is None, reason="owned SoulCalibur HUMAN.DAT not on this node")
def test_owned_disc_every_fighter(tmp_path):
    human = _owned_human()
    assert hashlib.sha256(human).hexdigest().startswith("4630923ce5b82493")
    cov = D.coverage(human)
    assert len(cov["fighters"]) == 19 and cov["costumes"] == 45 and cov["weapons"] >= 50
    for row in cov["fighters"]:
        assert all(c["roles"] == 18 for c in row["costumes"]), row["fighter"]
    r = D.export(human, 0, 0, tmp_path / "mit.glb", "mit")
    assert r["triangles"] > 3000 and len(r["roles"]) == 18 and r["weapon"]["entry"] == 5
    entries = D.olnk(human)
    stock = D.costume_parts(entries[0])["model"]
    assert len(D.lz_compress(stock)) < len(D.costume_parts(entries[0])["bank"][0]) * 1.02


@pytest.mark.skipif(_owned_human() is None, reason="owned SoulCalibur HUMAN.DAT not on this node")
def test_owned_disc_round_trip_identity():
    """Read every stock costume and write it back unchanged: the game must see the same bytes. The model layout
    (pack_model), the texture bank and costume tables, and the LZ stream all round-trip exactly."""
    human = _owned_human()
    entries = D.olnk(human)
    n = 0
    for g, _key, name, _a in D.FIGHTERS:
        for c in D.costumes_of(entries, g):
            entry = entries[g * D.GROUP + c]
            cp = D.costume_parts(entry)
            m = D.parse_model(cp["model"])
            assert D.pack_model(m) == cp["model"], (name, c)
            assert D.pack_model(m, tail_at=m["strips_end"], size=len(cp["model"])) == cp["model"]
            assert D.slot_counts(m) == m["counts"], (name, c)
            assert D.engine_skin(m, D.bone_world(m["bones"]))["stale_adds"] == 0, (name, c)
            assert D.build_table(cp["bank"]) == cp["table"][0] and D.build_table(cp["table"]) == entry
            packed = D.lz_compress(cp["model"])
            assert D.lz_decompress(packed) == cp["model"] and len(D.pad32(packed)) <= len(cp["bank"][0]) * 1.05
            n += 1
    assert n == 45
    assert W.replace_entries(human, {}) == human


@pytest.mark.skipif(_owned_human() is None, reason="owned SoulCalibur HUMAN.DAT not on this node")
@pytest.mark.parametrize("fighter,costume", [("MIT", 0), ("TAK", 0), ("IVY", 0), ("NIG", 0), ("NIG", 1)])
def test_owned_disc_stock_geometry_through_the_writer_skins_like_stock(fighter, costume):
    """A stock costume's own geometry (read with its influences) written back through the donor encoder: the game's
    maths on both, in random poses, give the same vertices (within the weight rounding the format allows)."""
    human = _owned_human()
    entries = D.olnk(human)
    g = W.group_of(fighter)
    stock = D.costume_parts(entries[g * D.GROUP + costume])["model"]
    m0 = D.parse_model(stock)
    sk0 = D.skin(m0)
    prims = []
    for mat, d in D.mesh_arrays(m0, sk0).items():
        if len(d["tris"]):
            prims.append({"pos": d["pos"], "nrm": d["nrm"], "uv": d["uv"], "tris": d["tris"], "J": d["joints"],
                          "W": d["weights"], "_page": mat & 3, "_uv": [d["uv"][t] for t in d["tris"]]})
    m1 = D.parse_model(W.encode_model(stock, prims, [0, 1, 2, 3])["model"])
    rest = D.bone_world(m0["bones"])
    r0 = D.engine_skin(m0, rest)["positions"].astype(float)
    e1 = D.engine_skin(m1, rest)
    r1 = e1["positions"].astype(float)
    assert e1["stale_adds"] == 0 and np.isfinite(r1).all()
    sk1 = D.skin(m1)
    pairs = []
    for s in range(len(r1)):
        near = np.nonzero(np.linalg.norm(r0 - r1[s], axis=1) < 2e-3)[0]
        assert len(near), s

        def diff(t):
            a, b = sk0["influences"][t], sk1["influences"][s]
            return sum(abs(a.get(k, 0) - b.get(k, 0)) for k in set(a) | set(b))
        t = min(near, key=diff)
        if diff(t) < 0.05:                       # stock vertices with more than 4 influences are cut to 4 by the reader
            pairs.append((s, t))
    assert len(pairs) > 0.97 * len(r1)
    a, b = np.array(pairs).T
    for seed in range(2):
        X = _posed(m0["bones"], seed + 10 * costume)
        p0 = D.engine_skin(m0, X)["positions"][b]
        p1 = D.engine_skin(m1, X)["positions"][a]
        assert np.abs(p1 - p0).max() < 0.01, (fighter, costume, seed)   # metres; a 1.8 m fighter
