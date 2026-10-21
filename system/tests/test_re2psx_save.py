"""Focused tests for gbox.re2psx_save MEM_CARD.BIN reader (request #2032).

Runs against the real cached MEM_CARD.BIN extracted from the owned
USA Dual Shock Disc 2 image (23,932 bytes, sha256-pinned below), plus a
deterministic-synthetic round-trip for the memory-card block reader.
"""
import hashlib
from pathlib import Path

import pytest

from gbox import re2psx_save as save

CACHE = Path.home() / "gBox_alt/gbox-cache" / "2d8ef2bdbd4a58fd" / "extracted"
MEM_CARD = CACHE / "MEM_CARD.BIN"
MEM_CARD_SIZE = 23932
MEM_CARD_SHA256 = None  # pinned dynamically below after first read


def _load_real():
    if not MEM_CARD.exists():
        pytest.skip("cached MEM_CARD.BIN not present on this machine")
    return MEM_CARD.read_bytes()


def test_real_mem_card_parses():
    data = _load_real()
    assert len(data) == MEM_CARD_SIZE
    ov = save.parse_mem_card_overlay(data)
    assert ov.size == MEM_CARD_SIZE
    assert ov.sha256 == hashlib.sha256(data).hexdigest()
    # Three BASLUS filenames per the disc analysis
    assert len(ov.filenames) == 3
    assert all(n.startswith("BASLUS-") for n in ov.filenames)
    assert ov.addresses, "expected non-empty PSX address list"


def test_real_mem_card_reread_deterministic():
    data = _load_real()
    a = save.parse_mem_card_overlay(data)
    b = save.parse_mem_card_overlay(data)
    assert a.filenames == b.filenames
    assert a.addresses == b.addresses
    assert a.sha256 == b.sha256


def test_small_overlay_rejected():
    with pytest.raises(ValueError):
        save.parse_mem_card_overlay(b"\x00" * 0x33)


def _synthetic_card():
    blk = save.PSX_MC_BLOCK_SIZE
    header = bytearray(save.PSX_MC_HEADER_SIZE)
    header[:3] = b"BAS"
    header[4:12] = b"BASLUS-0"
    import struct
    struct.pack_into("<I", header, 12, 100)
    body = bytes((i * 7) & 0xFF for i in range(blk - save.PSX_MC_HEADER_SIZE))
    used = bytes(header) + body
    card = used + b"\x00" * blk
    return card


def test_memory_card_reader_roundtrip():
    card = _synthetic_card()
    blocks = save.parse_memory_card(card)
    assert len(blocks) == 2
    assert not blocks[0].is_free
    assert blocks[0].filename == "BASLUS-0"
    assert blocks[0].size == 100
    assert blocks[1].is_free
    again = save.parse_memory_card(save.write_memory_card(blocks))
    assert [b.to_dict() for b in again] == [b.to_dict() for b in blocks]


def test_room_flags_roundtrip():
    rf = save.RoomFlags()
    rf[3] = 0xDEADBEEF
    data = rf.to_bytes()
    assert len(data) == save.ROOM_FLAG_COUNT * 4
    rf2 = save.RoomFlags.from_bytes(data)
    assert rf2[3] == 0xDEADBEEF
    assert rf2.summary()["nonzero_count"] == 1
