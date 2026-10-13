"""Soul Calibur II (GameCube) reader / writer on synthetic data (gbox.sc2_vmg, gbox.soulcalibur2,
gbox.soulcalibur2_swap). SC2_IMAGE=<owned .gcz / .iso> adds the owned-disc check."""
from __future__ import annotations

import hashlib
import json
import os
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import sc2_vmg as V
from gbox import soulcalibur2 as S
from gbox import soulcalibur2_swap as W

# the 21 body bones as Mitsurugi's model has them: (name, parent, translation, euler in turns)
BODY = [("MUNE1", -1, (0, 0, 0), (0, 0, 0.25)), ("MUNE2", 0, (0.13, 0, 0), (0, 0, 0)),
        ("KUBI", 1, (0.24, 0, 0), (0, 0, 0)), ("ATAMA", 2, (0.07, 0, 0), (0.25, 0, 0.25)),
        ("SAKOTSU_R", 1, (0.22, 0, -0.1), (-0.25, 0.2083, 0)), ("KATA_R", 4, (0.12, 0, 0), (-0.25, 0, 0.0417)),
        ("UDE_R", 5, (0.3, 0, 0), (0, 0, 0)), ("TE_R", 6, (0.23, 0, 0), (0.25, 0, 0)),
        ("SAKOTSU_L", 1, (0.22, 0, 0.1), (-0.25, -0.2083, 0)), ("KATA_L", 8, (0.12, 0, 0), (-0.25, 0, -0.0417)),
        ("UDE_L", 9, (0.3, 0, 0), (0, 0, 0)), ("TE_L", 10, (0.23, 0, 0), (0.25, 0, 0)),
        ("KOSHI", -1, (0, 0, 0), (0, 0, -0.25)), ("MOMO_R", 12, (0.16, 0, -0.1), (0, 0, 0)),
        ("HIZA_R", 13, (0.44, 0, 0), (0, 0, 0)), ("ASHI_R", 14, (0.42, 0, 0), (0, 0, 0)),
        ("TSUMASAKI_R", 15, (0.1, -0.13, 0), (0, 0, -0.25)), ("MOMO_L", 12, (0.16, 0, 0.1), (0, 0, 0)),
        ("HIZA_L", 17, (0.44, 0, 0), (0, 0, 0)), ("ASHI_L", 18, (0.42, 0, 0), (0, 0, 0)),
        ("TSUMASAKI_L", 19, (0.1, -0.13, 0), (0, 0, -0.25))]


