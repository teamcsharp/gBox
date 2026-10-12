"""Tests for gbox/doa6_inventory.py: DRK index parsing, IDRK chunk decompression, manifest.

Fixtures are synthetic: a tiny DRK index and IDRK containers built with the module's own
format constants, so the tests stay independent of any real disc.
"""

from __future__ import annotations

import struct
import zlib

from gbox import doa6_inventory as d6


def build_idrk_entry(name: str | None, crc1: int, data: bytes, size: int | None = None,
                     flags: int | None = None) -> bytes:
    """One IDRK entry: header + one zlib chunk. Mirrors the on-disc layout.

    size overrides the header's uncompressed-size field (index entries carry the real size
    but no chunk payload).
    """
    flags = flags if flags is not None else (0x00120000 if name else 0x00100000)
    num1 = 0
    hlen = 56 + 12 * 0 + num1 + (len(name.encode()) + 1 if name else 0)
    payload = struct.pack("<I", 0) if not data else struct.pack("<I", len(zlib.compress(data))) + zlib.compress(data)
    entry_size = hlen + len(payload) + (4 if data else 0)  # loose files carry a 4-byte trailer
    header = d6.IDRK_MAGIC
    header += struct.pack("<QQQI", entry_size, 0, len(data) if size is None else size, num1)
    header += struct.pack("<5I", crc1, 0x1234ABCD, flags, 0, 0)
    if name:
        header += name.encode("latin1") + b"\0"
    assert len(header) == hlen, (len(header), hlen)
    return header + payload + (b"\0" * 4 if data else b"")


def build_rdb(entries: list[tuple[str | None, int, bytes]]) -> bytes:
    blob = d6.DRK_MAGIC
    blob += struct.pack("<4I", 0x20, 0x10, len(entries), 0)
    blob += b"data/\0" + b"\0" * ((-(0x18 + 6)) % 4)
    body = b""
    for name, crc1, data in entries:
        entry = build_idrk_entry(name, crc1, b"", size=len(data))
        body += entry + b"\0" * ((-len(entry)) % 4)
    body += b"\0" * ((-len(body)) % 4)
    return blob + body


def test_rdb_roundtrip():
    rdb = build_rdb([("3faf6080@be0", 0x10004, b"hello"), (None, 0x1423B7, b"world"), ("abc@1", 7, b"x" * 100)])
    import tempfile
    import pathlib
    with tempfile.TemporaryDirectory() as tmp:
        p = pathlib.Path(tmp) / "RRPreview.rdb"
        p.write_bytes(rdb)
        r = d6.Rdb(p)
        assert r.file_count == 3
        assert r.mount_path == "data/"
        assert r.end_offset == len(r.raw)
        names = [e.name for e in r.entries]
        assert names == ["3faf6080@be0", "", "abc@1"]
        assert [e.crc1 for e in r.entries] == [0x10004, 0x1423B7, 7]
        assert [e.size for e in r.entries] == [5, 5, 100]


def test_idrk_chunk_decompression():
    data = bytes(range(256)) * 200  # 51,200 bytes -> 13 chunks of 0x4000
    payload = b""
    for off in range(0, len(data), d6.CHUNK_SIZE):
        chunk = zlib.compress(data[off:off + d6.CHUNK_SIZE])
        payload += struct.pack("<I", len(chunk)) + chunk
    hlen = 56 + 9  # header incl. name
    hdr = d6.IDRK_MAGIC + struct.pack("<QQQI", hlen + len(payload) + 4, 0, len(data), 0)
    hdr += struct.pack("<5I", 0xABCDEF, 0, 0x00120000, 0, 0) + b"big@c800\0"
    hdr += b"\0" * ((-len(hdr)) % 4)
    assert len(hdr) == (hlen + 3) & ~3
    idrk = d6.Idrk.from_bytes(hdr + payload)
    assert idrk.crc1 == 0xABCDEF
    assert idrk.size == len(data)
    assert idrk.read_data() == data
    assert idrk.read_data(limit=1000) == data[:1000]


def test_unnamed_entry_has_no_name_bytes():
    entry = build_idrk_entry(None, 0x22, b"bb")
    blob = d6.IDRK_MAGIC + entry[8:]
    idrk = d6.Idrk.from_bytes(blob)
    assert idrk.crc1 == 0x22
    assert idrk.flags & 0x20000 == 0
    assert idrk.read_data() == b"bb"


def test_sniff():
    assert d6.sniff_magic(b"_RNK0000\x18\x00") == "rnk"
    assert d6.sniff_magic(b"_DRK0000\x20\x00") == "drk"
    assert d6.sniff_magic(b"G1MX....") == "g1m"
    assert d6.sniff_magic(b"\x89PNG\r\n\x1a\n....") == "png"
    assert d6.sniff_magic(b"\x00\x01\x02") == "unknown"


def test_inventory_synthetic():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "DOA6.exe").write_bytes(b"MZ" + b"\0" * 100)
        idx = root / "RRPreview.rdb"
        idx.write_bytes(build_rdb([("a@1", 1, b"aa"), (None, 0x22, b"bb")]))
        data_dir = root / "data"
        data_dir.mkdir()
        loose = build_idrk_entry(None, 0x22, b"_RNK0000\x18\x00\x00\x00" + b"\0" * 64)
        (data_dir / "0x00000022.file").write_bytes(loose)
        m = d6.inventory(root)
        assert m["executable"]["size"] == 102
        assert m["rdbs"]["RRPreview"]["file_count"] == 2
        assert m["rdbs"]["RRPreview"]["parses_clean"]
        assert m["loose"]["files"] == 1
        assert m["loose"]["content"] == {"rnk": 1}
