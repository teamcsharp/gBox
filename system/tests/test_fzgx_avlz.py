"""Amusement Vision LZ codec and F-Zero GX inventory: self-contained round-trips plus
owned-disc checks (skipped when the GCZ is not mounted)."""
import struct
from pathlib import Path

import pytest

from gbox.formats import avlz
from gbox.formats.avlz import AvLzError, decompress, decompress_stream

SRC = "/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/F-Zero GX (USA).gcz"


def test_avlz_all_literals_roundtrip():
    # header {compressed=3, uncompressed=2}; flag 0b11 -> two literals, then "AB"
    blob = struct.pack("<II", 3, 2) + bytes([0x03, 0x41, 0x42])
    assert decompress(blob) == b"AB"


def test_avlz_backreference():
    # "ABC" then a 3-byte back-ref to the start -> "ABCABC"
    # index = ((b1 & 0xF0) << 4) | b0 ; b0=0xEE, b1=0xF0 -> index 0xFEE (4078, the ring
    # write start), count = (0xF0 & 0x0F) + 3 = 3
    stream = bytes([0x07]) + b"ABC" + bytes([0xEE, 0xF0])
    assert decompress_stream(stream, 6) == b"ABCABC"


def test_avlz_size_mismatch_raises():
    blob = struct.pack("<II", 3, 5) + bytes([0x03, 0x41, 0x42])
    with pytest.raises(AvLzError):
        decompress(blob)


def test_avlz_bad_header_raises():
    with pytest.raises(AvLzError):
        decompress(b"\x00" * 4)  # too short


def test_avlz_known_stub_has_u8_magic():
    # The 31-byte chara/arc/_intervewer_sel.arc.lz stub decompresses to a U8 archive.
    stub = bytes.fromhex(
        "17000000" "2d000000"
        "af55aa382debf020ebf00dd6ebf040ccfefc01e4f70100"
    )
    out = decompress(stub)
    assert len(out) == 45
    assert out[:4] == avlz.U8_MAGIC


def test_inventory_owned_disc():
    if not Path(SRC).exists():
        pytest.skip("F-Zero GX GCZ not mounted")
    from gbox import fzgx_inventory as inv

    m = inv.build_manifest(SRC)
    assert m["disc_id"] == "GFZE01"
    assert m["region"] == "NTSC-U"
    assert m["roster_count"] == 44
    assert m["roster"][0] == "arrow" and "zoda" in m["roster"]
    assert m["containers"]["u8_archive_plain"] == 52
    assert len(m["source_sha256"]) == 64
    assert len(m["dol"]["sha256"]) == 64
    assert m["fst"]["num_files"] > 4000