def bare_template() -> bytes:
    """A VMG with the body skeleton, one material / texture / stage and no meshes (the shape of the disc's)."""
    names = b"".join(n.encode() + b"\0" for n, *_ in BODY)
    stages = struct.pack(">HH8f", 1, 0x24, 1.0, 1.0, 0, 0, 0, 0, 0, 0) + b"\xff\xff\xff\xff"
    o = 0x4C
    lay = {"list": o}
    lay["stages"] = o
    o += len(stages)
    lay["colours_obj"] = o
    o += 8
    o = (o + 15) // 16 * 16
    lay["nodes"] = o
    o += 0x150
    lay["material"] = o
    o += 0x50
    lay["bones"] = o
    o += 0x40 * len(BODY)
    o = (o + 31) // 32 * 32
    lay["colour"] = o
    o += 32
    lay["vgt"] = o
    tex = np.zeros((8, 8, 4), np.uint8)
    tex[..., 0], tex[..., 3] = 200, 255
    vgt, trec = V._texture_records(tex, None, o)
    o += len(vgt)
    lay["tail"] = o
    o += 0x28
    lay["names"] = o
    o += len(names)
    out = bytearray((o + 31) // 32 * 32)
    out[0:8] = b"VMG." + bytes([3, 0x10, 13, 0])
    struct.pack_into(">8H", out, 8, 1, 1, 0, 0, 0, len(BODY), 1, 0)
    struct.pack_into(">13I", out, 0x18, lay["vgt"], lay["material"], lay["stages"], lay["nodes"], lay["colours_obj"],
                     lay["list"], lay["list"], lay["list"], 0, 0, lay["bones"], lay["names"], lay["tail"])
    out[lay["stages"]:lay["stages"] + len(stages)] = stages
    struct.pack_into(">II", out, lay["colours_obj"], 0, lay["colour"])
    out[lay["nodes"]:lay["nodes"] + 0x150] = V.NODE0
    struct.pack_into(">8I", out, lay["material"], 1, 0, lay["vgt"] + trec, 0, 0, lay["stages"], 0, 0)
    struct.pack_into(">12f", out, lay["material"] + 0x20, 0, 0, 0, 0, 1, 1, 1, 1, 0, 0, 0, 0)
    no = lay["names"]
    for i, (n, par, t, e) in enumerate(BODY):
        r = lay["bones"] + 0x40 * i
        struct.pack_into(">4f3ff3fI3f", out, r, 0, 0, 0, 1, *t, 1.0, *e, no, 1, 1, 1)
        out[r + 0x3C:r + 0x40] = bytes([0, 0xFF if par < 0 else par, i, 0])
        no += len(n) + 1
    out[lay["colour"]:lay["colour"] + 4] = b"\xff\xff\xff\xff"
    out[lay["vgt"]:lay["vgt"] + len(vgt)] = vgt
    out[lay["names"]:lay["names"] + len(names)] = names
    return bytes(out)


def boxes(v: V.Vmg, size=0.05, scale=1.0):
    """A box per body bone at its bind position (P, N, UV, B, F counter-clockwise from outside)."""
    W_ = V.bind_world(v, V.model_root(v))
    P, N, UV, B, F = [], [], [], [], []
    for b in v.bones:
        c = W_[b.index][:3, 3]
        for ax in range(3):
            for sgn in (-1, 1):
                n = np.zeros(3)
                n[ax] = sgn
                u, w = np.eye(3)[(ax + 1) % 3], np.eye(3)[(ax + 2) % 3]
                if sgn < 0:
                    u, w = w, u
                base = len(P)
                for du, dw in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                    P.append(c + (n + du * u + dw * w) * size * scale)
                    N.append(n)
                    UV.append(((du + 1) / 2, (dw + 1) / 2))
                    B.append(b.index)
                F += [(base, base + 1, base + 2), (base, base + 2, base + 3)]
    return np.array(P), np.array(N, float), np.array(UV, float), np.array(B), np.array(F)


@pytest.fixture(scope="module")
def stock() -> bytes:
    """A 'stock' costume model: boxes on every body bone, encoded on the bare skeleton."""
    bare = V.parse(bare_template())
    P, N, UV, B, F = boxes(bare)
    atlas = np.zeros((32, 32, 4), np.uint8)
    atlas[..., 1], atlas[..., 3] = 180, 255
    return V.encode(bare, P, N, UV, B, F, atlas)


# ------------------------------------------------------------------------------------------------ format

def test_bind_world_euler_turns_and_skeleton_frame():
    v = V.parse(bare_template())
    W_ = V.bind_world(v, np.array([0, 1.15, 0]))
    idx = {b.name: b.index for b in v.bones}
    assert np.allclose(W_[idx["MUNE2"]][:3, 3], [0, 1.28, 0], atol=1e-6)        # up the spine
    assert np.allclose(W_[idx["HIZA_L"]][:3, 3], [0.1, 0.55, 0], atol=1e-6)     # left knee at +X
    assert np.allclose(W_[idx["TE_R"]][:3, 3], [-0.746, 1.531, 0], atol=2e-3)   # T-pose right hand at -X
    assert np.allclose(W_[idx["MUNE2"]][:3, 0], [0, 1, 0], atol=1e-6)          # bones point along their +X


def test_encode_parse_decode_round_trip(stock):
    v = V.parse(stock)
    assert v.counts["list0"] == 1 and v.counts["skin"] == 1 and len(v.bones) == len(BODY)
    assert [b.name for b in v.bones] == [n for n, *_ in BODY]
    prims, W_, names = V.decode(v)
    bare = V.parse(bare_template())
    P, N, UV, B, F = boxes(bare)
    assert sum(len(p["tris"]) for p in prims) == len(F)
    got = np.concatenate([p["pos"] for p in prims])
    assert np.abs(np.sort(got, 0) - np.sort(P[F.reshape(-1)], 0)).max() < 2e-3      # skin records -> world
    assert prims[0]["image"] is not None and prims[0]["image"][..., 1].mean() > 150
    assert np.allclose(V.skin_root(v), V.model_root(bare), atol=1e-3)
    t = V.vgt_textures(v.data, v.ptrs["vgt"])[0]
    assert (t["w"], t["h"], t["fmt"]) == (32, 32, 14) and t["data2"] == t["data"]   # no 2P image given: shared


def test_written_faces_are_gx_clockwise(stock):
    v = V.parse(stock)
    prims, _W, _n = V.decode(v)
    P = prims[0]["pos"][prims[0]["tris"]]
    n = prims[0]["nrm"][prims[0]["tris"]].mean(1)
    cr = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    assert ((cr * n).sum(1) < 0).mean() > 0.95


def test_skin_records_variable_group_and_terminator():
    rec = lambda b, w, last=0: struct.pack(">7hBB", 8192, 0, 0, w, 16384, 0, 0, last, b)
    data = bytearray(0x200)
    o = 0x40
    body = rec(1, 8192) + rec(2, 4096) + rec(3, 4096) + b"".join(rec(4 + k, 2048, 1 if k == 3 else 0)
                                                                  for k in range(4))
    body += b"".join(rec(9 + k, 1638) for k in range(5)) + b"\xff" * 16
    data[o:o + len(body)] = body
    v = V.Vmg(bytes(data), {}, {})
    out = V.skin_records(v, {"records": o, "counts": (1, 1, 0, 2)})
    assert [len(x) for x in out] == [1, 2, 4, 5]
    assert out[3][0][0] == 9 and abs(sum(r[1] for r in out[3]) - 1.0) < 1e-3


def test_display_list_strips_keep_their_winding():
    dl = struct.pack(">BH", 0x98, 4) + b"".join(struct.pack(">HHBH", i, i, 0, i) for i in range(4))
    tris = V.triangles(V.display_list(dl + bytes(32), 0, 32, (3, 3, 2, 3)))
    assert [tuple(c[0] for c in t) for t in tris] == [(0, 1, 2), (2, 1, 3)]


def test_encode_rejects_too_many_vertices(stock):
    v = V.parse(stock)
    with pytest.raises(ValueError):
        V.encode(v, np.zeros((70000, 3)), np.zeros((70000, 3)), np.zeros((70000, 2)), np.zeros(70000, int),
                 np.zeros((1, 3), int), np.zeros((8, 8, 4), np.uint8))


# ------------------------------------------------------------------------------------------------ archive / disc

def olk(entries: list[bytes]) -> bytes:
    n = len(entries)
    start = (16 * (n + 2) + 0x7FF) // 0x800 * 0x800
    recs, body = [], bytearray()
    for e in entries:
        recs.append((len(body), len(e)))
        body += e + bytes((-len(e)) % 0x800)
    head = bytearray(start)
    struct.pack_into("<I4sII", head, 0, n, b"olnk", 0x800, 0)
    struct.pack_into("<IIII", head, 16, start, len(body), 0, 0)
    for i, (o, s) in enumerate(recs):
        struct.pack_into("<IIII", head, 32 + 16 * i, o, s, 0, 0)
    return bytes(head) + bytes(body)


def costume_package(vmg: bytes, room: int = 0) -> bytes:
    out = bytearray(struct.pack(">I", 14) + struct.pack(">14I", 0x80, *([0] * 13)))
    out += bytes(0x80 - len(out)) + vmg + bytes(room)
    return bytes(out)


def dol(costumes: int = 2, base: int = 2, extra: bool = True, stock: bool = True) -> bytes:
    text_addr, data_addr = 0x800A2000, 0x80275A00
    text = bytearray(0x200)
    o = S.COSTUME_LOAD - text_addr
    text[o:o + len(W.RANDOM_STOCK)] = W.RANDOM_STOCK if stock else bytes(len(W.RANDOM_STOCK))
    data = bytearray(0x2100)
    fid = 1                                                              # Mitsurugi
    struct.pack_into(">I", data, S.CHAR_TABLE + fid * 0xF8 - data_addr, 1)
    struct.pack_into(">h", data, S.CHAR_TABLE + fid * 0xF8 + 0x8A - data_addr, costumes)
    for f in range(33):
        struct.pack_into(">h", data, S.BASE_TABLE + 2 * f - data_addr, base if f == fid else -1)
    data[S.EXTRA_TABLE + fid - data_addr] = 1 if extra else 0
    hdr = bytearray(0x100)
    struct.pack_into(">I", hdr, 0x00, 0x100)
    struct.pack_into(">I", hdr, 0x48, text_addr)
    struct.pack_into(">I", hdr, 0x90, len(text))
    struct.pack_into(">I", hdr, 0x1C, 0x100 + len(text))
    struct.pack_into(">I", hdr, 0x64, data_addr)
    struct.pack_into(">I", hdr, 0xAC, len(data))
    struct.pack_into(">I", hdr, 0xE0, text_addr)
    return bytes(hdr + text + data)


def disc_image(path: Path, human: list[bytes], dol_bytes: bytes) -> Path:
    root = olk([olk([b"x" * 16]) for _ in range(4)] + [olk(human)])
    dol_off, fst_off, root_off = 0x2000, 0x1000, 0x10000
    names = b"root.olk\0"
    fst = struct.pack(">III", 1 << 24, 0, 2) + struct.pack(">III", 0, root_off, len(root)) + names
    img = bytearray(root_off + len(root))
    img[0:6] = S.DISC_ID.encode()
    img[0x20:0x2C] = b"SOULCALIBUR2"
    struct.pack_into(">III", img, 0x420, dol_off, fst_off, len(fst))
    img[fst_off:fst_off + len(fst)] = fst
    img[dol_off:dol_off + len(dol_bytes)] = dol_bytes
    img[root_off:] = root
    path.write_bytes(bytes(img))
    return path


@pytest.fixture()
def disc(tmp_path, stock):
    human = [b""] * 12
    for e in (2, 3, 10, 11):
        human[e] = costume_package(stock, room=0x4000)
    return disc_image(tmp_path / "sc2.iso", human, dol())


def test_olk_package_and_fighter_table(disc):
    with S.Disc(disc) as d:
        assert d.game_id == "GRSEAF" and len(d.groups) == 5 and len(d.human) == 12
        t = S.fighter_table(d.dol)
        assert list(t) == ["mitsurugi"]
        assert t["mitsurugi"]["entries"] == [[2, 10], [3, 11]]
        c = S.read_costume(d, "mitsurugi", 1)
        assert c.entry == 3 and len(c.vmg.bones) == len(BODY) and c.weapon is None
        assert W.random_patched(d) is False
    assert S.package(b"\x00\x00\x00\x02\x00\x00\x00\x0c\x00\x00\x00\x00abcd") == [(12, 4), (0, 0)]
    assert S.package(b"junk") is None


def test_reader_exports_a_rigged_textured_glb(disc, tmp_path):
    r = S.extract(disc, "mitsurugi", tmp_path / "m.glb", "Mitsurugi")
    assert r["roles"] == S.ROLE_BONES and len(r["roles"]) == 18
    gl = json.loads((tmp_path / "m.glb").read_bytes()[20:20 + struct.unpack_from("<I", (tmp_path / "m.glb")
                                                                              .read_bytes(), 12)[0]])
    assert len(gl["skins"][0]["joints"]) == len(BODY) and gl.get("images")
    assert r["triangles"] == 12 * len(BODY)


def test_dedicated_row_and_roster():
    from gbox import characters as C
    names = [n for n, test, _r, _run in C.DEDICATED if test("soul calibur ii (usa)", "gamecube")]
    assert names == ["soulcalibur2"]
    assert not [n for n, test, _r, _run in C.DEDICATED if test("soulcalibur iii", "ps2") and n == "soulcalibur2"]
    ros = S.roster()
    assert len(ros) == 24 and any(r["slug"] == "sc2_link" for r in ros)
    assert C.reader_version("soulcalibur2") == S.READER_VERSION


# ------------------------------------------------------------------------------------------------ writer

@pytest.fixture()
def donor(disc, tmp_path):
    big = V.parse(bare_template())
    P, N, UV, B, F = boxes(big, size=0.06, scale=1.3)
    atlas = np.zeros((16, 16, 4), np.uint8)
    atlas[..., 2], atlas[..., 3] = 220, 255
    vmg = V.encode(big, P, N, UV, B, F, atlas)
    c = S.Costume("donor", 0, 0, costume_package(vmg), S.package(costume_package(vmg)), V.parse(vmg))
    r = S.export(c, tmp_path / "donor.glb", "Donor")
    return W.load_donor("donor", r["path"], r["roles"], "Donor")


def test_slots_parse_and_plans():
    assert W.parse_slot("fighter:taki:2") == ("taki", 1) and W.parse_slot("player") == ("mitsurugi", None)
    assert W.is_slot("fighter:link") and W.is_slot("random") and not W.is_slot("fighter:nobody")
    assert len(W.keys_for("fighter:lizardman")) == 6 and W.keys_for("all")[0] == ("mitsurugi", 0)
    plan = W.plan_pairs([("fighter:taki:2", "a"), ("fighter:taki", "b"), ("", "c")])
    assert plan[("taki", 1)] == "a" and plan[("taki", 0)] == "b" and plan[("mitsurugi", 0)] == "c"
    sa2, ds = ["s1", "s2", "s3"], ["m1", "m2"]
    p = W.plan_random([sa2, ds], seed="x")
    assert len(p) == sum(v[1] for v in S.EXPECTED.values())
    for fid, key, _n, _a in S.FIGHTERS:
        got = [p[(key, c)] for c in range(S.EXPECTED[key][1])]
        if len(got) > 1:                                   # every multi-costume fighter shows both franchises
            assert {g[0] for g in got} == {"s", "m"}
    firsts = [p[(k, 0)][0] for _f, k, _n, _a in S.FIGHTERS]
    assert abs(firsts.count("s") - firsts.count("m")) <= 1  # half the roster starts with each pool
    assert W.plan_random([sa2, ds], seed="x") == p          # deterministic


def test_fit_costume_retargets_within_the_budget(donor, stock):
    v = V.parse(stock)
    f = W.fit_costume(donor, v, "mitsurugi", 0, len(stock))
    assert len(f.data) <= len(stock) and f.report["triangles"] > 0
    nv = V.parse(f.data)
    prims, _W, _n = V.decode(nv)
    hand = [b.index for b in nv.bones if b.name == "TE_R"][0]
    J = np.concatenate([p["J"][:, 0] for p in prims])
    assert (J == hand).any()                               # the donor's right hand rides TE_R (the weapon hand)
    with pytest.raises(ValueError):
        W.fit_costume(donor, v, "mitsurugi", 0, 1000)        # cannot fit 1000 bytes


def test_ground_feet_lifts_tall_shoes_out_of_the_floor():
    tgt = {"T": np.array([[0, 0.13, 0.0], [0, 1, 0]]), "jmap": {"l_foot": 0}, "ground": 0.0}
    prims = [{"pos": np.array([[0, 0.13, 0], [0, -0.3, 0.1]]), "J": np.array([[0, 0, 0, 0], [0, 0, 0, 0]])}]
    k = W.ground_feet(prims, tgt)
    assert k["l_foot"] == 0.5 and prims[0]["pos"][1, 1] > -0.1


def test_replace_child0_keeps_the_package_size(stock):
    pkg = costume_package(stock, room=0x100)
    new = W.replace_child0(pkg, stock[:len(stock) // 2])
    assert len(new) == len(pkg) and S.package(new) == S.package(pkg)
    with pytest.raises(ValueError):
        W.replace_child0(pkg, bytes(len(pkg)))


def test_build_image_writes_every_copy_patches_select_and_reads_back(disc, donor, tmp_path):
    rep = W.build_image(disc, tmp_path / "out", {("mitsurugi", 0): donor, ("mitsurugi", 1): donor},
                        random_select=True, image_name="sc2.iso")
    assert rep["entries"] == [2, 3, 10, 11] and rep["verify"]["ok"] and rep["random_select"]
    assert all(s["status"] == "built" for s in rep["slots"].values())
    with S.Disc(tmp_path / "out" / "sc2.iso") as d:
        assert W.random_patched(d)
        o = W.random_patch_site(d.dol)
        assert d.dol[o:o + 24] == W.RANDOM_PATCH
        assert d.entry(2) == d.entry(10)                       # Extra-mode copy gets the same body
    assert disc.read_bytes() != (tmp_path / "out" / "sc2.iso").read_bytes()
    with S.Disc(disc) as d:                                  # the source image is untouched
        assert not W.random_patched(d)
    rec = W.write_marker(tmp_path / "out", "201629ad498aba7b", "m", "sc2.iso", rep,
                         {("mitsurugi", 0): "donor"}, "test")
    assert rec["image"] == "sc2.iso" and rec["random_select"] and rec["writer"] == W.WRITER
    assert json.loads((tmp_path / "out" / ".gbox-mod.json").read_text())["cast"] == [["mitsurugi:1", "donor"]]


def test_random_patch_refuses_an_unknown_dol(tmp_path, stock):
    human = [b""] * 12
    human[2] = costume_package(stock)
    img = disc_image(tmp_path / "x.iso", human, dol(stock=False))
    with S.Disc(img) as d, pytest.raises(ValueError):
        W.random_patch_site(d.dol)


def test_registration_coverage_cast_swap_and_readiness():
    from gbox import cast_swap, char_coverage, replacement_readiness
    g = {"game_id": "201629ad498aba7b", "title": "Soul Calibur II (USA)", "platform": "gamecube"}
    w = char_coverage.writer_for(g)
    assert w and w["writer"] == W.WRITER and w["routed"]
    slots = char_coverage.cast_slots(g)
    assert any(s["slot"] == "fighter:link" for s in slots)
    assert cast_swap.strategy(W.WRITER)[0] == "pairs" and W.WRITER in cast_swap.BUILDERS
    spec = replacement_readiness.spec_for(W.WRITER)
    assert spec["known"] and spec["influences"] == 1 and len(spec["roles"]) == 18


@pytest.mark.skipif(not os.environ.get("SC2_IMAGE"), reason="SC2_IMAGE (owned disc) not set")
def test_owned_disc_reads_every_fighter():
    with S.Disc(os.environ["SC2_IMAGE"]) as d:
        t = S.fighter_table(d.dol)
        assert {k: (v["base"], v["costumes"], int(v["extra"])) for k, v in t.items()} == S.EXPECTED
        W.random_patch_site(d.dol)
        for key in ("mitsurugi", "link", "inferno"):
            c = S.read_costume(d, key)
            assert len(S.roles_of(c.vmg)) == 18 and V.stats(c.vmg)["triangles"] > 4000
