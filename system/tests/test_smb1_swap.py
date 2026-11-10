"""Tests for gbox.smb1_swap (SMB1 CHR writer)."""
from __future__ import annotations

import hashlib
import os
import pathlib

import pytest

from gbox import smb1_swap
from gbox.smb1_inventory import OFFSETS

ROM = pathlib.Path(os.environ.get("SMB1_ROM", pathlib.Path.home() / "gbox-cache" / "49b6a2f65aca26a2"
                                  / "rom" / "Super Mario Bros. (World).nes"))
ROM_SHA256 = "f61548fdf1670cffefcc4f0b7bdcdd9eaba0c226e3b74f8666071496988248de"  # owned ROM bytes


def _synthetic(tmp_path):
    """Hand-built NROM-256: tile 1 = all index 1, tile 2 = all index 2, tile 3 = all index 3."""
    prg = bytearray(32768)
    o = OFFSETS["PlayerGraphicsTable"]
    prg[o: o + 8] = bytes([1, 0xFC, 0xFC, 0xFC, 0xFC, 0xFC, 0xFC, 0xFC])
    e = OFFSETS["EnemyGraphicsTable"]
    prg[e: e + 6] = bytes([3, 0xFC, 0xFC, 0xFC, 0xFC, 0xFC])
    chr_ = bytearray(8192)
    chr_[16:24] = b"\xff" * 8          # tile 1: low plane set -> value 1
    chr_[32 + 8: 32 + 16] = b"\xff" * 8  # tile 2: high plane -> value 2
    chr_[48: 64] = b"\xff" * 16        # tile 3: both planes -> value 3
    hdr = b"NES\x1a" + bytes([2, 1, 0, 0]) + bytes(8)
    p = tmp_path / "synth.nes"
    p.write_bytes(hdr + bytes(prg) + bytes(chr_))
    return p


def test_synthetic_swap_changes_only_target_tile(tmp_path):
    src = _synthetic(tmp_path)
    out = tmp_path / "mod.nes"
    r = smb1_swap.write_mod(str(src), str(out), 0, 0)
    a, b = src.read_bytes(), out.read_bytes()
    chr0 = 16 + 32768
    assert r["tile_map"] == {1: 3}
    assert b[chr0 + 16: chr0 + 32] == b"\xff" * 16           # tile 1 now equals tile 3's bytes
    assert [i for i in range(len(a)) if a[i] != b[i]] == list(range(chr0 + 24, chr0 + 32))
    assert r["mod_sha256"] == hashlib.sha256(b).hexdigest() != r["source_sha256"]


def test_refuses_overwrite_and_unchanged_donor(tmp_path):
    src = _synthetic(tmp_path)
    with pytest.raises(ValueError):
        smb1_swap.write_mod(str(src), str(src), 0, 0)
    with pytest.raises(ValueError):
        smb1_swap.write_mod(str(src), str(tmp_path / "x.nes"), 99, 0)
    data = bytearray(src.read_bytes())
    data[16 + OFFSETS["EnemyGraphicsTable"]] = 1  # donor == player tile -> no change
    src.write_bytes(bytes(data))
    with pytest.raises(ValueError):
        smb1_swap.write_mod(str(src), str(tmp_path / "x.nes"), 0, 0)


def test_owned_rom_swap_preserves_original(tmp_path):
    if not ROM.exists():
        pytest.skip("owned ROM missing")
    before = ROM.read_bytes()
    assert hashlib.sha256(before).hexdigest() == ROM_SHA256
    r = smb1_swap.write_mod(str(ROM), str(tmp_path / "mod.nes"), 0, 0)
    assert r["tile_map"] == {2: 170, 3: 171, 4: 172, 5: 173}
    assert r["changed_bytes"] <= 16 * 4 and r["changed_bytes"] > 0
    assert ROM.read_bytes() == before
