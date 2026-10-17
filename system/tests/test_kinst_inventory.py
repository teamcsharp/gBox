"""Focused tests for gbox.kinst_inventory (Killer Instinct arcade, request #1372)."""

import hashlib
import os
import shutil
import struct
import zipfile
from pathlib import Path

import pytest

from gbox import kinst_inventory as ki

# Verbatim `chdman info` (0.264) output for the owned collections/Mame/roms/kinst/kinst.chd.
CHDMAN_INFO = """chdman - MAME Compressed Hunks of Data (CHD) manager 0.264 (unknown)
Input file:   kinst.chd
File Version: 5
Logical size: 131,076,608 bytes
Hunk Size:    4,096 bytes
Total Hunks:  32,002
Unit Size:    512 bytes
Total Units:  256,009
Compression:  lzma (LZMA), zlib (Deflate), huff (Huffman), flac (FLAC)
CHD size:     93,887,853 bytes
Ratio:        71.6%
SHA1:         81d833236e994528d1482979261401b198d1ca53
Data SHA1:    a37a2c5e52ea936a715210d237874dd573bb002f
Metadata:     Tag='GDDD'  Index=0  Length=34 bytes
              CYLS:419,HEADS:13,SECS:47,BPS:512.
"""


def _zip(path: Path, members: dict) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


def test_mame_reference_tables():
    assert len(ki.BOOT_ROM_SHA1) == 5 and len(ki.SOUND_ROM_SHA1) == 8
    assert ki.DEFAULT_BIOS in ki.BOOT_ROM_SHA1
    assert set(ki.REQUIRED_FOR_DEFAULT_BIOS) == {ki.DEFAULT_BIOS, *ki.SOUND_ROM_SHA1}
    assert all(len(h) == 40 and int(h, 16) >= 0 for h in ki.MAME_ROMS.values())
    assert len(ki.MAME_CHD_SHA1) == 40


def test_audit_zip_default_bios_vs_parent_set(tmp_path):
    blobs = {"boot.a": b"A" * 16, "boot.b": b"B" * 16, "snd.1": b"1" * 16, "snd.2": b"2" * 16}
    ref = {n: hashlib.sha1(d).hexdigest() for n, d in blobs.items()}
    req = ("boot.a", "snd.1", "snd.2")
    minimal = _zip(tmp_path / "minimal.zip", {k: blobs[k] for k in req})
    a = ki.audit_zip(minimal, ref=ref, required=req)
    assert a.boots_default and not a.complete_parent_set
    assert (a.missing, a.unknown, a.wrong_sha1) == (["boot.b"], [], [])
    assert a.sha256 == hashlib.sha256(minimal.read_bytes()).hexdigest()
    full = ki.audit_zip(_zip(tmp_path / "full.zip", blobs), ref=ref, required=req)
    assert full.boots_default and full.complete_parent_set
    bad = _zip(tmp_path / "bad.zip", {**blobs, "snd.2": b"x", "extra.bin": b"e"})
    b = ki.audit_zip(bad, ref=ref, required=req)
    assert b.wrong_sha1 == ["snd.2"] and b.unknown == ["extra.bin"]
    assert not b.boots_default and not b.complete_parent_set


def test_parse_chdman_info():
    info = ki.parse_chdman_info(CHDMAN_INFO)
    assert info["sha1"] == ki.MAME_CHD_SHA1
    assert info["data_sha1"] == "a37a2c5e52ea936a715210d237874dd573bb002f"
    assert info["file_version"] == 5 and info["unit_size"] == 512
    assert info["logical_size"] == 131_076_608 and info["chd_size"] == 93_887_853
    geo = (info["cyls"], info["heads"], info["secs"], info["bps"])
    assert geo == (419, 13, 47, 512)
    assert info["cyls"] * info["heads"] * info["secs"] == info["total_units"] == 256_009
    assert info["total_units"] * info["bps"] == info["logical_size"]


def test_banner_and_disk_runs(tmp_path):
    lines = ["Killer Instinct v1.0", "", "31/10/94 12:35", "", "(c) Copyright Rare Ltd 1994"]
    s0 = b"".join(ln.ljust(31).encode() + b"\n" for ln in lines).ljust(512, b"\0")
    zero, data = bytes(512), b"\x01" * 512
    raw = tmp_path / "disk.raw"
    raw.write_bytes(s0 + zero + data + data + zero + data)
    assert ki.disk_runs(raw) == [(0, 0), (2, 3), (5, 5)]
    assert ki.banner(s0) == ["Killer Instinct v1.0", "31/10/94 12:35", "(c) Copyright Rare Ltd 1994"]


def test_entropy_and_regions():
    assert ki.entropy(bytes(range(256)) * 4) == pytest.approx(8.0)
    assert ki.entropy(bytes(64)) == 0.0
    prof = [{"block": 0, "entropy": 6.1, "zero_frac": 0.01},
            {"block": 1, "entropy": 6.5, "zero_frac": 0.0},
            {"block": 2, "entropy": 7.99, "zero_frac": 0.01},
            {"block": 3, "entropy": 0.0, "zero_frac": 1.0}]
    regions = ki.classify_regions(prof, block=16)
    assert [(r["kind"], r["start"], r["end"], r["blocks"]) for r in regions] == [
        ("structured", 0, 32, 2), ("high_entropy", 32, 48, 1), ("empty", 48, 64, 1)]


def test_boot_rom_reset_jump_and_ide_sites():
    # Word 0 of the owned ki-l15d.u98 is 0x0bf000e2, i.e. `j 0xbfc00388`.
    assert ki.decode_jump(0x0BF000E2, ki.BOOT_ROM_BASE) == 0xBFC00388
    assert ki.decode_jump(0x3C08B000, ki.BOOT_ROM_BASE) is None
    rom = struct.pack("<4I", 0x0BF000E2, 0, 0x3C08B000, 0x3C08B001) + b"\xff" * 16
    prof = ki.boot_rom_profile(rom)
    assert prof["reset_jump"] == "0xbfc00388"
    assert prof["ide_lui_sites"] == [{"addr": "0xbfc00008", "rt": 8}]
    assert prof["used_bytes"] == 16 and prof["size"] == 32


def test_core_has_driver_needs_whole_short_name(tmp_path):
    core = tmp_path / "core.so"
    core.write_bytes(b"\0kinst2\0kinst2uk\0Killer Instinct (E)(1995)\0")
    assert not ki.core_has_driver(core)
    core.write_bytes(b"\0kinst2\0kinst\0Killer Instinct\0")
    assert ki.core_has_driver(core)


def test_ascii_hits():
    hits = ki.ascii_hits(b"xxJAGOxxJago", ["JAGO", "EYEDOL"])
    assert hits == {"JAGO": 1, "Jago": 1, "EYEDOL": 0, "Eyedol": 0}


CACHE = Path(os.environ.get("GBOX_KINST_CACHE", str(Path.home() / "gbox-cache" / ki.GAME_ID)))


@pytest.mark.skipif(not (CACHE / "kinst.chd").exists() or shutil.which("chdman") is None,
                    reason="owned kinst CHD not staged or chdman missing")
def test_owned_chd_matches_mame():
    info = ki.chd_identity(CACHE / "kinst.chd")
    assert info["sha1"] == ki.MAME_CHD_SHA1
    assert (info["cyls"], info["heads"], info["secs"], info["bps"]) == (419, 13, 47, 512)
    raw = CACHE / "kinst.raw"
    if raw.exists():
        with open(raw, "rb") as f:
            assert ki.banner(f.read(512))[0] == "Killer Instinct v1.0"
