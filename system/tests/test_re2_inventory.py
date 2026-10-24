"""Focused tests for gbox.re2_inventory on a synthetic Resident Evil 2 N64 ROM.

The fixture builds a small big-endian cart image containing the game's own
structures in miniature: an overlay table (magic record + main overlay + the
directory record), an asset directory with one asset of each storage codec,
and overlay 1 carrying the character asset table, pair table and entity
tables.
"""

import struct
import zlib

import pytest

from gbox import re2_inventory as ri

TABLE_ROM = 0x10000
DIR_BASE = 0xA000
MAIN_ROM = 0x2000
MAIN_LOAD = 0x80010000
ROM_SIZE = 0x40000


def packbits_encode_bytes(data: bytes) -> bytes:
    out = bytearray()
    at = 0
    while at < len(data):
        run = 1
        while at + run < len(data) and data[at + run] == data[at]:
            run += 1
        if run >= 3:
            take = min(run, 0x80)
            out += bytes([0x100 - take, data[at]])
            at += take
            continue
        literal = 1
        while at + literal < len(data) and literal < 0x7F:
            r = 1
            while (at + literal + r < len(data)
                   and data[at + literal + r] == data[at + literal]):
                r += 1
            if r >= 3:
                break
            literal += 1
        out += bytes([literal]) + data[at:at + literal]
        at += literal
    out += b"\x00"
    return bytes(out)


def put16(buf: bytearray, off: int, value: int) -> None:
    struct.pack_into(">H", buf, off, value)


def put32(buf: bytearray, off: int, value: int) -> None:
    struct.pack_into(">I", buf, off, value)


