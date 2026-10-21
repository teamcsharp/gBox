"""Tests for gbox.nightfire_writer (007 Nightfire GC writer, #1377)."""
from __future__ import annotations

import hashlib
import os
import random
import struct
import zlib
from pathlib import Path

import pytest

from gbox import nightfire_edl as E
from gbox import nightfire_writer as W

ISO = Path.home() / "gBox_alt/gbox-cache/modbase/744ba3bc797403bf/007 - Nightfire (USA).iso"
LEVEL_EDL_SHA = "33f667850b6acfd5c5dc2639f93455cb9d1d2b9aa231a17441e4dde0d8f3c3c7"
LEVEL_SHA = "b4e554ac925e1f0b00db873367b24e32225021b878fe82aa8d2561c721392664"


def _sample(n=120_000, seed=7):
    r = random.Random(seed)
    words = [bytes(r.randrange(256) for _ in range(r.randrange(2, 12))) for _ in range(300)]
    out = bytearray()
    while len(out) < n:
        out += r.choice(words) if r.random() < 0.8 else bytes([r.randrange(256)])
    return bytes(out[:n])


def test_deflate_tokens_rebuild_input_including_stored_blocks():
    data = os.urandom(40_000) + b"xyz" * 20_000 + bytes(range(256)) * 40
    for level in (0, 1, 9):
        co = zlib.compressobj(level, zlib.DEFLATED, -15)
        toks = W.deflate_tokens(co.compress(data) + co.flush())
        out = bytearray()
        for t in toks:
            if type(t) is int:
                out.append(t)
            else:
                for _ in range(t[0]):
                    out.append(out[-t[1]])
        assert bytes(out) == data


def test_huffman_lengths_are_limited_and_complete():
    freqs = [int(1.6 ** i) for i in range(40)] + [0] * 5 + [1]
    for limit in (8, 10, 15):
        lens = W.huffman_lengths(freqs, limit)
        assert max(lens) <= limit
        assert sum(2.0 ** -L for L in lens if L) == pytest.approx(1.0)
    one = W.huffman_lengths([0, 5, 0], 8)  # a lone symbol still gets a complete 2-code table
    assert sorted(L for L in one if L) == [1, 1]


@pytest.mark.parametrize("data", [b"", b"A", b"\0" * 70_000, _sample()], ids=["empty", "one-byte", "zeros", "sample"])  # short ids: Windows caps env vars at 32 KiB
def test_method1_roundtrip_through_reconstructed_decoder(data):
    edl = W.compress_method1(data, block_input=8192)
    h = E.header(edl)
    assert (edl[:4], h["method"], h["big_endian"], h["size"], h["unpacked"]) == (b"EDL\x81", 1, True, len(edl), len(data))
    assert (len(edl) - 12) % 4 == 0
    assert E.decompress(edl) == data


def _pack(entries):
    table = b"".join(struct.pack("<IB", len(p), t) + n.encode() + b"\0" for n, t, p in entries)
    table += b"\0" * (-len(table) % 16)
    head = struct.pack(">II", len(table), len(entries)) + b"\x11" * 24
    return head + table + b"".join(p for _, _, p in entries)


def test_repack_noop_and_size_change():
    lvl = _pack([("01000075", 2, b"\0\0\0\0\x14\0\0\x0e" + b"B" * 40), ("05000007", 3, b"S" * 16), ("x", 5, b"z")])
    assert W.repack(lvl) == lvl
    new = W.repack(lvl, {"05000007": b"T" * 24})
    idx = W.pack_index(new)
    assert [e["size"] for e in idx["entries"]] == [48, 24, 1]
    assert new[idx["entries"][1]["offset"]:][:24] == b"T" * 24
    with pytest.raises(KeyError):
        W.repack(lvl, {"deadbeef": b""})


def _disc(files, size):
    """Tiny GC-style image: FST at 0x440 with a root, one directory 'gc' and the given files."""
    names = b"gc\0" + b"".join(n.encode() + b"\0" for n, _, _ in files)
    n = 2 + len(files)
    fst = struct.pack(">III", 0x01000000, 0, n) + struct.pack(">III", 0x01000000, 0, n)
    p = 3
    for name, off, data in files:
        fst += struct.pack(">III", p, off, len(data))
        p += len(name) + 1
    fst += names
    img = bytearray(size)
    img[0x424:0x430] = struct.pack(">III", 0x440, len(fst), len(fst))
    img[0x440:0x440 + len(fst)] = fst
    for _, off, data in files:
        img[off:off + len(data)] = data
    return bytes(img)


def test_build_mod_iso_in_place_and_relocated(tmp_path):
    src = tmp_path / "src.iso"
    src.write_bytes(_disc([("a.bin", 0x1000, b"A" * 0x100), ("b.bin", 0x1100, b"B" * 0x80)], 0x20000))
    before = src.read_bytes()
    r = W.build_mod_iso(src, tmp_path / "small.iso", "gc/a.bin", b"N" * 0x40)
    assert r["mode"] == "in_place" and r["offset"] == 0x1000 and r["extent"] == 0x100
    assert W.read_disc_file(tmp_path / "small.iso", "gc/a.bin") == b"N" * 0x40
    assert W.read_disc_file(tmp_path / "small.iso", "gc/b.bin") == b"B" * 0x80
    r = W.build_mod_iso(src, tmp_path / "big.iso", "gc/a.bin", b"G" * 0x300)
    assert r["mode"] == "relocated" and r["offset"] == 0x8000
    assert W.read_disc_file(tmp_path / "big.iso", "gc/a.bin") == b"G" * 0x300
    assert src.read_bytes() == before
    with pytest.raises(ValueError):
        W.build_mod_iso(src, tmp_path / "huge.iso", "gc/a.bin", b"H" * 0x20000)
    with pytest.raises(ValueError):
        W.build_mod_iso(src, src, "gc/a.bin", b"x")


@pytest.mark.skipif(not ISO.exists(), reason="owned Nightfire ISO not present")
def test_owned_level_reencode_and_bond_head_swap():
    orig = W.read_disc_file(ISO, "gc/07000001.bin")
    assert hashlib.sha256(orig).hexdigest() == LEVEL_EDL_SHA
    lvl = E.decompress(orig)
    assert hashlib.sha256(lvl).hexdigest() == LEVEL_SHA and len(lvl) == 9_872_000
    assert W.repack(lvl) == lvl
    edl = W.encode_level(lvl)              # asserts decode == input
    assert len(edl) <= len(orig)           # fits the original disc extent, no FST relocation needed
    mod, rep = W.swap_texture(lvl, ("01000075", "bond_head"), ("01000145", "mayhew"))
    assert rep["size"] == 43680 and rep["old_sha256"].startswith("a86c1a46") and len(rep["copies"]) == 1
    assert len(mod) == len(lvl) and mod != lvl
    t = W.object_texture(mod, "01000075", "bond_head")
    d = W.object_texture(lvl, "01000145", "mayhew")
    assert mod[t["abs"]:t["abs"] + t["size"]] == lvl[d["abs"]:d["abs"] + d["size"]]
    with pytest.raises(ValueError):       # DT shared refs carry no texels
        W.object_texture(lvl, "0100006f", "eyeball_brown")
    with pytest.raises(ValueError):       # 256x256 head into a 128x128 slot
        W.swap_texture(lvl, ("01000075", "male_hand"), ("01000145", "mayhew"))
