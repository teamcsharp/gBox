"""Focused tests for gbox.re2_analysis.

Synthetic tests always run. The owned-ROM tests use the verified ROM at
GBOX_RE2_N64_ROM (default ~/gbox-cache/46eec2fc627c8f58/rom.z64) and skip
when it is absent. They exercise the overlay xref scanner and the 0x01410000
mesh probe.
"""

import os
import struct
from pathlib import Path

import pytest

from gbox import re2_analysis as ra
from gbox import re2_inventory as ri

ROM_PATH = Path(os.environ.get("GBOX_RE2_N64_ROM", Path.home() / "gbox-cache" / "46eec2fc627c8f58" / "rom.z64"))
needs_rom = pytest.mark.skipif(not ROM_PATH.exists(), reason="owned RE2 N64 rom.z64 not cached")


def _mips(op, rs, rt, imm):
    return struct.pack(">I", (op << 26) | (rs << 21) | (rt << 16) | (imm & 0xFFFF))


def test_xref_scanner_pairs_hi_lo_with_sign_adjust():
    # lui t0,0x8013 ; addiu t0,t0,0x87b0  -> 0x801287B0 (low half >= 0x8000: %hi is +1)
    # lui t1,0x8012 ; ori   t1,t1,0x87b0  -> 0x801287B0 (ORI zero-extends: plain high half)
    # lui t2,0x8012 ; addiu t2,t2,0x87b0  -> 0x801187B0, must NOT match
    code = (_mips(ra.OP_LUI, 0, 8, 0x8013) + _mips(ra.OP_ADDIU, 8, 8, 0x87B0)
            + _mips(ra.OP_LUI, 0, 9, 0x8012) + _mips(ra.OP_ORI, 9, 9, 0x87B0)
            + _mips(ra.OP_LUI, 0, 10, 0x8012) + _mips(ra.OP_ADDIU, 10, 10, 0x87B0))
    hits = ra._find_lui_use_pairs(code, 0x80000000, 0x801287B0, "t")
    assert [(h.lui_address, h.use_kind) for h in hits] == [(0x80000000, "ADDIU"), (0x80000008, "ORI")]
    # low half < 0x8000: both forms pair with the plain high half
    code = _mips(ra.OP_LUI, 0, 4, 0x8012) + _mips(ra.OP_ADDIU, 4, 5, 0x6C80)
    assert [h.use_kind for h in ra._find_lui_use_pairs(code, 0, 0x80126C80, "t")] == ["ADDIU"]


def _mesh(chunks=2):
    body = bytearray(0x40)
    index = 0x110 + len(body)
    body += b"".join(struct.pack(">II", 0x10 * k, 0x20 * k) for k in range(chunks))
    tail = b"".join(struct.pack(">IIII", t, 0x110, 0, 0) for t in (0, 1, 1)) + struct.pack(">IIII", 2, index, 0, 0)
    raw = bytearray(0x110) + body + tail
    struct.pack_into(">IIII", raw, 0, ra.MESH_MAGIC, 0x11, len(raw) - 0x110, 0)
    struct.pack_into(">I", raw, 0x14, chunks)
    return bytes(raw)


def test_parse_mesh_asset_synthetic():
    m = ra.parse_mesh_asset(1, _mesh())
    assert m.valid and not m.notes
    assert m.index_table_type == 2 and m.index_entries == [(0, 0), (0x10, 0x20)]
    short = ra.parse_mesh_asset(2, bytes(16))
    assert not short.valid
    bad = bytearray(_mesh())
    bad[0] = 0x02
    assert not ra.parse_mesh_asset(3, bytes(bad)).valid


@pytest.fixture(scope="module")
def loaded_overlay1():
    if not ROM_PATH.exists():
        pytest.skip("owned RE2 N64 rom.z64 not cached")
    rom, _, _ = ri.load_rom(ROM_PATH)
    overlays = ri.read_overlays(rom)
    main = next(e for e in overlays if e.index == 1)
    overlay1 = main.decompress(rom)
    assert overlay1 is not None
    return overlay1, main.load_addr


@pytest.fixture(scope="module")
def asset_directory():
    if not ROM_PATH.exists():
        pytest.skip("owned RE2 N64 rom.z64 not cached")
    rom, _, _ = ri.load_rom(ROM_PATH)
    overlays = ri.read_overlays(rom)
    directory = ri.read_asset_directory(rom, overlays)
    by_index = {e.index: e for e in directory.entries}
    return rom, directory, by_index


def test_overlay_xrefs_find_character_tables(loaded_overlay1):
    overlay1, load_base = loaded_overlay1
    xrefs = ra.find_table_xrefs(overlay1, load_base)
    tables = {x.table_name for x in xrefs}
    assert "char_asset_table" in tables
    assert "pair_table" in tables


def test_overlay_xrefs_addresses_reproducible(loaded_overlay1):
    overlay1, load_base = loaded_overlay1
    xrefs = ra.find_table_xrefs(overlay1, load_base)
    char_xrefs = [x for x in xrefs if x.table_name == "char_asset_table"]
    pair_xrefs = [x for x in xrefs if x.table_name == "pair_table"]

    # These addresses are stable for the USA Rev 1 build.
    assert any(x.lui_address == 0x80031D34 for x in char_xrefs)
    assert any(x.lui_address == 0x80031E40 for x in char_xrefs)
    assert any(x.lui_address == 0x80087518 for x in pair_xrefs)
    assert any(x.lui_address == 0x800876E0 for x in pair_xrefs)
    assert any(x.lui_address == 0x8008788C for x in pair_xrefs)


def test_mesh_probe_header(asset_directory):
    rom, directory, by_index = asset_directory
    data = by_index[5599].decode(rom, directory.base)
    mesh = ra.parse_mesh_asset(5599, data)
    assert mesh.magic == 0x01410000
    assert mesh.version == 0x11
    assert mesh.body_size == len(data) - ra.MESH_HEADER_SIZE
    assert mesh.chunk_count == 13
    assert mesh.valid


def test_mesh_probe_tail_records(asset_directory):
    rom, directory, by_index = asset_directory
    data = by_index[5599].decode(rom, directory.base)
    mesh = ra.parse_mesh_asset(5599, data)
    assert len(mesh.tail_records) == 4
    assert mesh.tail_records[-1].record_type in (2, 3)
    assert mesh.index_table_offset is not None
    assert len(mesh.index_entries) == mesh.chunk_count


@needs_rom
def test_analyze_integration():
    report = ra.analyze(ROM_PATH, mesh_assets=[5599, 5600])
    assert report["source"]["overlay_1_size"] == 1172240
    assert any(x["table"] == "char_asset_table" for x in report["overlay_xrefs"])
    assert any(x["table"] == "pair_table" for x in report["overlay_xrefs"])
    assert len(report["mesh_probe"]) == 2
    assert all(p["valid"] for p in report["mesh_probe"])