def build_overlay_data() -> bytes:
    """Overlay 1 image with one character: mesh 1984, anims 100/101, textures 10/11."""
    data = bytearray(0x129200)  # RAM 0x80010000..0x8012A200, covers all four entity tables
    for i in range(len(data) // 2):
        put16(data, i * 2, 0xFFFF)
    # character asset table, asset_base 0: slot 7 = mesh, slots 1-2 = animations
    base = ri.CHAR_ASSET_TABLE - MAIN_LOAD
    for slot, value in ((1, 100), (2, 101), (7, 1984)):
        put16(data, base + slot * 2, value)
    # pair table, pair 0: 2 textures, kind 1
    pair = ri.PAIR_TABLE - MAIN_LOAD
    put16(data, pair, 2)
    put16(data, pair + 2, 1)
    put16(data, pair + 4, 10)
    put16(data, pair + 6, 11)
    # entity table 0, record 0: pair 0, asset_base 0
    ent = ri.ENTITY_TABLES[0] - MAIN_LOAD
    put16(data, ent + 4, 0)
    put16(data, ent + 6, 0)
    return bytes(data)


def raw_deflate(data: bytes) -> bytes:
    co = zlib.compressobj(wbits=-15, level=9)
    return co.compress(data) + co.flush()


def build_rom() -> bytes:
    rom = bytearray(ROM_SIZE)
    rom[0:4] = b"\x80\x37\x12\x40"
    rom[0x20:0x34] = b"TEST ROM".ljust(0x14, b"\x00")
    rom[0x3B:0x3F] = b"NREE"
    rom[0x3F] = 1

    # main overlay payload: 2-byte block header + raw deflate
    overlay = build_overlay_data()
    compressed = raw_deflate(overlay)
    put32(rom, MAIN_ROM, 0)  # block header (unused by the reader)
    rom[MAIN_ROM + 2:MAIN_ROM + 2 + len(compressed)] = compressed

    # overlay table: magic record, entry 1 (main), entry 0x43 (directory), terminator
    table = TABLE_ROM
    rom[table:table + ri.OVERLAY_RECORD] = ri.OVERLAY_MAGIC
    # the real table is dense, so fill every slot up to the directory record
    for index in range(2, ri.OVERLAY_DIRECTORY_INDEX):
        at = table + index * ri.OVERLAY_RECORD
        put32(rom, at, 0xB0000000)  # empty slot: zero sizes
        put32(rom, at + 4, 0)
        put32(rom, at + 8, 0x80000000)
        put32(rom, at + 12, 0x80000000)
    for index, (cart, csize, load, end) in (
        (1, (0xB0000000 + MAIN_ROM, 2 + len(compressed), MAIN_LOAD,
             MAIN_LOAD + len(overlay))),
        (ri.OVERLAY_DIRECTORY_INDEX, (0xB0000000 + DIR_BASE, 0, 0x80080000, 0x80080100)),
    ):
        at = table + index * ri.OVERLAY_RECORD
        put32(rom, at, cart)
        put32(rom, at + 4, csize)
        put32(rom, at + 8, load)
        put32(rom, at + 12, end)
    # terminator: invalid cart address
    at = table + (ri.OVERLAY_DIRECTORY_INDEX + 1) * ri.OVERLAY_RECORD
    put32(rom, at, 0)

    # asset directory: 4 assets, one per storage kind
    put32(rom, DIR_BASE, 4)
    rom[DIR_BASE + 8:DIR_BASE + ri.ASSET_HEADER] = b"TEST BUILD\n".ljust(ri.ASSET_HEADER - 8, b"\x00")
    payloads = [
        (b"ABCDEF", 1, b"ABCDEF"),                                          # stored
        (packbits_encode_bytes(b"AAAAABBBC"), 2, b"AAAAABBBC"),              # rle bytes
        (b"\xff\xfd\x12\x34\x00\x00", 4, b"\x12\x34" * 3),                  # rle16 units
        (b"\x00\x00" + raw_deflate(b"hello deflate world" * 3), 16,          # deflate
         b"hello deflate world" * 3),
    ]
    rel = ri.ASSET_HEADER + 4 * ri.ASSET_RECORD
    for i, (stored, kind, decoded) in enumerate(payloads):
        put32(rom, DIR_BASE + ri.ASSET_HEADER + i * ri.ASSET_RECORD, rel)
        put32(rom, DIR_BASE + ri.ASSET_HEADER + i * ri.ASSET_RECORD + 4, len(stored))
        rom[DIR_BASE + rel:DIR_BASE + rel + len(stored)] = stored
        trailer = DIR_BASE + rel + len(stored) + (len(stored) & 1)
        put32(rom, trailer, kind << 16)
        put32(rom, trailer + 4, len(decoded))
        rel = rel + len(stored) + (len(stored) & 1) + ri.ASSET_TRAILER
        rel = (rel + 1) & ~1
    return bytes(rom)


@pytest.fixture(scope="module")
def rom_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("re2") / "synthetic.z64"
    path.write_bytes(build_rom())
    return path


def test_byte_order_detection():
    assert ri.detect_order(b"\x80\x37\x12\x40" + b"\x00" * 8) == "z64"
    assert ri.detect_order(b"\x37\x80\x40\x12" + b"\x00" * 8) == "v64"
    assert ri.detect_order(b"\x40\x12\x37\x80" + b"\x00" * 8) == "n64"


def test_packbits_roundtrip():
    data = b"AB" + b"B" * 300 + b"C"
    assert ri.packbits_decode(packbits_encode_bytes(data)) == data


def test_overlay_and_directory(rom_path):
    rom, _, _ = ri.load_rom(rom_path)
    overlays = ri.read_overlays(rom)
    assert [e.index for e in overlays] == list(range(1, ri.OVERLAY_DIRECTORY_INDEX + 1))
    main = overlays[0]
    assert main.decompress(rom) == build_overlay_data()
    directory = ri.read_asset_directory(rom, overlays)
    assert directory.count == 4
    assert directory.null_slots == 0
    assert directory.build_stamp == "TEST BUILD"


def test_asset_codecs(rom_path):
    rom, _, _ = ri.load_rom(rom_path)
    directory = ri.read_asset_directory(rom, ri.read_overlays(rom))
    by_index = {e.index: e for e in directory.entries}
    assert by_index[0].decode(rom, directory.base) == b"ABCDEF"
    assert by_index[1].decode(rom, directory.base) == b"AAAAABBBC"
    assert by_index[2].decode(rom, directory.base) == b"\x12\x34" * 3
    assert by_index[3].decode(rom, directory.base) == b"hello deflate world" * 3


def test_characters(rom_path):
    manifest = ri.inventory(rom_path)
    tables = manifest["characters"]["entity_tables"]
    assert len(tables) == 4
    chars = tables[0]["characters"]
    assert len(chars) == 1
    char = chars[0]
    assert char["mesh_asset"] == 1984
    assert char["animation_assets"] == [100, 101]
    assert char["texture_ids"] == [10, 11]
    assert manifest["asset_directory"]["storage_kinds"] == {"1": 1, "2": 1, "4": 1, "16": 1}
    assert manifest["asset_directory"]["decoded"] == 4
    assert manifest["game"]["game_code"] == "NREE"


def test_v64_normalizes_identically(rom_path):
    rom, _, _ = ri.load_rom(rom_path)
    swapped = bytearray(rom)
    for i in range(0, len(swapped) - 1, 2):
        swapped[i], swapped[i + 1] = swapped[i + 1], swapped[i]
    v64 = rom_path.with_name("synthetic.v64")
    v64.write_bytes(bytes(swapped))
    assert ri.load_rom(v64)[0] == rom
    assert ri.inventory(v64)["source"]["rom_sha256"] == ri.inventory(rom_path)["source"]["rom_sha256"]
