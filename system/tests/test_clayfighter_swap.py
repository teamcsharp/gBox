"""gbox/clayfighter_swap.py (request #588): Clay Fighter: Sculptor's Cut fighter sprite reader + writer.

Synthetic tests build a small ROM in the game's own layout (CHAR_ROM_START/END tables, fighter blobs with the 0x40
header, run-coded frame bitmaps, sample table, RLE8-packed CharDef with frame table / palettes / alpha records) and
check reader -> writer -> reader round trips, size and palette edge cases, relocation and the header CRC. Owned-ROM
tests skip when the dump isn't on this machine."""
import json
import os
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import clayfighter_swap as S
from gbox.romexport import n64_crc

ROM_SIZE = 0x200000
BLOB_AREA = 0x110000


# ------------------------------------------------------------------------------------------------ synthetic ROM

def _frame_pixels(W, H, seed):
    """A little figure: opaque body with a transparent margin, indices 0..63, a few partial-alpha pixels."""
    rng = np.random.default_rng(seed)
    idx = np.full((H, W), -1, np.int16)
    y0, x0 = H // 4, W // 4
    idx[y0:, x0:max(x0 + 1, W - W // 4)] = rng.integers(0, 64, (H - y0, max(1, W - W // 4 - x0)))
    alpha = {}
    flat = idx.reshape(-1)
    for t in np.nonzero(flat >= 0)[0][::7][:10]:
        alpha[int(t)] = int(t) % 8
    return idx, alpha


def build_blob(geoms, n_pal=8, seed=0, pal_used=None, rec_slack=0):
    """One fighter blob in the game's layout. geoms: [(W, H, X, Y)] per frame. rec_slack: spare alpha-record room."""
    rng = np.random.default_rng(seed)
    n = len(geoms)
    pal_used = pal_used or [k % n_pal for k in range(n)]
    bitmaps, records = [], []
    for k, (W, H, X, Y) in enumerate(geoms):
        idx, alpha = _frame_pixels(W, H, seed * 100 + k)
        bitmaps.append(S.encode_bitmap(W, H, X, Y, idx, pal_used[k]))
        records.append(S.encode_alpha(W, H, alpha))
    defs = bytes(range(64)) * 2                            # stands in for sequences / rects / moves
    h2 = S.HEADER + len(defs)
    h4 = h2 + 12 * n
    h5 = h4 + 128 * n_pal
    rec0 = h5 + S.EFFECT_PALETTES
    h6 = (rec0 + sum(len(r) for r in records) + rec_slack + 15) & ~15
    sound = b"B1\x00\x00" + bytes(12)
    image = bytearray(h6 + len(sound))
    image[S.HEADER:h2] = defs
    pals = rng.integers(0, 0x10000, n_pal * 64).astype(np.uint16) | 1
    image[h4:h5] = pals.astype(">u2").tobytes()
    image[h5:rec0] = b"\x2f" + bytes(S.EFFECT_PALETTES - 1)
    image[h6:] = sound
    h7 = S.HEADER + sum(len(b) for b in bitmaps)
    samples = bytes(range(32))
    h8 = h7 + len(samples)
    p, rp, offs = S.HEADER, rec0, []
    for b, r in zip(bitmaps, records):
        image[rp:rp + len(r)] = r
        struct.pack_into(">III", image, h2 + 12 * len(offs), p, len(b), rp - S.HEADER + h8)
        offs.append(p)
        p += len(b)
        rp += len(r)
    comp = S.pack_chardef(bytes(image[S.HEADER:]))
    hdr = [S.VERSION << 16 | n, S.HEADER, h2, n_pal, h4, h5, h6, h7, h8, len(comp), 1, 1, 0, 0, 0, 0]
    image[:S.HEADER] = struct.pack(">16I", *hdr)
    blob = bytearray(struct.pack(">16I", *hdr)) + b"".join(bitmaps) + samples + comp
    return bytes(blob), image


GEOMS = [[(20, 30, 10, 29), (17, 9, 8, 8), (33, 40, 16, 39)],
         [(1, 1, 0, 0), (255, 6, 127, 5), (200, 3, 100, 2), (7, 255, 3, 254)]]


def synthetic_rom():
    rom = bytearray(ROM_SIZE)
    rom[0:4] = b"\x80\x37\x12\x40"
    rom[8:12] = b"\x80\x00\x04\x00"
    rom[0x20:0x34] = b"Clayfighter SC      "
    p, starts, ends = BLOB_AREA, [], []
    for i in range(S.COUNT):
        if i == 7:                                          # CHAR_HOBO: the nullchar stub, as in the real build
            blob = b"nullchar" + bytes(8)
        else:
            blob, _img = build_blob(GEOMS[i % 2], seed=i, rec_slack=256 if i == 4 else 0)
        rom[p:p + len(blob)] = blob
        starts.append(p)
        ends.append(p + len(blob))
        p += len(blob)                                      # packed tight: growth must relocate
        p += p & 1
    struct.pack_into(f">{S.COUNT}I", rom, S.CHAR_ROM_START, *starts)
    struct.pack_into(f">{S.COUNT}I", rom, S.CHAR_ROM_END, *ends)
    S.fix_crc(rom, "6102")
    return bytes(rom)


@pytest.fixture(scope="module")
def rom():
    return synthetic_rom()


def _solid_donor(n, w=24, h=40, colours=None):
    """Donor frames with exact 5-bit colours (so quantisation is lossless) on a transparent background."""
    colours = colours or [(248, 0, 0), (0, 248, 0), (0, 0, 248), (248, 248, 0), (0, 0, 0), (255, 255, 255)]
    out = []
    for k in range(n):
        im = np.zeros((h + 6, w + 4, 4), np.uint8)
        for y in range(h):
            im[3 + y, 2:2 + w, :3] = colours[(y // 4 + k) % len(colours)]
            im[3 + y, 2:2 + w, 3] = 255
        out.append(im)
    return out


# ------------------------------------------------------------------------------------------------ codecs

def test_rle8_round_trip_and_end_code():
    for data in [b"", b"\x00", b"\xff" * 300, bytes(range(256)) * 3, b"ab" * 200 + b"\x07" * 129 + b"z"]:
        packed = S.rle8_encode(data)
        assert packed[-1] == 0xFF
        assert S.rle8_decode(packed, len(data)) == (data, len(packed))
    assert S.unpack_chardef(S.pack_chardef(b"hello" * 99)) == b"hello" * 99


def _bits(fields):
    """An independent LSB-first packer: [(value, nbits)] -> bytes."""
    bits = [(v >> k) & 1 for v, n in fields for k in range(n)]
    bits += [0] * (-len(bits) % 8)
    return bytes(sum(b << k for k, b in enumerate(bits[i:i + 8])) for i in range(0, len(bits), 8))


def test_decode_hand_built_frame():
    # 4x2: row 0 = 3 opaque px, palette 5, mode 3 (5-bit, index v) then 1 transparent; row 1 = 2 transparent +
    # 2 opaque px in mode 8 (4 bits + extra bit: index 4v + 3)
    stream = _bits([((2 << 1), 8), (5, 8), (3, 3), (0, 5), (1, 5), (31, 5),
                    ((0 << 1) | 1, 8), ((1 << 1) | 1, 8),
                    ((1 << 1), 8), (9, 8), (5, 3), (1, 1), (0, 4), (15, 4)])
    d = S.decode_bitmap(bytes([4, 2, 2, 1]) + stream)
    assert (d["W"], d["H"], d["X"], d["Y"]) == (4, 2, 2, 1)
    assert d["pal"].tolist() == [[5, 5, 5, -1], [-1, -1, 9, 9]]
    assert d["idx"][0, :3].tolist() == [0, 1, 31] and d["idx"][1, 2:].tolist() == [3, 63]
    # alpha: skip 2 (digit nibble 8|2), level 3 -> pixel 2 alpha 100; then skip to the end
    rec = _bits([(8 | 2, 4), (3, 4), (8 | 0, 4), (8 | 5, 4), (0, 4)])     # t = 2 + 1 + 5 = 8 = H * W: end
    a, used = S.decode_alpha(rec, 4, 2)
    assert a == {2: 100} and used == len(rec)


@pytest.mark.parametrize("W,H", [(1, 1), (2, 1), (255, 3), (3, 255), (200, 2), (129, 4)])
def test_bitmap_encoder_round_trip_sizes(W, H):
    rng = np.random.default_rng(W * 1000 + H)
    idx = rng.integers(-1, 64, (H, W)).astype(np.int16)
    idx[0] = rng.integers(0, 64, W)                        # a fully opaque row (runs > 128 split)
    P = rng.integers(0, 256, H)
    b = S.encode_bitmap(W, H, W // 2, H - 1, idx, P)
    assert len(b) % 2 == 0
    d = S.decode_bitmap(b)
    assert d["used"] in (len(b), len(b) - 1)
    assert (d["idx"].astype(int)[idx >= 0] == idx[idx >= 0]).all()
    assert ((d["pal"] >= 0) == (idx >= 0)).all()
    rows = np.nonzero((idx >= 0).any(1))[0]
    assert all((d["pal"][r][idx[r] >= 0] == P[r]).all() for r in rows)


@pytest.mark.parametrize("vals,mode", [([0, 4, 60], 5), ([3, 7, 63], 8), ([0, 2, 30], 9), ([32, 34, 62], 10),
                                       ([0, 31, 5], 3), ([32, 63], 4), ([0, 62, 40, 2], 1), ([1, 63, 33], 2),
                                       ([0, 63, 1], 0)])
def test_row_mode_choice(vals, mode):
    assert S._row_mode(np.array(vals)) == mode
    idx = np.array([vals], np.int16)
    d = S.decode_bitmap(S.encode_bitmap(len(vals), 1, 0, 0, idx, 7))
    assert d["idx"][0].tolist() == vals


def test_bitmap_rejects_bad_geometry_and_index():
    with pytest.raises(ValueError):
        S.encode_bitmap(0, 4, 0, 0, np.zeros((4, 0)), 0)
    with pytest.raises(ValueError):
        S.encode_bitmap(256, 1, 0, 0, np.zeros((1, 256)), 0)
    with pytest.raises(ValueError):
        S.encode_bitmap(2, 1, 0, 0, np.array([[0, 64]]), 0)


def test_alpha_round_trip_large_skips():
    a = {0: 0, 1: 7, 5000: 3, 255 * 255 - 1: 5}
    rec = S.encode_alpha(255, 255, a)
    out, used = S.decode_alpha(rec, 255, 255)
    assert out == {k: 25 * (v + 1) for k, v in a.items()} and used == len(rec)


# ------------------------------------------------------------------------------------------------ reader on the synthetic ROM

def test_reader_on_synthetic_rom(rom):
    v = S.validate(rom)
    assert v["ok"], v["problems"]
    assert v["frames"]["CHAR_HOBO"] == 0
    f = S.Fighter(rom, 1)
    assert f.count == len(GEOMS[1])
    assert [(d["W"], d["H"], d["X"], d["Y"]) for d in f.frames()] == GEOMS[1]
    with pytest.raises(ValueError, match="nullchar"):
        S.Fighter(rom, 7)
    assert struct.unpack_from(">II", rom, 0x10) == n64_crc(rom, "6102")


# ------------------------------------------------------------------------------------------------ writer round trips

def test_writer_reader_round_trip_exact_colours(rom):
    before = S.Fighter(rom, 0)
    donor = _solid_donor(3)
    targets = [{k: d[k] for k in ("W", "H", "X", "Y")} for d in before.frames()]
    canvases = S.fit_frames(targets, donor)
    new, rep = S.write_fighters(rom, [{"index": 0, "frames": donor}])
    after = S.Fighter(new, 0)
    assert after.count == before.count
    pals = after.palettes()
    for i, d in enumerate(after.frames()):
        assert (d["W"], d["H"], d["X"], d["Y"]) == tuple(targets[i].values())
        got, want = after.rgba(d, pals), canvases[i]
        m = want[..., 3] >= 64
        assert (got[..., 3] > 0).tolist() == m.tolist()
        assert (got[..., :3][m] >> 3 == want[..., :3][m] >> 3).all()      # RGBA5551: 5 bits per channel
    # the CharDef outside palettes / frame table / records is untouched; other fighters too
    assert after.image[S.HEADER:before.h[2]] == before.image[S.HEADER:before.h[2]]
    assert after.image[before.h[6]:] == before.image[before.h[6]:]
    assert after.h[2:9] == before.h[2:9]
    for j in (1, 2, 16):
        a, b = S.Fighter(new, j), S.Fighter(rom, j)
        assert a.base == b.base and [a.bitmap(k) for k in range(a.count)] == [b.bitmap(k) for k in range(b.count)]
    assert S.validate(new)["ok"]
    assert struct.unpack_from(">II", new, 0x10) == n64_crc(new, "6102") != struct.unpack_from(">II", rom, 0x10)
    assert rep[0]["frames"] == 3


def test_unused_palettes_kept(rom):
    blob, _ = build_blob(GEOMS[0], n_pal=8, pal_used=[2, 5, 2])
    r = bytearray(rom)
    base = S.blob_table(rom)[0][3]
    end = S.blob_table(rom)[0][4]
    assert len(blob) <= end - base
    r[base:base + len(blob)] = blob
    new, _rep = S.write_fighters(bytes(r), [{"index": 3, "frames": _solid_donor(1)}])
    old, now = S.Fighter(bytes(r), 3).palettes(), S.Fighter(new, 3).palettes()
    changed = [p for p in range(8) if not (old[p] == now[p]).all()]
    assert set(changed) <= {2, 5} and changed
    used = S.Fighter(new, 3).used_palettes()
    assert set(used) <= {2, 5}


def test_more_frames_than_palettes_share(rom):
    geoms = [(10, 12, 5, 11)] * 6
    blob, _ = build_blob(geoms, n_pal=2, pal_used=[0, 1, 0, 1, 0, 1])
    r = bytearray(rom) + bytes(0x10000)
    base = len(rom)
    r[base:base + len(blob)] = blob
    struct.pack_into(">I", r, S.CHAR_ROM_START + 4 * 5, base)
    struct.pack_into(">I", r, S.CHAR_ROM_END + 4 * 5, base + len(blob))
    new, rep = S.write_fighters(bytes(r), [{"index": 5, "frames": _solid_donor(6)}])
    f = S.Fighter(new, 5)
    assert rep[0]["palettes"] == 2
    assert sorted(f.used_palettes()) == [0, 1]
    assert S.validate(new)["ok"]


def test_many_colours_partial_alpha_and_flip(rom):
    rng = np.random.default_rng(7)
    donor = []
    for k in range(5):
        im = np.zeros((60, 30, 4), np.uint8)
        im[..., :3] = rng.integers(0, 256, (60, 30, 3))
        im[5:, 3:27, 3] = 255
        im[5:, 3, 3] = 150                                  # a soft edge -> alpha records
        donor.append(im)
    new, rep = S.write_fighters(rom, [{"index": 4, "frames": donor, "flip": True}])
    f = S.Fighter(new, 4)
    frames = f.frames()
    assert all(d["idx"].max() <= 63 for d in frames)
    assert any(d["alpha"] for d in frames) and rep[0]["soft_edge_frames"] > 0
    assert S.validate(new)["ok"]
    # no spare record room (fighter 2): soft edges are dropped, never overrun
    new, rep = S.write_fighters(rom, [{"index": 2, "frames": donor}])
    assert S.validate(new)["ok"] and rep[0]["alpha_record_bytes"] <= S.Fighter(rom, 2).h[6]


def test_growth_relocates_blob_and_grows_rom(rom):
    rng = np.random.default_rng(3)
    donor = [np.dstack([rng.integers(0, 256, (90, 60, 3)), np.full((90, 60), 255)]).astype(np.uint8)]
    new, rep = S.write_fighters(rom, [{"index": 2, "frames": donor}])
    assert rep[0]["relocated"] and rep[0]["bitmap_bytes"] > rep[0]["original_bitmap_bytes"]
    assert len(new) > len(rom) and len(new) % S.GROW == 0
    starts, ends = S.blob_table(new)
    assert starts[2] >= len(rom) and ends[2] > starts[2]
    f, old = S.Fighter(new, 2), S.Fighter(rom, 2)
    assert [(d["W"], d["H"], d["X"], d["Y"]) for d in f.frames()] == GEOMS[0]
    assert f.h[7] == old.h[7] and f.h[8] == old.h[8]
    assert new[starts[2] + f.h[7]:starts[2] + f.h[8]] == rom[old.base + f.h[7]:old.base + f.h[8]]   # samples
    assert S.blob_table(new)[0][1] == S.blob_table(rom)[0][1]
    assert S.validate(new)["ok"]
    assert struct.unpack_from(">II", new, 0x10) == n64_crc(new, "6102")
    # a second swap on the grown ROM keeps the first
    new2, _ = S.write_fighters(new, [{"index": 0, "frames": _solid_donor(2)}])
    assert S.blob_table(new2)[0][2] == starts[2] and S.validate(new2)["ok"]


def test_fit_frames_letterbox_and_hotspot():
    targets = [{"W": 40, "H": 20, "X": 20, "Y": 19}, {"W": 10, "H": 50, "X": 5, "Y": 49}]
    donor = _solid_donor(1, w=30, h=30)
    out = S.fit_frames(targets, donor)
    for t, c in zip(targets, out):
        assert c.shape == (t["H"], t["W"], 4)
        ys, xs = np.nonzero(c[..., 3])
        assert ys.max() == t["Y"]                           # feet on the hotspot row
        assert abs((xs.min() + xs.max()) / 2 - t["X"]) <= 1.5
        assert xs.max() - xs.min() + 1 <= t["W"]
    assert S.deal(5, 2) == [0, 1, 0, 1, 0] and S.deal(3, 9) == [0, 3, 6]


# ------------------------------------------------------------------------------------------------ slots / donors

def test_slots_and_fighter_lookup():
    slots = S.cast_slots()
    assert len(slots) == 16 and all(s["slot"].startswith("fighter:") for s in slots)
    assert "fighter:hobo" not in {s["slot"] for s in slots}
    assert S.find_fighter("fighter:taffy")[0]["index"] == 14
    assert S.find_fighter("fighter:Bad Mr. Frosty")[0]["index"] == 0
    assert S.find_fighter("player")[0]["index"] == 0
    f, flip = S.find_fighter("fighter:EWJ:flip")
    assert f["code"] == "CHAR_EWJ" and flip
    with pytest.raises(ValueError):
        S.find_fighter("fighter:hobo")
    with pytest.raises(ValueError):
        S.find_fighter("fighter:ryu")
    assert len(S.roster_entries()) == 16


def _save(path, arr):
    from PIL import Image
    Image.fromarray(arr, "RGBA").save(path)


def test_donor_frames_sources(tmp_path):
    frames = _solid_donor(3)
    sheet, cells = S.sheet_of(frames)
    # sprite_capture entry: clips with sheet.json
    d = tmp_path / "cap"
    (d / "clips" / "walk").mkdir(parents=True)
    _save(d / "clips" / "walk" / "sheet.png", sheet)
    (d / "clips" / "walk" / "sheet.json").write_text(json.dumps({"frames": [{"sheet": c} for c in cells]}))
    _save(d / "sheet.png", sheet)
    meta = {"kind": "sprites", "model": "sheet.png", "name": "cap",
            "animations": [{"sheet": "clips/walk/sheet.png", "index": "clips/walk/sheet.json"}]}
    got, how = S.donor_frames(d, meta)
    assert len(got) == 3 and "clip" in how and (got[1] == frames[1]).all()
    # MVC2-style atlas index
    d2 = tmp_path / "mvc2"
    d2.mkdir()
    _save(d2 / "x.sprites.png", sheet)
    (d2 / "x.json").write_text(json.dumps({"atlas": {"sprites": {"file": "x.sprites.png"}},
                                           "sprites": [{"atlas_x": c[0], "atlas_y": c[1], "w": c[2], "h": c[3]}
                                                       for c in cells]}))
    got, how = S.donor_frames(d2, {"kind": "sprites", "model": "x.sprites.png"})
    assert len(got) == 3 and "x.json" in how
    # Tetris-DS-style sheet without frame rectangles: connected regions
    d3 = tmp_path / "tds"
    d3.mkdir()
    _save(d3 / "s.png", sheet)
    (d3 / "s_meta.json").write_text(json.dumps({"stem": "s", "tile_count": 9}))
    got, how = S.donor_frames(d3, {"kind": "sprites", "model": "s.png"})
    assert len(got) == 3 and "regions" in how
    # a 3D entry: its preview, background keyed out
    d4 = tmp_path / "glb"
    d4.mkdir()
    prev = np.zeros((50, 50, 4), np.uint8)
    prev[...] = (38, 40, 48, 255)
    prev[10:40, 20:30] = (200, 50, 50, 255)
    _save(d4 / "preview.png", prev)
    got, how = S.donor_frames(d4, {"kind": "character", "model": "m.glb", "preview": "preview.png"})
    assert len(got) == 1 and "static pose" in how and int((got[0][..., 3] > 0).sum()) == 300


def test_export_fighter_is_a_donor(rom, tmp_path):
    r = S.export_fighter(rom, 0, tmp_path)
    idx = json.loads(r["files"][1].read_text())
    assert len(idx["frames"]) == 3 and idx["frames"][0]["hotspot"] == [10, 29]
    got, how = S.donor_frames(tmp_path, {"kind": "sprites", "model": r["files"][0].name})
    assert len(got) == 3 and "sheet index" in how


def test_registered_writer_and_extractor():
    from gbox import char_coverage as CC, characters as C
    row = next(r for r in CC.WRITERS if r[0] == "clayfighter_swap")
    assert "fighter:<name>" in row[1]
    game = {"game_id": S.GAME_ID, "title": "Clay Fighter: Sculptor's Cut (USA)", "platform": "n64"}
    w = CC.writer_for(game)
    assert w and w["writer"] == "gbox.clayfighter_swap" and w["routed"]
    slots = CC.cast_slots(game)
    assert {"fighter:bmf", "fighter:zappa", "player"} <= {s["slot"] for s in slots}
    assert CC.extractor_for(game)[0] == "clayfighter"
    import inspect
    assert "fighter:<name>" in inspect.getsource(C.CharIn)                 # CharIn slot docs name the slot


# ------------------------------------------------------------------------------------------------ owned ROM

def _owned_rom():
    cands = [os.environ.get("GBOX_CLAYFIGHTER_ROM", ""),
             str(Path.home() / "gBox_alt/gbox-cache" / S.GAME_ID / "rom.z64")]
    cache = Path.home() / "gBox_alt/gbox-cache" / "n64-rom"
    if cache.is_dir():
        cands += [str(p) for p in cache.glob("*.z64") if p.stat().st_size == 0x1000000]
    for c in cands:
        if c and os.path.isfile(c):
            with open(c, "rb") as fh:
                head = fh.read(0x40)
            if head[:4] == b"\x80\x37\x12\x40" and head[0x20:0x2E] == b"Clayfighter SC":
                data = Path(c).read_bytes()
                import hashlib
                if hashlib.sha1(data).hexdigest().upper() == "28697FBA130DED056BF7C497DEAA3E154CCE8022":
                    return data
    return None


@pytest.fixture(scope="module")
def owned():
    data = _owned_rom()
    if data is None:
        pytest.skip("owned Clay Fighter: Sculptor's Cut (USA) ROM not on this machine")
    return data


def test_owned_layout_and_crc(owned):
    starts, ends = S.blob_table(owned)
    assert starts[0] == 0x0D1C70 and ends[16] == 0xB156B0
    assert owned[starts[7]:starts[7] + 8] == b"nullchar"
    assert struct.unpack_from(">II", owned, 0x10) == n64_crc(owned, "6102") == (0xFA5A3DFF, 0xB4C9CDB9)


@pytest.mark.parametrize("index,count", [(0, 185), (6, 131), (13, 140)])
def test_owned_frames_decode_exactly(owned, index, count):
    f = S.Fighter(owned, index)
    assert f.count == count
    frames = f.frames()
    for k, d in enumerate(frames):
        assert d["size"] - 1 <= d["used"] <= d["size"]
        nxt = f.rec_ram(k + 1) if k + 1 < f.count else f.h[6]
        assert f.rec_ram(k) + d["rec_used"] <= nxt
    assert S.rle8_encode(bytes(f.image[S.HEADER:])) and len(f.image) - S.HEADER == struct.unpack_from(
        ">I", owned, f.base + f.h[8] + 8)[0]


def test_owned_reencode_matches_original_stream(owned):
    """Our encoder reproduces most of the game's own frame bit streams byte for byte (same per-row mode choice)."""
    f = S.Fighter(owned, 0)
    same = 0
    for i in range(f.count):
        d = f.frame(i)
        idx = np.where(d["pal"] >= 0, d["idx"].astype(np.int16), -1)
        P = [int(r[r >= 0][0]) if (r >= 0).any() else 0 for r in d["pal"]]
        same += S.encode_bitmap(d["W"], d["H"], d["X"], d["Y"], idx, np.array(P)) == f.bitmap(i)
    assert same >= 0.7 * f.count


def test_owned_swap_frosty_with_taffy(owned):
    taffy = S.Fighter(owned, 14)
    pals = taffy.palettes()
    donor = [taffy.rgba(taffy.frame(i), pals) for i in range(0, taffy.count, 4)]
    new, rep = S.write_fighters(owned, [{"index": 0, "frames": donor}])
    f = S.Fighter(new, 0)
    assert f.count == 185
    for k in range(0, f.count, 20):
        d = f.frame(k)
        assert d["size"] - 1 <= d["used"] <= d["size"]
    assert struct.unpack_from(">II", new, 0x10) == n64_crc(new, "6102")
    assert new[0x1000:0xAB260] == owned[0x1000:0xAB260]            # code untouched
