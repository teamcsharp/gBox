"""Focused checks for the Ghidra gameplay-state adapters (gBox request #2834).

The adapters locate the DOA2 (Dreamcast SH4) and RE4 Mercenaries (GameCube PPC)
gameplay-state addresses that the emulator bots read to skip title screens,
waiting and stalling.  These checks pin the adapter sources and, when the owned
binaries are present, the bytes behind the documented addresses.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import pytest

SYSTEM = Path(__file__).resolve().parents[1]
ADAPTERS = SYSTEM / "adapters" / "ghidra"

DOA2_BIN = Path(os.environ.get(
    "GBOX_DOA2_BIN",
    Path.home() / "gBox_alt/gbox-doa2-animation/1ST_READ.BIN",
))
DOA2_SHA256 = "27a014aeda35983df749f7d575bbddbea3f1ffd1f7776194ef503108c20c97e1"
DOA2_BASE = 0x8C010000
DOA2_CONFIRM = 0x8C0262E0
DOA2_COMMIT = 0x8C02A1CA
DOA2_RANDOM = 0x8C120CF0
DOA2_SLOT_TABLE = 0x8C239D50
DOA2_COSTUME_TABLE = 0x8C239D64

RE4_PLAYER = 0x802B3044
RE4_EMMGR = 0x8027DF20
RE4_GLOBAL = 0x802B2280
RE4_MERC_TIMER = 0x80279308
RE4_MERC_STATE = 0x8021392C

# The headless Ghidra run that exercises the adapters against the real binary.
DOA2_LOG = Path(os.environ.get("GBOX_R2834_DOA2_LOG", ""))

needs_doa2 = pytest.mark.skipif(not DOA2_BIN.exists(), reason="DOA2 executable not in cache")
needs_log = pytest.mark.skipif(not DOA2_LOG.is_file(), reason="headless Ghidra run log not set")


@pytest.fixture(scope="module")
def doa2_bytes() -> bytes:
    data = DOA2_BIN.read_bytes()
    assert hashlib.sha256(data).hexdigest() == DOA2_SHA256, "not the pinned DOA2 build"
    return data


@pytest.fixture(scope="module")
def sources() -> dict[str, str]:
    out: dict[str, str] = {}
    for name in ("FindGameplayState.java", "DOA2GameState.java", "RE4MercGameState.java"):
        path = ADAPTERS / name
        assert path.is_file(), f"missing adapter {name}"
        out[name] = path.read_text(encoding="utf-8")
    return out


def test_adapters_present(sources):
    assert set(sources) == {"FindGameplayState.java", "DOA2GameState.java", "RE4MercGameState.java"}


def test_no_absolute_address_is_offset_by_the_load_base(sources):
    """The load base was added to addresses that were already absolute, which pushed
    every lookup outside the mapped image and made it miss silently."""
    doa2 = sources["DOA2GameState.java"]
    for address in (DOA2_CONFIRM, DOA2_COMMIT, DOA2_RANDOM):
        for spelling in (f"0x{address:X}", f"0x{address:X}L", f"0x{address:x}", f"0x{address:x}L"):
            assert f"DOA2_BASE + {spelling}" not in doa2, f"{spelling} is offset by the load base"
            assert f"DOA2_BASE+{spelling}" not in doa2, f"{spelling} is offset by the load base"


def test_doa2_addresses_are_documented(sources):
    doa2 = sources["DOA2GameState.java"]
    for address in (DOA2_CONFIRM, DOA2_COMMIT, DOA2_RANDOM, DOA2_SLOT_TABLE, DOA2_COSTUME_TABLE):
        assert f"0x{address:X}" in doa2 or f"0x{address:x}" in doa2, f"0x{address:X} is not documented"


def test_confirm_handler_resolves_through_its_containing_function(sources):
    """0x8C0262E0 is a code block inside FUN_8c025dfc, not a function entry, so the
    adapter must ask for the containing function instead of the function at the address."""
    doa2 = sources["DOA2GameState.java"]
    assert "getFunctionContaining(searchAddr)" in doa2
    assert "getFunctionAt(searchAddr)" not in doa2
    assert "Confirm handler function not found at expected location" not in doa2


def test_re4_detection_uses_the_ppc_elf_machine_type(sources):
    """The disc id lives in the DOL header, not the ELF, so the read from 0x80000000
    always missed and the whole script degraded to no-ops."""
    re4 = sources["RE4MercGameState.java"]
    assert re.search(r"e_?machine\s*==\s*(20|0x14)", re4, re.IGNORECASE) or "EM_PPC" in re4, \
        "the RE4 script does not detect the PPC ELF machine type"
    assert re.search(r"e_?machine", re4, re.IGNORECASE), "the RE4 script never reads the ELF machine type"


def test_re4_player_base_is_a_literal(sources):
    re4 = sources["RE4MercGameState.java"]
    assert re.search(r"[A-Z_]*PLAYER[A-Z_]*\s*=\s*0x802B3044", re4), \
        "the player base is not the literal 0x802B3044"
    assert not re.search(r"=\s*0x802B9780\s*-\s*0x673C", re4), \
        "the player base is still computed by subtraction"


def test_re4_addresses_are_documented(sources):
    re4 = sources["RE4MercGameState.java"]
    for address in (RE4_EMMGR, RE4_PLAYER, RE4_GLOBAL, RE4_MERC_TIMER, RE4_MERC_STATE):
        assert f"0x{address:X}" in re4, f"0x{address:X} is not documented"


def test_doa2_flat_binary_is_detected(sources):
    """The build has no ELF header and an image base of 0, so detection has to use the
    load address and the SH4 startup marker; the marker string also sits inside the
    executable block, which the old scan skipped."""
    finder = sources["FindGameplayState.java"]
    assert "isDreamcastFlatBinary" in finder
    assert "|| block.isExecute()) continue;" not in finder


@needs_doa2
def test_doa2_boot_header_marks_the_sh4_startup_word(doa2_bytes):
    assert doa2_bytes[0:2] == b"\x09\x00"


@needs_doa2
def test_doa2_documented_code_addresses_hold_code(doa2_bytes):
    for address in (DOA2_CONFIRM, DOA2_COMMIT, DOA2_RANDOM):
        offset = address - DOA2_BASE
        assert 0 <= offset < len(doa2_bytes), f"0x{address:X} is not file-backed"
        window = doa2_bytes[offset:offset + 4]
        assert window != b"\x00\x00\x00\x00", f"0x{address:X} is erased"
        assert any(window), f"0x{address:X} is empty"


@needs_doa2
def test_doa2_data_addresses_sit_in_the_work_ram_window(doa2_bytes):
    for address in (DOA2_SLOT_TABLE, DOA2_COSTUME_TABLE):
        assert 0x8C000000 <= address <= 0x8CFFFFFF, f"0x{address:X} is outside work RAM"


@needs_log
def test_headless_run_detects_doa2_and_resolves_the_confirm_handler():
    log = DOA2_LOG.read_text(encoding="utf-8", errors="replace")
    assert "Detected game ID: DOA2" in log, "the flat Dreamcast build was not detected"
    assert f"confirm_handler: 0x{DOA2_CONFIRM:X}" in log, "the confirm handler did not resolve"
    assert "Confirm handler function not found" not in log
    assert f"commit_routine: 0x{DOA2_COMMIT:X}" in log
    assert f"random_address: 0x{DOA2_RANDOM:X}" in log


@needs_log
def test_headless_re4_run_reports_the_ppc_disc_id():
    """The RE4 GameCube ELF carries no G4BE08 string; the disc id lives in the DOL
    header, so the script has to recognise the PPC ELF image itself."""
    log = Path(os.environ.get("GBOX_R2834_RE4_LOG", ""))
    if not log.is_file():
        pytest.skip("headless RE4 run log not set")
    text = log.read_text(encoding="utf-8", errors="replace")
    assert "G4BE08" in text, "the RE4 script did not identify the GameCube disc id"
    assert "Game ID not found in expected location" not in text
