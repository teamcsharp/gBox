"""Focused tests for gbox.formats.nsw_xts (AES-128-XTS sector decryption).

Synthetic-only: no real ROM, no prod.keys.  A crafted HFS0-like blob is
encrypted per-sector with AES-XTS and must decrypt back byte-identical, which
proves the module's cipher/IV plumbing is correct before it is pointed at the
owned card image.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gbox.formats.nsw_xts import (
    SECTOR_SIZE,
    XtsKeyError,
    decrypt_sector,
    decrypt_sectors,
    find_magic,
    make_xts_cipher,
    sector_iv,
)

# deterministic synthetic key (NOT real key material): two AES-128 halves
KEY = bytes.fromhex(
    "0123456789abcdef0123456789abcdef" "fedcba9876543210fedcba9876543210"
)


def _craft_hfs0_like(sector_count: int = 2) -> bytes:
    """A plausible plaintext HFS0 block: magic, file_count, string pool, filler."""
    n = SECTOR_SIZE * sector_count
    blob = bytearray(n)
    blob[0:4] = b"HFS0"
    struct.pack_into("<I", blob, 8, 4)      # file_count
    struct.pack_into("<I", blob, 12, 0x100)  # string table size
    names = (b"logo", b"normal", b"update", b"secure")
    for i in range(4):
        blob[0x40 + i * 8: 0x40 + i * 8 + 8] = names[i].ljust(8, b"\x00")
    blob[0x100:0x110] = b"logo\0update\0".ljust(16, b"\x00")  # slice must stay 16 bytes
    blob[0x200:] = bytes((i * 7 + 3) & 0xFF for i in range(n - 0x200))  # deterministic filler
    return bytes(blob)


def _encrypt_sector(clear: bytes, key: bytes, abs_offset: int, mode: str) -> bytes:
    return make_xts_cipher(key, sector_iv(abs_offset, mode)).encrypt(clear)


def test_sector_iv_shapes():
    assert sector_iv(0, "sector") == b"\x00" * 16
    assert sector_iv(0x7000, "sector") == (0x7000 // 0x200).to_bytes(16, "little")
    assert sector_iv(0x7000, "offset") == (0x7000).to_bytes(16, "little")
    assert sector_iv(0x12345, "zero") == b"\x00" * 16
    for iv in (sector_iv(0x1000, "sector"), sector_iv(0x1000, "offset")):
        assert len(iv) == 16
    try:
        sector_iv(0, "bogus")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_key_and_iv_size_gates():
    try:
        make_xts_cipher(KEY[:16], b"\x00" * 16)
        raise AssertionError("expected XtsKeyError for short key")
    except XtsKeyError:
        pass
    try:
        make_xts_cipher(KEY, b"\x00" * 8)
        raise AssertionError("expected XtsKeyError for short IV")
    except XtsKeyError:
        pass
    try:
        decrypt_sector(b"\x00" * 100, KEY, 0)
        raise AssertionError("expected ValueError for non-sector size")
    except ValueError:
        pass


def test_synthetic_roundtrip_single_sector():
    clear = _craft_hfs0_like(1)
    for base, mode in ((0, "sector"), (0x7000, "offset"), (0, "zero")):
        sec = _encrypt_sector(clear, KEY, base, mode)
        assert sec != clear, "encryption must change the bytes"
        back = decrypt_sector(sec, KEY, base, mode)
        assert back == clear, "roundtrip failed for base=0x%x mode=%s" % (base, mode)


def test_synthetic_roundtrip_multi_sector_offsets():
    """Consecutive sectors, each with its own absolute IV, must all recover."""
    clear = _craft_hfs0_like(3)
    base = 0x10000  # typical root-partition start
    enc = bytearray()
    for i in range(3):
        off = base + i * SECTOR_SIZE
        enc += _encrypt_sector(clear[i * SECTOR_SIZE:(i + 1) * SECTOR_SIZE], KEY, off, "sector")
    out = decrypt_sectors(bytes(enc), KEY, base, 3, mode="sector")
    assert out == clear
    # offset mode must NOT recover the sector-mode ciphertext (IVs differ at this offset)
    wrong = decrypt_sectors(bytes(enc), KEY, base, 3, mode="offset")
    assert wrong != clear


def test_find_magic_detects_hfs0():
    blob = b"\x00" * 16 + b"HFS0" + b"\x00" * 32 + b"PFS0"
    hits = find_magic(blob)
    got = {(off, magic) for off, magic, _ in hits}
    assert (16, "HFS0") in got
    assert (52, "PFS0") in got
    assert find_magic(b"\x00" * 64) == []


def test_decrypt_sectors_length_gates():
    try:
        decrypt_sectors(b"\x00" * SECTOR_SIZE, KEY, 0, 2)
        raise AssertionError("expected ValueError for short buffer")
    except ValueError:
        pass
    try:
        decrypt_sectors(b"\x00" * SECTOR_SIZE, KEY, 0, 0)
        raise AssertionError("expected ValueError for zero count")
    except ValueError:
        pass


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print("PASS", fn.__name__)
        except Exception as e:  # noqa: BLE001
            failed += 1
            print("FAIL", fn.__name__, "->", e)
    sys.exit(1 if failed else 0)
