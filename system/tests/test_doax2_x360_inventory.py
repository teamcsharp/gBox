"""Focused tests for gbox.doax2_x360_inventory (synthetic XDVDFS + AFS, no game data)."""
import hashlib
import struct

import pytest

from gbox import doax2_x360_inventory as inv

S = inv.SECTOR


def dirent(name, sector, size, attr=0, left=0, right=0):
    nm = name.encode()
    rec = struct.pack("<HHIIBB", left, right, sector, size, attr, len(nm)) + nm
    return rec + b"\xff" * (-len(rec) % 4)


def afs(members):
    n = len(members)
    off = (8 + 8 * n + 8 + 2047) & ~2047
    table, body, pos = b"", b"", off
    for _, data in members:
        table += struct.pack("<II", pos, len(data))
        body += data + b"\0" * (-len(data) % 2048)
        pos += len(data) + (-len(data) % 2048)
    names = b"".join(nm.encode().ljust(32, b"\0") + b"\0" * 12 + struct.pack("<I", len(d)) for nm, d in members)
    head = b"AFS\0" + struct.pack("<I", n) + table + struct.pack("<II", pos, len(names))
    return head.ljust(off, b"\0") + body + names


def build():
    xex = b"XEX2" + struct.pack(">IIIII", 1, 0x5000, 0, 152, 1) + struct.pack(">II", 0x10201, 0x1000) + b"\0" * 400
    chr_afs = afs([("vtn1.tpr", b"XPR2" + b"\0" * 20), ("vtn1.cat", b"CAT\0" + b"\0" * 8),
                   ("hand_a.bin", b"MPV\0" + b"\0" * 8)])
    # root dir at sector 40: default.xex (root node), chr.afs (right child)
    d1 = dirent("default.xex", 41, len(xex), right=0)
    d2 = dirent("chr.afs", 42, len(chr_afs))
    d1 = dirent("default.xex", 41, len(xex), right=len(d1) // 4)
    root = (d1 + d2).ljust(2048, b"\xff")
    vol = bytearray(S)
    vol[:20] = inv.MAGIC
    struct.pack_into("<II", vol, 20, 40, len(root))
    vol[-20:] = inv.MAGIC
    img = bytearray(0x10000 + S * 3)
    img[0x10000:0x10000 + S] = vol
    img += b"\0" * (40 * S - len(img))
    img += root
    img += xex.ljust(S, b"\0")
    img += chr_afs
    img += b"\0" * (-len(img) % S)
    return bytes(img), xex


def test_inventory_roundtrip(tmp_path):
    img, xex = build()
    p = tmp_path / "t.iso"
    p.write_bytes(img)
    r = inv.inventory(p, hash_iso=True)
    assert r["volume"] == {"base": 0, "root_sector": 40, "root_bytes": 2048}
    assert r["file_count"] == 2
    assert r["executable"]["sha256"] == hashlib.sha256(xex).hexdigest()
    assert r["executable"]["optional_headers"]["0x00010201"] == 0x1000
    assert r["image_sha256"] == hashlib.sha256(img).hexdigest()
    assert r["afs"]["chr.afs"]["count"] == 3
    assert r["afs"]["chr.afs"]["magics"] == {"XPR2": 1, "CAT": 1, "MPV": 1}
    assert r["chr_sets"]["vtn"]["count"] == 2


def test_rejects_non_xdvdfs(tmp_path):
    p = tmp_path / "bad.iso"
    p.write_bytes(b"\0" * 0x20000)
    with pytest.raises(inv.Unsupported):
        inv.inventory(p)


def test_xex_magic_required():
    with pytest.raises(ValueError):
        inv.parse_xex(b"XEX1" + b"\0" * 64)
