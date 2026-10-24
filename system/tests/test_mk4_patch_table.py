"""Focused tests for the MK4 (USA) N64 boot patch-table reader.

The synthetic tests are hermetic; the owned-build test runs only when the
owned ROM is present in the local cache.
"""

import struct

import pytest

from gbox.mk4_patch_table import (
    ASSET_END,
    ASSET_START,
    DEFAULT_ROM,
    MAIN_ENTRY,
    PATCH_TABLE_ENTRIES,
    PATCH_TABLE_END,
    PATCH_TABLE_START,
    V64_MAGIC,
    Z64_MAGIC,
    PatchTable,
    classify_address,
    cluster_by_bucket,
    load_rom,
    parse_patch_table,
    region,
    scan_magics,
    summarize,
    to_z64,
)


def _swap_halfwords(data: bytes) -> bytes:
    out = bytearray(data)
    out[0::2] = data[1::2]
    out[1::2] = data[0::2]
    return bytes(out)


def _synthetic_rom(pairs, size: int = 0x140000) -> bytes:
    rom = bytearray(size)
    rom[0:4] = Z64_MAGIC
    for i, (slot, value) in enumerate(pairs):
        struct.pack_into(">II", rom, PATCH_TABLE_START + i * 8, slot, value)
    return bytes(rom)


def test_to_z64_roundtrips_a_v64_image():
    z64 = Z64_MAGIC + bytes(range(256))
    v64 = _swap_halfwords(z64)
    assert v64[:4] == V64_MAGIC
    assert to_z64(v64) == z64
    assert to_z64(z64) == z64


def test_to_z64_rejects_a_non_rom_image():
    with pytest.raises(ValueError):
        to_z64(b"\x00\x01\x02\x03" + bytes(16))


def test_classify_address_buckets():
    assert classify_address(0) == "zero"
    assert classify_address(0x1000) == "rom"
    assert classify_address(0x20FFF0) == "rom"
    assert classify_address(0x210000) == "other"
    assert classify_address(MAIN_ENTRY) == "ram"
    assert classify_address(0x807FFFFC) == "ram"
    assert classify_address(0x80800000) == "other"
    assert classify_address(0x12345678) == "other"


def test_region_matches_the_known_layout():
    assert region(0x1000) == "code"
    assert region(PATCH_TABLE_START) == "patch"
    assert region(ASSET_START) == "asset"
    assert region(ASSET_END - 1) == "asset"
    assert region(ASSET_END) == "pad"


def test_parse_patch_table_on_a_synthetic_image():
    rom = _synthetic_rom([(0x140000, 0x140010), (0x80001000, 0x140020)])
    table = parse_patch_table(rom)
    assert isinstance(table, PatchTable)
    assert len(table.entries) == PATCH_TABLE_ENTRIES == 1353
    assert len(table.rom_slots) == 1
    assert len(table.ram_slots) == 1
    assert table.rom_slots[0].slot_region == "asset"
    assert table.ram_slots[0].slot_region == "ram"
    assert table.asset_values == [0x140010, 0x140020]
    assert table.ram_values == []
    window = table.patch_table_window()
    assert window is not None
    lo, hi, size = window
    assert (lo, hi) == (0x140000, 0x140000)
    assert size == 1


def test_cluster_by_bucket_counts_ranges():
    assert cluster_by_bucket([0x140000, 0x140010, 0x150000]) == [(0x140000, 2), (0x150000, 1)]


def test_scan_magics_finds_patterns_in_the_asset_region():
    rom = bytearray(0x140000)
    rom[0x140000:0x140004] = b"MK4!"
    hits = scan_magics(bytes(rom), [b"MK4!", b"NOPE"], start=ASSET_START, end=ASSET_END)
    assert hits[b"MK4!"] == [0x140000]
    assert hits[b"NOPE"] == []


@pytest.mark.skipif(not DEFAULT_ROM.exists(), reason="owned MK4 (USA) ROM not in local cache")
def test_owned_build_patch_table_shape():
    rom = load_rom(DEFAULT_ROM)
    assert rom[:4] == Z64_MAGIC
    table = parse_patch_table(rom)
    assert len(table.entries) == 1353
    assert len(table.rom_slots) == 1298
    assert len(table.ram_slots) == 55
    assert len(table.asset_values) == 707
    assert len(table.ram_values) == 368
    # every ROM slot lives in the asset region ...
    assert all(e.slot_region == "asset" for e in table.rom_slots)
    # ... and every ROM-class value points into the mapped ROM window.
    rom_values = [e.value for e in table.entries if e.value_class == "rom"]
    assert len(rom_values) == 881
    assert all(0x1000 <= v < 0x210000 for v in rom_values)
    window = table.patch_table_window()
    assert window is not None
    lo, hi, size = window
    assert ASSET_START <= lo <= hi < ASSET_END
    assert size == hi - lo + 1


@pytest.mark.skipif(not DEFAULT_ROM.exists(), reason="owned MK4 (USA) ROM not in local cache")
def test_owned_build_summary_is_stable():
    rom = load_rom(DEFAULT_ROM)
    summary = summarize(rom)
    assert summary["entries"] == 1353
    assert summary["z64_sha256"] == summarize(rom)["z64_sha256"]
    assert summary["patch_window"] is not None
