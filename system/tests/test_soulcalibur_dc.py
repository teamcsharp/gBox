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
    assert all(np.abs(got - w).sum(1).min() < 1e-5 for w in want)
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
