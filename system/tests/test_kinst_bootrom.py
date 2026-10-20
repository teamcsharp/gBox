"""Focused tests for gbox.kinst_bootrom (Killer Instinct boot ROM, request #1372)."""

import os
import hashlib
import struct
from pathlib import Path

import pytest

from gbox import kinst_bootrom as kb


def test_memory_map_and_ide_registers():
    assert kb.RAM == (0x00000000, 0x00080000)
    assert kb.RAM2 == (0x08000000, 0x08800000)
    assert kb.ROM == (0x1FC00000, 0x1FC80000)
    assert kb.DEVICES == (0x10000000, 0x10001000)
    # IDE task file at 0x10000100 (cs0) / 0x10000170 (cs1); KSEG1 = 0xb00001xx.
    assert kb.kseg1(0x10000100) == 0xB0000100
    assert kb.kseg1(0x10000170) == 0xB0000170
    assert kb.device_write_is_ide(0x10000100) and kb.device_write_is_ide(0x10000170)
    assert not kb.device_write_is_ide(0x10000080)  # vram_control
    assert not kb.device_write_is_ide(0x10000000)  # reset strobe


def test_bootstrap_header_parses():
    rom = bytearray(0x2000)
    struct.pack_into("<H", rom, kb.STREAM_OFFSET, 0x7262)
    rom[kb.STREAM_OFFSET + 2] = 3
    rom[kb.STREAM_OFFSET + 3] = 0
    struct.pack_into("<I", rom, kb.STREAM_OFFSET + 4, 0x32CB0)
    struct.pack_into("<I", rom, kb.STREAM_OFFSET + 8, 0x88000000)
    h = kb.bootstrap_header(bytes(rom))
    assert h["serial_magic"] == kb.SERIAL_MAGIC == 0x7262
    assert h["block_count"] == 3 and h["sentinel"] == 0
    assert h["first_block_size"] == 0x32CB0
    assert h["entry_point"] == kb.SECOND_STAGE_ENTRY == 0x88000000
    assert h["load_phys"] == 0x08000000


def test_bootstrap_header_rejects_short_rom():
    with pytest.raises(ValueError):
        kb.bootstrap_header(b"\x00" * 8)


CACHE = Path(os.environ.get("GBOX_KINST_CACHE", str(Path.home() / "gBox_alt/gbox-cache" / "6d3a16492c9b09ee")))


@pytest.mark.skipif(not (CACHE / "ki-l15d.u98").exists(), reason="owned boot ROM not staged")
def test_owned_boot_rom_bootstrap_header():
    rom = (CACHE / "ki-l15d.u98").read_bytes()
    assert len(rom) == kb.BOOT_ROM_SIZE
    assert hashlib.sha1(rom).hexdigest() == kb.BOOT_ROM_SHA1
    h = kb.bootstrap_header(rom)
    assert h["serial_magic"] == 0x7262
    assert h["block_count"] == 3
    assert h["sentinel"] == 0
    assert h["first_block_load"] == 0x88000000  # second stage entry in RAM2 KSEG0
    assert h["load_phys"] == 0x08000000        # start of the 8 MiB second RAM bank


@pytest.mark.parametrize('offset',[-12,-1,5,100])
def test_invalid_header_offset_is_rejected(offset):
    with pytest.raises(ValueError): kb.bootstrap_header(bytes(16),offset)


def test_explicit_header_offset_reads_only_selected_bytes():
    raw=b'ignored!'+bytes.fromhex('62720300b02c030000000088')
    header=kb.bootstrap_header(raw,8)
    assert header['first_block_size']==0x32cb0
    assert header['first_block_load']==0x88000000
