"""Focused tests for the Platinum DAT reader + repack writer (Bayonetta 2)."""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import pytest

from gbox.formats.dat_platinum import parse_dat, repack_dat

REAL_PL0010 = Path.home() / ".hermes/cache/scratch/b2/pl0010.dat"
REAL_DAT = Path.home() / ".hermes/cache/scratch/b2/pl0000.dat"


@pytest.mark.skipif(not REAL_PL0010.exists(),
                    reason="real pl0010.dat not present in scratch/b2")
def test_real_donor_swap_pl0010_wmb_into_pl0000():
    """The acceptance swap: pl0010.wmb (657248 B) into pl0000.dat's wmb slot
    (793184 B) — shorter donor, file size and tables must be unchanged."""
    src = REAL_DAT.read_bytes()
    donor_buf = REAL_PL0010.read_bytes()
    donor_ents = parse_dat(donor_buf)
    wmb10 = [e for e in donor_ents if e.ext == "wmb"]
    assert len(wmb10) == 1 and wmb10[0].size == 657248
    e = wmb10[0]
    donor = donor_buf[e.offset:e.offset + e.size]

    ents = parse_dat(src)
    assert len(ents) == 5
    assert any(e.size == 793184 for e in ents)
    target = next(e for e in ents if e.size == 793184)
    key = f"{target.name}.{target.ext}" if target.ext else target.name

    out = repack_dat(src, {key: donor})
    assert len(out) == len(src)                      # file size unchanged
    assert hashlib.sha256(out).hexdigest() != hashlib.sha256(src).hexdigest()
    assert out[target.offset:target.offset + 657248] == donor
    assert out[target.offset + 657248:target.offset + 793184] == \
        src[target.offset + 657248:target.offset + 793184]  # original tail
    # tables byte-identical; unrelated members intact
    assert out[:target.offset] == src[:target.offset]
    ents2 = parse_dat(out)
    assert [ (a.offset, a.size, a.name) for a in ents2 ] == \
           [ (a.offset, a.size, a.name) for a in ents ]
    wtp = next(e for e in ents if e.ext == "wtp")
    assert out[wtp.offset:wtp.offset + wtp.size] == src[wtp.offset:wtp.offset + wtp.size]


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


def test_repack_shorter_donor_swap_preserves_layout():
    # shape of the real donor swap: pl0010.wmb (657248) into pl0000's wmb slot (793184)
    buf = _build_dat([("w", "wmb", b"A" * 100), ("t", "wtp", b"B" * 40),
                      ("s", "exp", b"C" * 16)])
    donor = b"D" * 40
    out = repack_dat(buf, {"w": donor})
    assert len(out) == len(buf)
    e = parse_dat(buf)[0]
    diff = [i for i in range(len(buf)) if buf[i] != out[i]]
    # only the new payload prefix may differ; tables + hash region byte-identical
    assert diff and min(diff) == e.offset and max(diff) < e.offset + 40
    assert out[e.offset:e.offset + 40] == donor
    assert out[e.offset + 40:e.offset + 100] == b"A" * 60  # original tail kept
    ents = parse_dat(out)
    assert ents[0].offset == e.offset and ents[0].size == 100  # slot unchanged
    assert out[ents[1].offset:ents[1].offset + 40] == b"B" * 40  # unrelated intact
    assert out[ents[2].offset:ents[2].offset + 16] == b"C" * 16


def test_repack_full_name_key_and_ambiguity():
    buf = _build_dat([("pl0000", "wmb", b"A" * 100), ("pl0000", "wtp", b"B" * 40)])
    with pytest.raises(ValueError, match="ambiguous"):
        repack_dat(buf, {"pl0000": b"A" * 100})
    out = repack_dat(buf, {"pl0000.wmb": b"Z" * 100})
    e0, e1 = parse_dat(buf)
    assert out[e0.offset:e0.offset + 100] == b"Z" * 100
    assert out[e1.offset:e1.offset + 40] == b"B" * 40  # wtp untouched


def test_repack_longer_rejected():
    buf = _build_dat([("w", "wmb", b"A" * 100)])
    with pytest.raises(ValueError, match="longer replacement"):
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
