"""Focused tests for gbox.defjam_icon_inventory (GDFX / Xbox 360 disc reader).

The parser is validated against a synthetic GDFX image built in-memory (no network or
SMB dependency), then against the real owned disc when the path is available.
"""

import struct
import tempfile
from pathlib import Path

import pytest

from gbox.defjam_icon_inventory import GDFX, GDFXError, MAGIC, SECTOR, _pad4

REAL_ISO = "/mnt/gbox/hyperspin/Arcade/collections/Microsoft XBOX 360/roms/Def Jam Icon.iso"


def _entry(left, right, sector, length, attr, name):
    """Pack one GDFX directory entry (padded to a 4-byte boundary)."""
    name = name.encode("latin1")
    raw = struct.pack("<HHIIBB", left, right, sector, length, attr, len(name)) + name
    return raw + b"\x00" * (_pad4(len(raw)) - len(raw))


def _layout(entries):
    """Pack entries sequentially; rewrite left/right ordinals from byte offsets.

    `entries` is a list of (left_name|None, right_name|None, sector, length, attr, name)
    and children are referenced by name so the caller never computes ordinals by hand.
    """
    offset_of = {}
    buf = bytearray()
    for i, (_, _, _, _, _, name) in enumerate(entries):
        offset_of[name] = len(buf)
        buf += _entry(0, 0, 0, 0, 0, name)
    out = bytearray()
    for left_name, right_name, sector, length, attr, name in entries:
        left = offset_of[left_name] // 4 if left_name else 0
        right = offset_of[right_name] // 4 if right_name else 0
        out += _entry(left, right, sector, length, attr, name)
    return bytes(out)


def _build_image():
    """Minimal GDFX image: root (default.xex file, sub/ dir), sub (a.txt, b.bin, c.dat)."""
    xex_sector, xex_size = 0x118, 16

    sub_entries = _layout([
        ("b.bin", "c.dat", 0x120, 8, 0x20, "a.txt"),
        (None, None, 0x121, 4, 0x20, "b.bin"),
        (None, None, 0x122, 7, 0x20, "c.dat"),
    ])
    sub_sector, sub_size = 0x110, len(sub_entries)

    root_entries = _layout([
        ("sub", None, xex_sector, xex_size, 0x20, "default.xex"),
        (None, None, sub_sector, sub_size, 0x10, "sub"),
    ])
    root_sector, root_size = 0x108, len(root_entries)

    size = 0x200000
    data = bytearray(size)
    desc = MAGIC + b"\x00" * (20 - len(MAGIC)) + struct.pack("<II", root_sector, root_size)
    data[0x10000:0x10000 + len(desc)] = desc
    data[root_sector * SECTOR: root_sector * SECTOR + root_size] = root_entries
    data[sub_sector * SECTOR: sub_sector * SECTOR + sub_size] = sub_entries
    data[xex_sector * SECTOR: xex_sector * SECTOR + xex_size] = b"XEX2" + b"\x00" * 12
    return bytes(data)


def _write(data):
    tmp = tempfile.NamedTemporaryFile(suffix=".iso", delete=False)
    tmp.write(data)
    tmp.close()
    return tmp.name


def test_walk_yields_expected_tree():
    path = _write(_build_image())
    try:
        with GDFX(path) as disc:
            got = {(p, d, s, l) for p, d, s, l in disc.walk()}
        assert ("default.xex", False, 0x118, 16) in got
        assert ("sub", True, 0x110, 60) in got
        assert ("sub/a.txt", False, 0x120, 8) in got
        assert ("sub/b.bin", False, 0x121, 4) in got
        assert ("sub/c.dat", False, 0x122, 7) in got
    finally:
        Path(path).unlink(missing_ok=True)


def test_manifest_counts_files():
    path = _write(_build_image())
    try:
        with GDFX(path) as disc:
            manifest = disc.manifest()
        assert manifest["file_count"] == 4
        assert manifest["total_bytes"] == 16 + 8 + 4 + 7
        assert len(manifest["source_sha256"]) == 64
    finally:
        Path(path).unlink(missing_ok=True)


def test_rejects_non_gdfx_image():
    path = _write(b"\x00" * 0x100000)
    try:
        with pytest.raises(GDFXError):
            GDFX(path)
    finally:
        Path(path).unlink(missing_ok=True)


@pytest.mark.skipif(not Path(REAL_ISO).exists(), reason="owned disc not mounted")
def test_real_disc_smoke():
    """The owned Def Jam Icon disc must parse and locate its character archives."""
    with GDFX(REAL_ISO) as disc:
        tree = {p: (s, l) for p, _, s, l in disc.walk()}
    assert tree["default.xex"] == (265, 8105984)
    assert tree["common/char.viv"][1] == 1281259996
    assert tree["common/char.viv.bh"][1] == 9628
    assert tree["common/char/hdr_char.viv"][1] == 107292
