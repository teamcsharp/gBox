"""Focused tests for gbox/tetris_ds.py — the Tetris DS (USA) native sprite reader.

Self-contained: no ROM, no third-party packages. The parsers are additionally
validated against the owned 16 MiB dump (sha256 4e443f9b…) in the integration
runs recorded on request c49f437bb6d84868: LZ10 byte-equality with ndspy on
all 410 compressed files, 4/4 NCLR and 6/6 NCGR resources parsed, 70/70 .chr
banks tile-aligned, 76 sprite sets extracted.
"""

import struct
import zlib
from pathlib import Path

import pytest

from gbox import tetris_ds
from gbox.tetris_ds import (NDSRom, TetrisDSReader, lz10_decompress,
                            parse_nclr, parse_ncgr, parse_objs, png_rgba,
                            raw_tiles, render_sheet, rgb555)


# ---------------------------------------------------------------- LZ10

def test_lz10_literal_run():
    # flag 0x00 = 8 literals
    blob = b"\x10\x05\x00\x00" + b"\x00" + b"hello" + b"\x00\x00\x00"
    assert lz10_decompress(blob) == b"hello"


def test_lz10_backward_window_reads_zero_fill():
    # flag 0x80 = copy; w = 0x0000 -> len 3, offset 0 -> window = out_pos-1 = -1
    # reads the zero-filled end of the output buffer (the Nitro backward LZ).
    blob = b"\x10\x03\x00\x00" + b"\x80" + b"\x00\x00"
    assert lz10_decompress(blob) == b"\x00\x00\x00"


def test_lz10_mixed_literal_and_copy():
    # flag 0xA0: bit0=1 copy(w=0x0000: len 3, window=out_pos-1 -> reads the
    # zero-filled buffer at -1 first, then repeats the previous byte),
    # bit1=0 literal 'A', bit2=1 copy (now repeats 'A'), bit3=0 literal 'B';
    # out len 8 is reached exactly after 'B'.
    blob = b"\x10\x08\x00\x00" + b"\xa0" + b"\x00\x00" + b"A" + b"\x00\x00" + b"B"
    assert lz10_decompress(blob) == b"\x00\x00\x00AAAAB"


def test_lz10_rejects_wrong_type():
    with pytest.raises(tetris_ds.LZ10Error):
        lz10_decompress(b"\x11\x00\x00\x00rest")


def test_lz10_rejects_truncated():
    with pytest.raises(tetris_ds.LZ10Error):
        lz10_decompress(b"\x10\x20\x00\x00" + b"\x00" + b"short")


# ---------------------------------------------------------------- ROM / FNT

def _mini_rom(files, gamecode=b"ATRE", title=b"TETRIS DS"):
    """Flatten (path, bytes) into an ordered [(path, payload)] listing."""
    tree = {}
    for path, payload in files:
        parts = path.split("/")
        node = tree
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                node[part] = payload  # leaf = bytes payload
            else:
                node = node.setdefault(part, {})
    ordered = []

    def walk(node, prefix):
        for name in sorted(node):
            child = node[name]
            if isinstance(child, bytes):
                ordered.append((f"{prefix}/{name}", child))
            else:
                walk(child, f"{prefix}/{name}")
    walk(tree, "")
    return ordered


