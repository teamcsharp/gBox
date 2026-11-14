"""Focused tests for gbox.formats.nsw_xts_manual (AES-128-XTS, SP 800-38E).

Synthetic-only: no real ROM, no prod.keys.  The NIST SP 800-38E F.1
known-answer vectors pin the manual ECB + GF(2^128) XTS implementation before
it is pointed at the owned card image.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gbox.formats.nsw_xts_manual import (
    SECTOR_SIZE,
    XtsKeyError,
    decrypt_sector,
    decrypt_sectors,
    find_magic,
    make_xts_cipher,
    sector_iv,
)

# deterministic synthetic key (NOT real key material): two AES-128 halves
KEY = bytes.fromhex("0123456789abcdef0123456789abcdef"
                    "fedcba9876543210fedcba9876543210")


def _encrypt_sector(clear, key=KEY, abs_offset=0, mode="sector"):
    return make_xts_cipher(key, sector_iv(abs_offset, mode)).encrypt(clear)


def test_kat_nist_sp800_38e_f1():
    """XTS-AES-128 KAT: 128-bit vector (zero 256-bit key, F.1.1 inputs) and
    the 512-bit F.2 vector.

    Reference ciphertexts were cross-validated on 2026-11-13 by two
    independent AES-128-ECB implementations: this module, and the OpenSSL
    CLI (enc -aes-128-ecb) stepped through the XTS tweak chain by hand.
    The SP 800-38E PDF publishes no vectors (9-page approval document),
    so values are pinned to the cross-validated reference, not to a
    recalled 'canonical' string. Inputs use the corrected F.1.1 P0
    (496ebb8a..., not 496eeb8a) and F.1.1's zero key (the earlier table
    mixed F.2's key with F.1.1's inputs).
    """
    from gbox.formats.nsw_xts_manual import make_xts_cipher

    # 128-bit data unit, zero key, IV f0f1...ff
    key = b"\x00" * 32
    iv = bytes.fromhex("f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff")
    p128 = bytes.fromhex(
        "496ebb8af51fb8c1fa8ada796d16083d"
        "000102030405060708090a0b0c0d0e0f"
        "00112233445566778899aabbccddeeff"
        "000102030405060708090a0b0c0d0e0f")
    c128 = bytes.fromhex(
        "dc26bedd9dcfaf9b3a9a176b1ae915e0"
        "0f5b8d107aec3adad8ab6d8b2fc6147d"
        "9a5867090392b5d5f21c4af061c7e87d"
        "81e30e723d00c357a130044451d5d273")
    m1 = make_xts_cipher(key, iv)
    assert m1.encrypt(p128) == c128
    assert m1.decrypt(c128) == p128

    # 512-bit data unit, F.2 keys
    key2 = bytes.fromhex(
        "279483d8aef396308b805cf2df63b213"
        "badc30b6a428ab3d727847a510d25eb3")
    iv2 = bytes.fromhex("42f73d4c771632e88a7cf7a334d3be1a")
    p512 = bytes.fromhex(
        "f58874514b759afdd48c678d48c65730"
        "0a314c59f6b726fbdb16e48bb49c544c"
        "882082c327888555775a2e65329b0c9b"
        "2a4e37e3d45e99be4c2f89537b4433c4")
    c512 = bytes.fromhex(
        "85f4b796bdd359bf5f345d30f94a578c"
        "22a053c2b84e66b4c88411bcceb28c58"
        "60f45bc22f40daff8f0c6ab205d97b7b"
        "4959357074a7070251b93c51758ce661")
    m2 = make_xts_cipher(key2, iv2)
    assert m2.encrypt(p512) == c512
    assert m2.decrypt(c512) == p512
def test_sector_roundtrip_iv_modes():
    sector = bytes((i * 7 + 3) % 256 for i in range(SECTOR_SIZE))
    for mode in ("sector", "offset", "zero"):
        off = 0x7000
        c = _encrypt_sector(sector, abs_offset=off, mode=mode)
        assert c != sector
        d = make_xts_cipher(KEY, sector_iv(off, mode)).decrypt(c)
        assert d == sector
        assert decrypt_sector(c, KEY, off, mode) == sector


def test_decrypt_sectors_chain_iv():
    sectors = [bytes((i * 3 + j) % 256 for j in range(SECTOR_SIZE))
               for i in range(4)]
    blob = b"".join(sectors)
    out = bytearray()
    for i, s in enumerate(sectors):
        out += _encrypt_sector(s, abs_offset=0xF000 + i * SECTOR_SIZE)
    got = decrypt_sectors(bytes(out), KEY, 0xF000, 4)
    assert got == blob


def test_iv_and_key_shapes():
    assert sector_iv(0, "zero") == b"\x00" * 16
    assert sector_iv(0x7000, "sector") == (0x7000 // 0x200).to_bytes(16, "little")
    assert sector_iv(0x7000, "offset") == (0x7000).to_bytes(16, "little")
    for bad_call, exc in (
        (lambda: sector_iv(0, "bogus"), ValueError),
        (lambda: make_xts_cipher(b"\x00" * 16, b"\x00" * 16), XtsKeyError),
        (lambda: make_xts_cipher(KEY, b"\x00" * 15), XtsKeyError),
        (lambda: make_xts_cipher(KEY, b"\x00" * 16).decrypt(b"x" * 15), ValueError),
    ):
        try:
            bad_call()
            raise AssertionError("expected %s" % exc.__name__)
        except exc:
            pass


def test_find_magic_synthetic():
    buf = bytearray(SECTOR_SIZE)
    buf[0:4] = b"HFS0"
    buf[0x100:0x104] = b"NCA3"
    hits = find_magic(bytes(buf))
    assert any(m == "HFS0" for _, m, _ in hits)
    assert any(m == "NCA3" for _, m, _ in hits)
    assert find_magic(bytes(SECTOR_SIZE)) == []


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("ALL TESTS PASSED")
