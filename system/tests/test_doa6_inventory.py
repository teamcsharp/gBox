"""Tests for gbox/doa6_inventory.py: DRK index parsing, IDRK chunk decompression, manifest.

Fixtures are synthetic: a tiny DRK index and IDRK containers built with the module's own
format constants, so the tests stay independent of any real disc.
"""

from __future__ import annotations

import struct
import zlib

import pytest

from gbox import doa6_inventory as d6


def build_idrk_entry(name: str | None, crc1: int, data: bytes, size: int | None = None,
                     flags: int | None = None) -> bytes:
    """One IDRK entry: header + one zlib chunk. Mirrors the on-disc layout.

    size overrides the header's uncompressed-size field (index entries carry the real size
    but no chunk payload).
    """
    flags = flags if flags is not None else (0x00120000 if name else 0x00100000)
    num1 = 0
    raw_hlen = 56 + 12 * 0 + num1 + (len(name.encode()) + 1 if name else 0)
    hlen = (raw_hlen + 3) & ~3
    if data:
        compressed = zlib.compress(data)
        payload = struct.pack("<I", len(compressed)) + compressed + b"\0" * 4
    else:
        payload = struct.pack("<I", 0)
    entry_size = (hlen + len(payload) + 3) & ~3
    header = d6.IDRK_MAGIC
    header += struct.pack("<QQQI", entry_size, 0, len(data) if size is None else size, num1)
    header += struct.pack("<5I", crc1, 0x1234ABCD, flags, 0, 0)
    if name:
        header += name.encode("latin1") + b"\0"
    header += b"\0" * (hlen - len(header))
    assert len(header) == hlen, (len(header), hlen)
    return header + payload + b"\0" * (entry_size - hlen - len(payload))


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
    assert d6.sniff_magic(b"GT1G....") == "g1t"
    assert d6.sniff_magic(b"KTID....") == "ktid"
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


def test_inventory_arcade_layout(tmp_path):
    (tmp_path / "muscle_apm3.exe").write_bytes(b"MZ" + b"\0" * 30)
    (tmp_path / "game.bat").write_text("@echo off\r\nW:\\muscle_apm3.exe\r\n")
    (tmp_path / "teknoparrot.ini").write_text("[General]\r\nInput API=XInput\r\n")
    (tmp_path / "CharacterEditor.rdb").write_bytes(build_rdb([("c@1", 5, b"aa")]))
    m = d6.inventory(tmp_path)
    assert m["layout"] == "arcade"
    assert m["executable"]["name"] == "muscle_apm3.exe"
    assert m["executable"]["size"] == 32
    assert m["rdbs"]["CharacterEditor"]["parses_clean"]
    assert "Input API=XInput" in m["launch"]["teknoparrot_ini"]
    assert "muscle_apm3.exe" in m["launch"]["sidecars"]
    assert "wrong" in m["platform_label"]


def test_inventory_steam_layout_preferred_and_missing_exe_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="muscle_apm3.exe"):
        d6.inventory(tmp_path)
    (tmp_path / "DOA6.exe").write_bytes(b"MZ")
    (tmp_path / "muscle_apm3.exe").write_bytes(b"MZ")
    assert d6.inventory(tmp_path)["layout"] == "steam"


def test_read_bin_entry_and_classify():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "DOA6.exe").write_bytes(b"MZ" + b"\0" * 10)
        idx = root / "RRPreview.rdb"
        idx.write_bytes(build_rdb([
            ("tex", 1, b""),
            ("mdl", 2, b""),
            ("rnk", 3, b""),
        ]))
        rdb = d6.Rdb(idx)
        bin_path = root / "RRPreview.rdb.bin"
        # build a bin from three IDRK entries with different payloads
        bin_path.write_bytes(
            build_idrk_entry(None, 1, b"GT1G0600" + b"\0" * 20)
            + build_idrk_entry(None, 2, b"_M1G7300" + b"\0" * 20)
            + build_idrk_entry(None, 3, b"_RNK0000" + b"\0" * 20)
        )
        assert d6.sniff_magic(d6.read_bin_entry(bin_path, 0, limit=8)) == "g1t"
        summary = d6.classify_bin_entries(rdb, sample=None)
        assert summary[bin_path.name]["sampled"] == 3
        assert summary[bin_path.name]["content"] == {"g1t": 1, "g1m": 1, "rnk": 1}


def test_read_bin_entry_rejects_truncated_header(tmp_path):
    first = build_idrk_entry(None, 1, b"GT1G0600" + b"\0" * 20)
    bad = tmp_path / "RRPreview.rdb.bin"
    bad.write_bytes(first + d6.IDRK_MAGIC + b"\0" * 10)      # the last magic has 18 of its 56 header bytes
    with pytest.raises(ValueError):
        d6._header_length(d6.IDRK_MAGIC + b"\0" * 10)
    with pytest.raises(ValueError):
        d6.read_bin_entry(bad, len(first), limit=8)


def test_read_bin_entry_rejects_entry_size_smaller_than_header(tmp_path):
    head = d6.IDRK_MAGIC + struct.pack("<QQQI", 10, 0, 100, 0) + struct.pack("<5I", 1, 2, 0x100000, 0, 0)
    bad = tmp_path / "RRPreview.rdb.bin"
    bad.write_bytes(head + b"\xAB" * 4096)                   # entry_size 10 < its 56-byte header: never read on
    with pytest.raises(ValueError):
        d6.read_bin_entry(bad, 0, limit=8)


def test_classify_counts_window_straddling_magic_and_survives_truncated_tail(tmp_path):
    (tmp_path / "DOA6.exe").write_bytes(b"MZ" + b"\0" * 10)
    idx = tmp_path / "RRPreview.rdb"
    idx.write_bytes(build_rdb([("tex", 1, b""), ("mdl", 2, b"")]))
    first = build_idrk_entry(None, 1, b"GT1G0600" + b"\0" * 20)
    second = build_idrk_entry(None, 2, b"_M1G7300" + b"\0" * 20)
    (tmp_path / "RRPreview.rdb.bin").write_bytes(first + second + d6.IDRK_MAGIC + b"\0" * 10)
    # a window edge 4 bytes into the second magic, and a magic at the tail with no header behind it
    summary = d6.classify_bin_entries(d6.Rdb(idx), sample=None, initial_chunk=len(first) + 4)
    assert summary["RRPreview.rdb.bin"]["sampled"] == 3
    assert summary["RRPreview.rdb.bin"]["content"] == {"g1t": 1, "g1m": 1, "unreadable": 1}