def _build_rom_full(gamecode=b"ATRE", title=b"TETRIS DS", files=None):
    files = files or [("a.bin", b"\x01\x02\x03"), ("dir/b.bin", b"sprites!")]
    ordered = _mini_rom(files)
    first_id = 0
    # ---- FAT
    fat_entries = []
    payload_blobs = []
    offset = 0x100000
    for _path, payload in ordered:
        fat_entries.append((offset, offset + len(payload)))
        payload_blobs.append(payload)
        offset += len(payload)
    # ---- FNT (root at 0x08, subdirs follow in DFS order; ids 0xF000+ordinal)
    fnt = bytearray(b"\x08\x00\x00\x00" + struct.pack("<H", first_id) + struct.pack("<H", 0xF000))

    dirs_seen = []

    def emit_sub(dir_paths, ordinal_base):
        """dir_paths: list of (name, is_dir, payload) for this directory."""
        nonlocal fnt
        kids = []
        for name, is_dir, payload in dir_paths:
            if is_dir:
                kid_id = ordinal_base + len(dirs_seen) + 1
                fnt += bytes([0x80 | len(name)]) + name.encode() + struct.pack("<H", 0xF000 + kid_id)
                kids.append((name, kid_id))
            else:
                fnt += bytes([len(name)]) + name.encode()
        fnt += b"\x00"
        return kids

    # group paths by directory
    groups = {"": []}
    for path, payload in files:
        parts = path.split("/")
        if len(parts) == 1:
            groups[""].append((parts[0], False, payload))
        else:
            dirname = parts[0]
            groups[""].append((dirname, True, None))
            groups.setdefault(dirname, []).append((parts[1], False, payload))

    # dedupe dir entries in root
    seen = []
    for entry in groups[""]:
        if entry not in seen:
            seen.append(entry)
    groups[""] = seen

    # order: root first, then each dir in order of first appearance
    order = [""]
    for entry in groups[""]:
        if entry[1]:
            order.append(entry[0])
    for d in order:
        emit_sub(groups.get(d, []), 0)

    # ---- assemble ROM
    header = bytearray(0x200)
    header[0x00:0x0C] = title.ljust(12, b"\x00")[:12]
    header[0x0C:0x10] = gamecode
    header[0x12] = 0x00
    struct.pack_into("<IIII", header, 0x20, 0x4000, 0x2000800, 0x2000000, 0x100)
    struct.pack_into("<IIII", header, 0x30, 0x5000, 0x3800000, 0x3800000, 0x100)
    fnt_off = 0x200
    fat_off = fnt_off + len(fnt)
    struct.pack_into("<II", header, 0x40, fnt_off, len(fnt))
    struct.pack_into("<II", header, 0x48, fat_off, len(fat_entries) * 8)
    rom = bytes(header) + bytes(fnt) + b"".join(struct.pack("<II", s, e) for s, e in fat_entries)
    rom = rom.ljust(0x100000, b"\x00") + b"".join(payload_blobs)
    return rom


def test_mini_rom_fnt_and_fat():
    rom = _build_rom_full(files=[("a.bin", b"\x01\x02\x03"), ("dir/b.bin", b"sprites!")])
    r = NDSRom(rom)
    assert r.is_tetris_ds_usa()
    assert set(r.paths()) == {"a.bin", "dir/b.bin"}
    assert r.raw("a.bin") == b"\x01\x02\x03"
    assert r.raw("/dir/b.bin") == b"sprites!"


def test_mini_rom_identity_rejection():
    rom = _build_rom_full(gamecode=b"ZZZZ", title=b"OTHER GAME",
                           files=[("a.bin", b"x")])
    r = NDSRom(rom)
    assert not r.is_tetris_ds_usa()
    with pytest.raises(ValueError):
        TetrisDSReader(rom)


def test_mini_rom_lz_transparent():
    # a file that starts with 0x10 gets decompressed on read()
    blob = b"\x10\x05\x00\x00" + b"\x00hello\x00\x00\x00"
    rom = _build_rom_full(files=[("c.chr", blob)])
    r = NDSRom(rom)
    assert r.read("c.chr") == b"hello"
    assert r.read("c.chr", decompress=False) == blob


# ---------------------------------------------------------------- NCLR / NCGR / objs

def _nclr(colors):
    data = b"".join(struct.pack("<H", c) for c in colors)
    section = b"TTLP" + struct.pack("<I", 8 + 0x10 + len(data)) \
        + struct.pack("<IIII", 3, 0, len(data), 0x10) + data
    blob = (b"RLCN" + struct.pack("<HH", 0xFFFE, 0x0001)
            + struct.pack("<I", 0x10 + len(section))
            + struct.pack("<HH", 0x10, 0x0001) + section)
    return blob


def test_nclr_roundtrip():
    blob = _nclr([0x7C00, 0x7FFF, 0x0000])
    pals = parse_nclr(blob)
    assert len(pals) == 1
    assert pals[0][0] == rgb555(0x7C00) == (255, 0, 0)
    assert pals[0][1] == rgb555(0x7FFF) == (255, 255, 255)
    assert pals[0][2] == (0, 0, 0)


def test_nclr_rejects_non_nclr():
    with pytest.raises(ValueError):
        parse_nclr(b"XXXX" + b"\x00" * 32)


