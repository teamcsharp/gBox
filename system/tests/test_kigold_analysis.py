"""Tests for gbox.kigold_analysis — pinned to the exact owned KI Gold build.

ROM-dependent tests skip unless the normalized rom.z64 is present at
GBOX_KIGOLD_ROM (default ~/gbox-cache/407771fca8e3cd17/rom.z64); the loaded
image is hash-checked against the No-Intro Rev 2 build.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from gbox.kigold_analysis import (
    dis,
    entry_trace,
    probe_frame_tables,
    probe_luts,
    probe_referents,
    u32,
)

ROM = Path(os.environ.get(
    "GBOX_KIGOLD_ROM",
    Path.home() / "gbox-cache" / "407771fca8e3cd17" / "rom.z64",
))
ROM_SHA256 = "f80cae340efadf5725cd0f75441addb9186be9860267595be2b4a2d317b05f8a"
SIZE_LADDER = [9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83,
               99, 115, 131, 163, 195, 227, 258]

needs_rom = pytest.mark.skipif(not ROM.exists(), reason="rom.z64 cache absent")


@pytest.fixture(scope="module")
def rom() -> bytes:
    data = ROM.read_bytes()
    assert hashlib.sha256(data).hexdigest() == ROM_SHA256, "not the Rev 2 build"
    return data


# ---------------------------------------------------------------- disassembler

def test_dis_vectors():
    assert dis(0x1420FFFD, 0x80000400) == ("b", "bne", "at, zero, 0x800003f8")
    assert dis(0x25080010, 0x80000404) == (" ", "addiu", "t0, t0, 16")
    assert dis(0x10000013, 0x80000408) == ("b", "beq", "zero, zero, 0x80000458")
    assert dis(0x3C088000, 0) == (" ", "lui", "t0, 0x8000")
    assert dis(0x8D240000, 0) == (" ", "lw", "a0, 0(t1)")
    assert dis(0xAD000004, 0) == (" ", "sw", "zero, 4(t0)")
    assert dis(0x03E00008, 0) == ("r", "jr", "ra")
    assert dis(0x00000000, 0)[:2] == (" ", "sll")
    assert dis(0x0C100400, 0x80001000)[0] == "c"  # jal
    assert dis(0x42000018, 0)[0] == "x"  # eret


# -------------------------------------------------------------- entry trace

@needs_rom
def test_entry_trace_boot_stub(rom):
    trace = entry_trace(rom)
    first = trace["insns"][0]
    assert first[0] == 0x80000400
    assert first[2:] == ("bne", "at, zero, 0x800003f8")
    addrs = [v for v, _, _, _ in trace["insns"]]
    assert 0x80000404 in addrs, "branch fallthrough must be followed"
    assert 0x80000454 in addrs, "the boot stub's forward jump must be followed"
    assert trace["count"] >= 6


# ----------------------------------------------------------- frame tables

@needs_rom
def test_known_frame_tables_bytes(rom):
    # Byte-exact pinning of the two inventory leads.
    assert [hex(u32(rom, o)) for o in (0x992D58, 0x992D5C)] == \
        ["0x3636fe", "0x3a36fe"]
    assert [hex(u32(rom, o)) for o in (0x9AA85C, 0x9AA860)] == \
        ["0x5454fe", "0x5854fe"]


@needs_rom
def test_frame_table_runs(rom):
    runs = {r["offset"]: r for r in probe_frame_tables(rom)["runs"]}

    a = runs["0x992d58"]
    assert a["tag"] == "0x36fe" and a["count"] == 7
    assert a["ladder_start"] == "0x36" and a["ladder_first"] is True
    assert a["all_u32_in_rom"] and a["all_blocks_in_dense"]
    first = a["entries"][0]
    assert first["u32_target"] == "0x3636fe"
    assert first["block_target"] == "0x360000"
    assert 6.5 < first["u32_entropy"] < 8.5  # compressed frame data
    assert 7.5 < first["block_entropy"] < 8.5

    b = runs["0x9aa85c"]
    assert b["tag"] == "0x54fe" and b["count"] == 15
    assert b["all_u32_in_rom"] and b["all_blocks_in_dense"]

    assert runs["0x9abd4c"]["tag"] == "0x36fe" and runs["0x9abd4c"]["count"] == 4
    assert runs["0x9ac55e"]["tag"] == "0x36fe" and runs["0x9ac55e"]["count"] == 4
    assert runs["0x9ac55e"]["ladder_start"] == "0x7a"
    assert runs["0x9ac646"]["tag"] == "0x24fe" and runs["0x9ac646"]["count"] == 11
    assert runs["0x99daaa"]["tag"] == "0x18fe" and runs["0x99daaa"]["count"] == 6

    # 0x12fe rows do not resolve to ROM offsets under either reading;
    # recorded as an open question for the Ghidra xref pass.
    rows = [r for r in runs.values() if r["tag"] == "0x12fe"]
    assert len(rows) == 8
    assert all(r["count"] == 6 for r in rows)
    assert not any(r["all_u32_in_rom"] for r in rows)


# -------------------------------------------------------------------- LUTs

@needs_rom
def test_size_ladder_lut(rom):
    luts = probe_luts(rom)
    assert luts["size_ladder"]["values"] == SIZE_LADDER
    assert luts["size_ladder"]["monotonic_increasing"] is True
    assert luts["shuffle_lut"]["bytes"][:6] == ["0x10", "0x11", "0x12",
                                                "0x0", "0x8", "0x7"]


# ------------------------------------------- negative referent scan

@needs_rom
def test_no_absolute_table_referents(rom):
    refs = probe_referents(rom)
    for table, info in refs["tables"].items():
        assert info["absolute_u32_hits"] == [], table
