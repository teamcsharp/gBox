"""Tests for gbox/deadaim_inventory.py — Resident Evil - Dead Aim (PS2) disc identity (#2035).

Pure-Python checks over pinned disc facts; no SMB access required (ELF bytes are synthesized
except the pinned sha256 constant which documents the real owned image).
"""
from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gbox.deadaim_inventory as da


def _elf(entry: int = 0x100008) -> bytes:
    head = bytearray(64)
    head[0:4] = b"\x7fELF"
    head[4] = 1          # 32-bit
    head[5] = 1          # LE
    head[6] = 1          # EV_current
    struct.pack_into("<H", head, 18, 8)        # MIPS
    struct.pack_into("<I", head, 24, entry)    # e_entry
    return bytes(head)


def test_serial_constants_match_owned_disc():
    # owned USA CHD boots SLUS_206.69 v1.01 (VER in SYSTEM.CNF), NTSC
    assert da.SERIAL == "SLUS_206.69"
    assert da.GAME_ID == "f2b204a34366254b"


def test_pinned_boot_elf_sha256():
    # revision-guard anchor read from the owned CHD on this host (gbox-data/deadaim/inventory.json)
    assert da.BOOT_ELF_SHA256 == "030a18d56b1aa7ed735382022607d8e788771982326bdb1a46adf6f7f83a7a49"
    assert da.BOOT_ELF_SIZE == 2362892


def test_system_cnf_parses_boot2():
    cnf = da.system_cnf("BOOT2 = cdrom0:\\SLUS_206.69;1\r\nVER = 1.01\r\nVMODE = NTSC\r\n")
    assert cnf["boot_file"] == "SLUS_206.69"
    assert cnf["VER"] == "1.01"
    assert cnf["VMODE"] == "NTSC"


def test_elf_info_accepts_mips_and_hashes():
    data = _elf()
    info = da.elf_info(data)
    assert info["sha256"] == hashlib.sha256(data).hexdigest()
    assert info["e_machine"] == 8
    assert info["e_entry"] == hex(0x100008)


def test_elf_info_rejects_non_elf():
    for bad in (b"AAAA" + b"\0" * 60, b"\x7fELF" + b"\0" * 60):
        try:
            da.elf_info(bad)
        except ValueError:
            continue
        raise AssertionError("expected ValueError")


def test_elf_info_rejects_non_mips():
    data = bytearray(_elf())
    struct.pack_into("<H", data, 18, 62)  # x86-64
    try:
        da.elf_info(bytes(data))
    except ValueError:
        return
    raise AssertionError("expected ValueError for non-MIPS e_machine")


def test_blob_probe_magics_and_names():
    head = b"fpk\0" + b"\0" * 4 + b"\0" * 512 + b"stagescript/st00z000/pack_uc.dat\0"
    p = da.blob_probe(head)
    assert p["magic"] == (b"fpk\0" + b"\0" * 4).hex()
    # the sample scanner keeps the run up to the NUL, same as the real disc probe
    assert any("pack_uc.dat" in s for s in p["name_sample"])
    afs = b"AFS\0" + struct.pack("<I", 3) + b"\0" * 40
    assert da.blob_probe(afs)["container"] == "AFS"
