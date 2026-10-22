"""WBFS v1 reader tests: synthetic fixture (always) + the real Metroid Other M image (when mounted)."""
import os
import struct
from pathlib import Path

import pytest

from gbox.formats import disc
from gbox.formats.wbfs import WBFS

REAL = Path("/mnt/gbox/hyperspin/Arcade/collections/Nintendo Wii/roms/Metroid - Other M (USA).wbfs")


def make_wbfs(path, sec_shift=21):
    hd_shift, sec = 9, 1 << sec_shift
    iso = bytearray(2 * sec)
    iso[0:6] = b"RTEST1"
    iso[0x18:0x1C] = struct.pack(">I", 0x5D1C9EA3)
    iso[0x20:0x20 + 4] = b"Test"
    iso[0x40000:0x40008] = struct.pack(">II", 1, 0x40020 >> 2)
    iso[0x40020:0x40028] = struct.pack(">II", 0x50000 >> 2, 0)
    iso[sec + 5] = 0xAB
    n_disc_sec = (143432 * 2 * 0x8000 + sec - 1) // sec
    wlba = [0] * n_disc_sec
    wlba[0], wlba[1] = 1, 3              # container sector 2 left unallocated; ISO sector 1 stored at 3
    img = bytearray(4 * sec)
    img[0:4] = b"WBFS"
    img[4:8] = struct.pack(">I", len(img) >> hd_shift)
    img[8], img[9], img[0x0C] = hd_shift, sec_shift, 1
    img[0x200:0x300] = iso[:0x100]
    img[0x300:0x300 + 2 * n_disc_sec] = struct.pack(f">{n_disc_sec}H", *wlba)
    img[sec:2 * sec] = iso[:sec]
    img[3 * sec:4 * sec] = iso[sec:]
    Path(path).write_bytes(img)
    return bytes(iso)


def test_synthetic_roundtrip(tmp_path):
    p = tmp_path / "t.wbfs"
    iso = make_wbfs(p)
    with WBFS(p) as w:
        assert w.game_id == "RTEST1" and w.title == "Test"
        assert w.size == len(iso)
        assert w.read(0, len(iso)) == iso
        assert w.read((1 << 21) - 3, 10) == iso[(1 << 21) - 3:(1 << 21) + 7]      # crosses a sector boundary
        assert w.partitions() == [{"type": 0, "offset": 0x50000, "group": 0}]
        out = tmp_path / "o.iso"
        assert w.extract_iso(out) == len(iso)
    assert out.read_bytes() == iso


def test_synthetic_listing(tmp_path):
    p = tmp_path / "t.wbfs"
    make_wbfs(p)
    L = disc.listing(p)
    assert L.kind == "wii_disc"
    assert {f["path"] for f in L.files} >= {"disc/header.bin", "disc/partition_table.bin"}
    assert L.files[0]["head"][:6] == b"RTEST1"


def test_rejects_bad_magic(tmp_path):
    p = tmp_path / "x.wbfs"
    p.write_bytes(b"NOPE" + bytes(0x400))
    with pytest.raises(ValueError):
        WBFS(p)


@pytest.mark.skipif(not REAL.exists(), reason="HyperSpin share not mounted")
def test_real_metroid_other_m():
    with WBFS(REAL) as w:
        assert w.sec_size == 1 << 21 and w.n_hd_sec * 512 == REAL.stat().st_size
        assert w.read(0x18, 4) == struct.pack(">I", 0x5D1C9EA3)
        assert w.game_id.startswith("R") and w.partitions()
        assert w.read(0x40000, 4) != b"\0\0\0\0"
    L = disc.listing(REAL, head=16, deep=0)
    assert L.kind == "wii_disc" and len(L.files) >= 3
