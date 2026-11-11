"""Focused tests for the Platinum DAT reader + repack writer (Bayonetta 2)."""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import pytest

from gbox.formats.dat_platinum import parse_dat, repack_dat

REAL_DAT = Path.home() / ".hermes/cache/scratch/b2/pl0000.dat"


def _build_dat(items, hash_words=None):
    """Independent spec-built fixture: DAT header + tables + fake hash + payloads."""
    n = len(items)
    nlen = 16
    off_o, ext_o, nam_o = 0x20, 0x30, 0x40
    siz_o = nam_o + 4 + n * nlen
    tbl_end = max(off_o + 4 * n, ext_o + 4 * n, nam_o + 4 + n * nlen, siz_o + 4 * n)
    hash_off = tbl_end + 8
    hash_len = 4 * n
    payload_start = hash_off + hash_len
    if hash_words is None:
        hash_words = list(range(1, n + 1))
    total = sum(len(pl) for _, _, pl in items)
    out = bytearray(payload_start + total)
    out[:4] = b"DAT\0"
    struct.pack_into("<6I", out, 4, n, off_o, ext_o, nam_o, siz_o, hash_off)
    struct.pack_into("<I", out, nam_o, nlen)
    pos = 0
    for i, (name, ext, payload) in enumerate(items):
        struct.pack_into("<I", out, off_o + 4 * i, payload_start + pos)
        struct.pack_into("<I", out, siz_o + 4 * i, len(payload))
        struct.pack_into("<I", out, nam_o + 4 + i * nlen, 0)
        out[nam_o + 4 + i * nlen : nam_o + 4 + i * nlen + len(name)] = name.encode()
        out[payload_start + pos : payload_start + pos + len(payload)] = payload
        pos += len(payload)
    for i, (name, ext, payload) in enumerate(items):
        out[ext_o + 4 * i : ext_o + 4 * i + 4] = ext.encode()[:4].ljust(4, b"\0")
    for w, word in enumerate(hash_words):
        struct.pack_into("<I", out, hash_off + 4 * w, word)
    return bytes(out)


def test_parse_fixture():
    buf = _build_dat([("pl0000", "wmb", b"A" * 100), ("pl0000", "wtp", b"B" * 40)])
    ents = parse_dat(buf)
    assert [e.name for e in ents] == ["pl0000", "pl0000"]
    assert [e.ext for e in ents] == ["wmb", "wtp"]
    assert [e.size for e in ents] == [100, 40]
    assert buf[ents[0].offset:ents[0].offset + 100] == b"A" * 100
    assert buf[ents[1].offset:ents[1].offset + 40] == b"B" * 40


def test_repack_noop_byte_identical():
    buf = _build_dat([("w", "wmb", b"A" * 100), ("t", "wtp", b"B" * 40),
                      ("s", "exp", b"C" * 16)])
    assert repack_dat(buf) == buf
    assert repack_dat(buf, {}) == buf
    assert repack_dat(buf, None) == buf


def test_repack_same_size_swap_only_touches_payload():
    buf = _build_dat([("w", "wmb", b"A" * 100), ("t", "wtp", b"B" * 40)])
    new_w = b"Z" * 100
    out = repack_dat(buf, {"w": new_w})
    assert len(out) == len(buf)
    diff = [i for i in range(len(buf)) if buf[i] != out[i]]
    e = parse_dat(buf)[0]
    assert diff and min(diff) >= e.offset and max(diff) < e.offset + 100
    ents = parse_dat(out)
    assert ents[0].offset == e.offset and ents[0].size == 100
    assert out[ents[0].offset:ents[0].offset + 100] == new_w
    assert out[ents[1].offset:ents[1].offset + 40] == b"B" * 40  # unrelated intact


def test_repack_size_change_rejected():
    buf = _build_dat([("w", "wmb", b"A" * 100)])
    with pytest.raises(ValueError, match="size-changing"):
        repack_dat(buf, {"w": b"A" * 128})


def test_repack_rejects_overlapping_payloads():
    buf = bytearray(_build_dat([("w", "wmb", b"A" * 100), ("t", "wtp", b"B" * 40),
                                ("s", "exp", b"C" * 200)]))
    _n, off_o, *_ = struct.unpack_from("<6I", bytes(buf), 4)
    o0 = struct.unpack_from("<I", buf, off_o)[0]
    struct.pack_into("<I", buf, off_o + 4, o0 + 50)  # second payload starts inside first
    with pytest.raises(ValueError, match="overlap"):
        repack_dat(bytes(buf))


def test_repack_rejects_garbage():
    with pytest.raises(ValueError, match="not DAT"):
        repack_dat(b"XDAT" + b"\0" * 64)


@pytest.mark.skipif(not REAL_DAT.exists(), reason="real pl0000.dat not present")
def test_real_pl0000_noop_roundtrip():
    buf = REAL_DAT.read_bytes()
    assert len(buf) == 12959744
    ents = parse_dat(buf)
    assert any(e.ext == "wmb" and e.size == 793184 for e in ents)
    out = repack_dat(buf)
    assert out == buf
    assert hashlib.sha256(out).hexdigest() == hashlib.sha256(buf).hexdigest()
