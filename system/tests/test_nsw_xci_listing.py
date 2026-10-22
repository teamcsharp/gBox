"""Tests for gbox.formats.nsw: synthetic HEAD-variant and classic XCI0 fixtures, plus the owned real card if present."""
import hashlib
import os
import struct

import pytest

from gbox.formats import nsw


def _hfs0(files):
    """Build an HFS0 image from [(name, bytes)]."""
    pool = b"".join(n.encode() + b"\0" for n, _ in files)
    entries, data, off, noff = b"", b"", 0, 0
    for n, d in files:
        entries += struct.pack("<QQIIQ", off, len(d), noff, 0, 0) + hashlib.sha256(d).digest()
        data += d
        off += len(d)
        noff += len(n) + 1
    return b"HFS0" + struct.pack("<II", len(files), len(pool)) + b"\0" * 4 + entries + pool + data


def _reader(img):
    return lambda o, n: img[o:o + n]


def _head_image():
    nca = b"NCA3" + b"\0" * 0x1FC
    nca += b"mainname".ljust(32, b"\0") + b"prog".ljust(32, b"\0") + b"\0" * 0x100
    secure = _hfs0([("a.nca", nca), ("b.cnmt.nca", b"x" * 64)])
    root = _hfs0([("update", _hfs0([])), ("secure", secure)])
    img = bytearray(0x10000 + len(root))
    img[0:0x100] = os.urandom(0x100) if False else b"\xf5" * 0x100
    img[0x100:0x104] = b"HEAD"
    struct.pack_into("<QQ", img, 0x130, 0xF000, len(root))
    img[0xF000:0xF000 + len(root)] = root
    return bytes(img)


def test_head_variant_listing():
    info = nsw.list_xci_from(_reader(_head_image()))
    assert [p.name for p in info.partitions] == ["update", "secure"]
    assert [e.name for e in info.hfs0["secure"]] == ["a.nca", "b.cnmt.nca"]
    assert info.hfs0["update"] == []
    assert [n["entry"] for n in info.ncas] == ["a.nca"]
    assert info.ncas[0]["header_names"] == ["mainname", "prog"]
    assert nsw.summarize(info)["warnings"] == []


def test_classic_xci0_listing():
    hfs = _hfs0([("c.nca", b"NCA3" + b"\0" * 0x3FC)])
    img = bytearray(0x1000 + 0x20)
    img[0:4] = b"XCI0"
    img += b"\0" * 0x1000
    start = len(img)
    img += hfs
    struct.pack_into("<QQHBB", img, 0x1000, start, len(hfs), 0x20, 1, 0)
    img[0x1014:0x1014 + 16] = b"HFS0PARTT".ljust(16)
    info = nsw.list_xci_from(_reader(bytes(img)))
    assert info.partitions[0].offset == start


def test_non_xci_rejected():
    with pytest.raises(ValueError):
        nsw.list_xci_from(_reader(b"\0" * 0x2000))


def test_truncated_rejected():
    with pytest.raises(ValueError):
        nsw.list_xci_from(_reader(_head_image()[:0xF010]))


REAL = os.path.join(os.path.dirname(__file__), "..", "animal_crossing_xci.xci")


@pytest.mark.skipif(not os.path.exists(REAL), reason="owned XCI not present")
def test_real_owned_card():
    info = nsw.list_xci(REAL)
    assert [p.name for p in info.partitions] == ["update", "normal", "secure"]
    names = [e.name for e in info.hfs0["secure"]]
    assert len(names) == 12
    assert "bd68bf29c8500e9c88ca844e1a6f77e8.nca" in names
