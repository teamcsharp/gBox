"""Focused tests for gbox.ttt2_inventory (Xbox 360 XDVDFS + Namco 0x0FF512ED packs).

The real disc is optional: set GBOX_TTT2_ISO to the owned ISO to exercise the
XDVDFS walk end-to-end.  The pack-header unit tests run without any disc.
"""
from __future__ import annotations

import os
import struct

import pytest

from gbox.ttt2_inventory import PACK_MAGIC, XDVDFS_MAGIC, Xdvdfs, pack_header


def _pack(magic=PACK_MAGIC, version=0x01000000, f1=0, f2=0, records=()):
    blob = struct.pack(">IIII", magic, version, f1, f2)
    for a, b in records:
        blob += struct.pack(">II", a, b)
    return blob


def test_pack_header_parses_records_until_out_of_bounds():
    # Two valid records, then a record whose range leaves the file -> stop.
    size = 1_000_000
    blob = _pack(records=[(1000, 500), (2000, 300), (999_000, 999_000)])
    info = pack_header(blob, size)
    assert info["magic"] == PACK_MAGIC
    assert info["version"] == 0x01000000
    assert info["records"] == [(1000, 500), (2000, 300)]


def test_pack_header_rejects_non_pack():
    with pytest.raises(ValueError):
        pack_header(b"NOTAPACK" + b"\x00" * 16, 1_000_000)


def test_pack_header_stops_on_zero_record():
    blob = _pack(records=[(1000, 500), (0, 0)])
    info = pack_header(blob, 1_000_000)
    assert info["records"] == [(1000, 500)]


def test_magic_constants():
    assert PACK_MAGIC == 0x0FF512ED
    assert XDVDFS_MAGIC == b"MICROSOFT*XBOX*MEDIA"


@pytest.mark.skipif(not os.environ.get("GBOX_TTT2_ISO"), reason="set GBOX_TTT2_ISO to run")
def test_xdvdfs_walk_finds_default_xex():
    dvd = Xdvdfs(os.environ["GBOX_TTT2_ISO"])
    files = dvd.files()
    boot = next(p for p in files if p.lower() == "default.xex")
    s, n = files[boot]
    assert dvd.read(s, 4) == b"XEX2"


def test_xdvdfs_rejects_directory_cycles_and_out_of_range_reads(tmp_path):
    image = bytearray(35 * 2048)
    image[32*2048:32*2048+20] = XDVDFS_MAGIC
    image[33*2048-20:33*2048] = XDVDFS_MAGIC
    struct.pack_into("<II", image, 32*2048+20, 33, 32)
    struct.pack_into("<HHIIBB", image, 33*2048, 0, 0, 33, 32, 0x10, 4)
    image[33*2048+14:33*2048+18] = b"loop"
    path = tmp_path / "cycle.iso"
    path.write_bytes(image)
    dvd = Xdvdfs(path)
    try:
        with pytest.raises(ValueError, match="cyclic"):
            dvd.files()
        with pytest.raises(ValueError, match="outside"):
            dvd.read(35, 1)
        with pytest.raises(ValueError, match="outside"):
            dvd.read(0, -1)
    finally:
        dvd.close()
