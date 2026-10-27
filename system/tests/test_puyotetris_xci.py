"""Tests for the Puyo Puyo Tetris XCI main-NSO resolver (request #2221).

These validate the binary-resolution path itself — the concrete acceptance step
that produces the SHA-256 the save overlay's revision gate requires — without
needing the real owned XCI present on this box. They construct a structurally
correct XCI and assert the resolver reads back the right partition, title id,
content id, and executable hash.
"""
from __future__ import annotations

import hashlib
import struct

import pytest

from gbox.puyotetris_xci import (
    PARTITION_MAIN,
    _nca_header,
    resolve_main_nso,
    profile,
)
from gbox.puyotetris_save import TITLE_ID as SAVE_TITLE_ID
from gbox.puyotetris_unlock import GAME_ID


def build_nca(partition: int, title_id: bytes, content_id: bytes, payload: bytes) -> bytes:
    """A structurally valid NCA: 0x400 header + payload (the NSO body).

    Header layout (non-overlapping):
      0x00  4 bytes magic "NCA\\x01"
      0x08  u8  header version
      0x0C  u32 header flags (bit0 = update flag)
      0x10  u16 partition id
      0x18  16 bytes title id
      0x28  16 bytes content id
    """
    hdr = bytearray(0x400)
    hdr[0:4] = b"NCA\x01"
    hdr[8:9] = bytes([1])
    hdr[12:16] = struct.pack("<I", 0)  # no update flag
    hdr[0x10:0x12] = struct.pack("<H", partition)
    hdr[0x18:0x28] = (title_id or b"\x00" * 16)[:16].ljust(16, b"\x00")
    hdr[0x28:0x38] = (content_id or b"\x00" * 16)[:16].ljust(16, b"\x00")
    return bytes(hdr) + payload


def build_xci(nca_main: bytes, partition_main: int = PARTITION_MAIN) -> bytes:
    """A minimal XCI: 0x400 partition table + the main NCA image.

    The partition table entry for ``partition_main`` points (relative to the end
    of the table) to where the NCA image is stored.
    """
    table = bytearray(0x400)
    entry_off = partition_main * 0x40
    # base = 0 (image starts right after the 0x400 table), size = len(nca_main)
    table[entry_off:entry_off + 8] = struct.pack("<Q", 0)
    table[entry_off + 8:entry_off + 16] = struct.pack("<Q", len(nca_main))
    return bytes(table) + nca_main


NSO_PAYLOAD = b"\xde\xad\xbe\xef" * 512  # 2 KiB of dummy "executable" bytes


def test_resolver_returns_correct_executable_sha256():
    title = SAVE_TITLE_ID.encode("ascii").ljust(16, b"\x00")
    content = bytes(range(16))
    nca = build_nca(PARTITION_MAIN, title, content, NSO_PAYLOAD)
    xci = build_xci(nca)
    rep = resolve_main_nso(xci)

    assert rep["game_id"] == GAME_ID
    assert rep["resolved"] is True
    assert rep["partition"] == PARTITION_MAIN
    assert rep["executable_sha256"] == hashlib.sha256(NSO_PAYLOAD).hexdigest()
    assert rep["nca_sha256"] == hashlib.sha256(nca).hexdigest()
    assert rep["nso_bytes"] == len(NSO_PAYLOAD)
    assert rep["nca_bytes"] == len(nca)
    assert rep["title_id_matches"] is True
    assert rep["gameplay_verified"] is False
    assert rep["complete_unlock_profile"] is False
    # The report must never claim a runtime unlock.
    assert "not an unlock" in rep["note"].lower() or "not unlock" in rep["note"].lower()


def test_resolver_reads_back_title_and_content_id():
    title = SAVE_TITLE_ID.encode("ascii").ljust(16, b"\x00")
    content = b"\x11" * 16
    nca = build_nca(PARTITION_MAIN, title, content, NSO_PAYLOAD)
    xci = build_xci(nca)
    rep = resolve_main_nso(xci)
    assert rep["nca_title_id"] == SAVE_TITLE_ID
    assert rep["nca_content_id"] == content.hex()


def test_resolver_rejects_wrong_partition_id_in_nca():
    # NCA header claims partition 1 but we asked for partition 3 -> mismatch.
    title = SAVE_TITLE_ID.encode("ascii").ljust(16, b"\x00")
    nca = build_nca(1, title, bytes(16), NSO_PAYLOAD)
    xci = build_xci(nca)  # table still points to this image for partition 3
    with pytest.raises(ValueError):
        resolve_main_nso(xci)


def test_resolver_rejects_bad_magic():
    bad = bytearray(build_xci(build_nca(PARTITION_MAIN, SAVE_TITLE_ID.encode(), bytes(16), NSO_PAYLOAD)))
    bad[0x400:0x404] = b"XXXX"  # corrupt the NCA magic
    with pytest.raises(ValueError):
        resolve_main_nso(bytes(bad))


def test_resolver_rejects_oversized_image():
    # Table says the image is bigger than the file allows.
    table = bytearray(0x400)
    entry_off = PARTITION_MAIN * 0x40
    table[entry_off:entry_off + 8] = struct.pack("<Q", 0)
    table[entry_off + 8:entry_off + 16] = struct.pack("<Q", 1 << 20)  # absurd size
    nca = build_nca(PARTITION_MAIN, SAVE_TITLE_ID.encode(), bytes(16), NSO_PAYLOAD)
    xci = bytes(table) + nca
    with pytest.raises(ValueError):
        resolve_main_nso(xci)


def test_resolver_rejects_short_file():
    with pytest.raises(ValueError):
        resolve_main_nso(b"\x00" * 128)


def test_profile_reports_resolver_available_and_no_gameplay():
    p = profile()
    assert p["xci_resolver_available"] is True
    assert p["partition_main"] == PARTITION_MAIN
    assert p["gameplay_verified"] is False
    assert p["game_id"] == GAME_ID
