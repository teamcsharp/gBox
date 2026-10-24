"""Focused tests for the Capcom Generations (Europe) (Disc 1) PS1 inventory."""

import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gbox import capcom_generations as cg  # noqa: E402

BIN = os.environ.get("CAPCOM_GEN_BIN", "/home/ehm_eckx/.bin")

# The published PS-X EXE header: 0x00 magic, 0x10 the ten header words,
# 0x38 the five saved registers, 0x4C the region/licence string.
SPEC_PC0 = 0x8005A38C
SPEC_T_ADDR = 0x80010000
SPEC_T_SIZE = 0x1000
SPEC_SP = 0x801FFFF0


def test_owned_source_identity_is_pinned():
    assert cg.OWNED_GAME_ID == "5a67d462464d2460"
    assert cg.OWNED_SOURCE_SHA256 == "6159ec05950ee85bc202250bdec5b4f251fe23ecd01ac4d9e6a89165b9d14aa5"
    assert cg.OWNED_BOOT_EXECUTABLE == "SLES_018.81"
    assert cg.OWNED_PLATFORM == "psx"


def _spec_header():
    """PS-X EXE header with the published Sony field offsets (not parser-derived)."""
    h = bytearray(0x800)
    h[0:8] = b"PS-X EXE"
    struct.pack_into("<10I", h, 0x10,
                     SPEC_PC0, 0x0, SPEC_T_ADDR, SPEC_T_SIZE,
                     0x0, 0x0, 0x0, 0x0, SPEC_SP, 0x0)
    struct.pack_into("<5I", h, 0x38, 0x801FFF00, 0x801FFF10, 0x0, 0x0, 0x0)
    h[0x4C:0x4C + len(b"test region")] = b"test region"
    return bytes(h)


def test_psx_exe_header_matches_published_layout():
    parsed = cg.parse_psx_exe(_spec_header() + b"\x00" * SPEC_T_SIZE)
    assert parsed["magic"] == "PS-X EXE"
    assert parsed["pc0"] == SPEC_PC0
    assert parsed["gp0"] == 0
    assert parsed["t_addr"] == SPEC_T_ADDR
    assert parsed["t_size"] == SPEC_T_SIZE
    assert parsed["d_addr"] == 0
    assert parsed["d_size"] == 0
    assert parsed["b_addr"] == 0
    assert parsed["b_size"] == 0
    assert parsed["sp"] == SPEC_SP
    assert parsed["stack_size"] == 0
    assert parsed["saved_sp"] == 0x801FFF00
    assert parsed["saved_fp"] == 0x801FFF10
    assert parsed["saved_gp"] == 0
    assert parsed["ret"] == 0
    assert parsed["dest"] == 0
    assert parsed["region"] == "test region"
    assert parsed["payload_size"] == SPEC_T_SIZE


def test_psx_exe_registers_are_not_read_from_the_header_words():
    """The saved registers live at 0x38, not at 0x30 (the stack word)."""
    parsed = cg.parse_psx_exe(_spec_header() + b"\x00" * SPEC_T_SIZE)
    assert parsed["sp"] == SPEC_SP
    assert parsed["saved_sp"] != SPEC_SP
    assert parsed["saved_fp"] == 0x801FFF10


def test_psx_exe_rejects_short_and_bad_magic():
    with pytest.raises(ValueError):
        cg.parse_psx_exe(b"PS-X EXE" + b"\x00" * 16)
    with pytest.raises(ValueError):
        cg.parse_psx_exe(b"NOT-AN-EXE" + b"\x00" * 0x800)


def test_psx_exe_rejects_t_size_beyond_the_payload():
    with pytest.raises(ValueError):
        cg.parse_psx_exe(_spec_header() + b"\x00" * 16)


@pytest.mark.skipif(not os.path.exists(BIN), reason="owned disc image not on this host")
def test_owned_disc_manifest_lists_the_boot_executable():
    man = cg.build_manifest(BIN, hash_files=True)
    assert man["file_count"] >= 1
    names = [f["name"].upper() for f in man["files"]]
    assert any(n.startswith(cg.OWNED_BOOT_EXECUTABLE) for n in names), names[:10]
    boot = [f for f in man["files"] if f["name"].upper().startswith(cg.OWNED_BOOT_EXECUTABLE)][0]
    assert boot["psx_exe"]["magic"] == "PS-X EXE"
    assert len(boot["sha256"]) == 64
    assert man["source_sha256"] == cg.OWNED_SOURCE_SHA256
    print("files", man["file_count"], man["extensions"])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