def _ncgr(tile_data, w=8, h=8, depth=4):
    section = b"RAHC" + struct.pack("<I", 8 + 0x18 + len(tile_data)) \
        + struct.pack("<I", (w << 16) | h) + struct.pack("<I", depth) \
        + struct.pack("<II", 0, 0) + struct.pack("<II", len(tile_data), 0x18) + tile_data
    blob = (b"RGCN" + struct.pack("<HH", 0xFFFE, 0x0101)
            + struct.pack("<I", 0x10 + len(section))
            + struct.pack("<HH", 0x10, 0x0001) + section)
    return blob


def test_ncgr_roundtrip_8bpp():
    tile = bytes(range(64))  # one 8x8 tile
    blob = _ncgr(tile)
    out = parse_ncgr(blob)
    assert len(out) == 1
    assert out[0]["width"] == 8 and out[0]["height"] == 8 and out[0]["depth"] == 4
    assert out[0]["tiles"] == [tile]


def test_ncgr_4bpp_expansion():
    raw = bytes([0x12, 0x34])  # 4 pixels: 1,2,3,4
    blob = _ncgr(raw, w=2, h=2, depth=3)
    out = parse_ncgr(blob)
    assert out[0]["tiles"] == [bytes([1, 2, 3, 4])]


def test_objs_parse_and_trailing():
    blob = struct.pack("<III", 2, 3, 4) + struct.pack("<HH", 0, 1) + struct.pack("<HH", 7, 2)
    parsed = parse_objs(blob)
    assert parsed["header"] == (2, 3, 4)
    assert parsed["pairs"] == [(0, 1), (7, 2)]
    assert parsed["tiles"] == [0, 7]
    parsed2 = parse_objs(blob + b"\xff")
    assert parsed2["trailing_bytes"] == 1


def test_raw_tiles_8bpp_and_4bpp():
    bank = bytes(range(128))  # two 8x8 tiles
    tiles = raw_tiles(bank, 8)
    assert len(tiles) == 2 and tiles[0] == bank[:64]
    bank4 = bytes([0xAB]) * 32
    t4 = raw_tiles(bank4, 4)
    assert len(t4) == 1 and len(t4[0]) == 64
    assert t4[0][0] == 0xA and t4[0][1] == 0xB


# ---------------------------------------------------------------- PNG / sheet

def test_png_roundtrip_signature_and_dims():
    w, h = 3, 2
    px = bytes([255, 0, 0, 255]) * (w * h)
    png = png_rgba(w, h, px)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", png[16:24]) == (w, h)
    # IDAT decompresses to h rows of 1 + w*4 bytes
    pos, idat = 8, b""
    while pos < len(png):
        ln = struct.unpack(">I", png[pos:pos + 4])[0]
        if png[pos + 4:pos + 8] == b"IDAT":
            idat += png[pos + 8:pos + 8 + ln]
        pos += 12 + ln
    raw = zlib.decompress(idat)
    assert len(raw) == h * (1 + w * 4)


def test_render_sheet_grid_and_transparency():
    tile = bytes([1, 1, 1, 1, 1, 1, 1, 1]) + bytes([0]) * 56  # 8x8
    pal = [(10, 20, 30), (200, 100, 50)]
    w, h, rgba = render_sheet([tile], pal)
    assert (w, h) == (8, 8)
    # first pixel: index 1 -> color 1
    assert tuple(rgba[0:4]) == (200, 100, 50, 255)
    # index 0 -> transparent
    assert tuple(rgba[8 * 4:8 * 4 + 4]) == (0, 0, 0, 0)


# ---------------------------------------------------------------- reader facade

def test_reader_extract_on_mini_rom(tmp_path):
    chr_bank = bytes([5] * 64)  # one 8x8 tile of index 5
    rom = _build_rom_full(files=[("ct_.chr", chr_bank), ("ct_.objs", b"\x00" * 12)])
    reader = TetrisDSReader(rom)
    assert "ct_" in reader.sprite_sets()
    report = reader.extract(tmp_path)
    assert report["sets"]["ct_"]["tiles"] == 1
    assert Path(report["sets"]["ct_"]["png"]).is_file()
    assert Path(report["sets"]["ct_"]["json"]).is_file()


def test_roster_covers_verified_inventory():
    entries = tetris_ds.roster()
    assert len(entries) == 76
    assert {e["key"] for e in entries} == set(tetris_ds.TETRIS_DS_SETS)
    assert all(e["slug"].startswith("tetris_ds_") for e in entries)
    assert all(e["kind"] == "character" for e in entries)
