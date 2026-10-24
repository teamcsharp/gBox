"""Tests for the Super Bust-A-Move (PS2) mode-select lock inventory."""
from __future__ import annotations

import hashlib
import os
import struct

import pytest

from gbox import sbam_modeselect as mod

ELF = os.path.expanduser(
    "~/gBox_alt/gbox-cache/ps2/6cd93f2e36885f31/inventory/SLUS_201.15")


def _elf():
    if not os.path.exists(ELF):
        pytest.skip("owned Super Bust-A-Move executable is not on this host")
    with open(ELF, "rb") as handle:
        return handle.read()


def _word(elf, vaddr):
    return struct.unpack_from("<I", elf, mod.vaddr_to_offset(vaddr))[0]


def _cstr(elf, vaddr):
    off = mod.vaddr_to_offset(vaddr)
    return elf[off:elf.index(b"\x00", off)].decode("latin1")


def test_profile_is_not_verified():
    prof = mod.profile()
    assert prof["verified"] is False
    assert prof["complete_unlock_profile"] is False
    assert prof["game_id"] == mod.GAME_ID
    assert prof["findings"]
    assert prof["unverified_note"]


def test_module_has_no_write_or_launch_api():
    with open(mod.__file__, "r", encoding="utf-8") as handle:
        src = handle.read()
    for token in ("write_memory", "freeze_memory", "launch_game", "mcp__gbox",
                  "poke(", "read_memory"):
        assert token not in src, token


def test_executable_digest_matches():
    assert hashlib.sha256(_elf()).hexdigest() == mod.EXECUTABLE_SHA256


def test_instruction_words_match_executable():
    elf = _elf()
    for row in mod.INSTRUCTIONS:
        assert _word(elf, row["vaddr"]) == row["word"], row


def test_panel_global_load_targets_the_documented_global():
    word = _word(_elf(), 0x001191C4)
    assert (word >> 26) & 0x3F == 0x23          # lw
    assert (word & 0xFFFF) == 0x1640
    assert (0x570000 + (word & 0xFFFF)) == mod.PANEL_GLOBAL_VADDR


def test_branch_target_is_the_narrow_panel():
    pc = 0x001191CC
    word = _word(_elf(), pc)
    assert (word >> 26) & 0x3F == 5             # bne
    offset = word & 0xFFFF
    if offset & 0x8000:
        offset -= 0x10000
    assert pc + 4 + offset * 4 == 0x00119248


def test_format_strings_match_executable():
    elf = _elf()
    assert _cstr(elf, mod.LOCK_SITE["format_selectable_vaddr"]) == \
        "ZONE %c (A-%c selectable)"
    assert _cstr(elf, mod.LOCK_SITE["format_only_a_vaddr"]) == \
        "ZONE %c (only A selectable)"


def test_panel_global_is_zero_on_disk():
    assert _word(_elf(), mod.PANEL_GLOBAL_VADDR) == mod.PANEL_GLOBAL_ON_DISK
    assert mod.PANEL_GLOBAL_ON_DISK == 0


def test_ev_names_present_in_executable():
    elf = _elf()
    for row in mod.EV_NAMES:
        assert _cstr(elf, row["vaddr"]) == row["name"]
