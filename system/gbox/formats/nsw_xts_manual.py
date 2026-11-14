"""AES-128-XTS sector decryption for encrypted Nintendo Switch card images (XCI/NCSD).

Importable implementation (SP 800-38E XTS-AES) built on single-block AES-ECB,
because pycryptodome does not provide ``AES.MODE_XTS``.  The older
``gbox.formats.nsw_xts`` module imported ``AES.MODE_XTS`` and is unimportable;
this module replaces it (delete the old one once this is published).

Scheme (matches hactool and switchbrew "Encryption" for NCSD/XCI partitions):

  * each 0x200-byte sector is encrypted independently;
  * key = the 32-byte header_key (first 16 bytes = data key, second 16 = tweak key);
  * IV  = 16-byte little-endian counter.  Three variants are supported and
    probed: absolute sector index (``iv="sector"``), absolute byte offset
    (``iv="offset"``), and zero (``iv="zero"``).

For each 16-byte block: ciphertext = AES(data_key, P XOR T) XOR T, with the
tweak advancing per block by a GF(2^128) multiply by 0x87.  Correctness is
pinned by the NIST SP 800-38E F.1 known-answer vectors in
``tests/test_nsw_xts_manual.py``.

No key material is embedded anywhere in this repository; callers pass key
bytes.  Ownership of the key is the operator's responsibility (prod.keys is
provisioned by the operator, never generated or bypassed by gBox).
"""
from __future__ import annotations

from typing import List

from Crypto.Cipher import AES

SECTOR_SIZE = 0x200

#: magic -> human label, scanned over decrypted output
KNOWN_MAGICS = {
    b"NCSD": "NCSD header (partition table follows)",
    b"XCI0": "XCI0 card header",
    b"HEAD": "card header (HEAD)",
    b"HFS0": "HFS0 file system",
    b"PFS0": "PFS0 plaintext file system",
    b"NCA3": "NCA content",
    b"HRS0": "HRS0",
    b"RMFS": "RMFS",
}

_MASK128 = (1 << 128) - 1


class XtsKeyError(ValueError):
    """Wrong-sized key/IV for AES-128-XTS."""


def _tweak_multiply(t: bytes) -> bytes:
    """Next XTS tweak: multiply T by x in GF(2^128), reduction constant 0x87.

    SP 800-38E / IEEE 1619 bit ordering: the leftmost bit of the block's hex
    representation is the most significant.  A shifted-out MSB therefore XORs
    the reduction constant into the LEFTMOST byte (0x87 << 120), not the last.
    """
    carry = 1 if t[0] & 0x80 else 0
    b = (int.from_bytes(t, "big") << 1) & _MASK128
    if carry:
        b ^= 0x87 << 120
    return b.to_bytes(16, "big")


class _XtsCipher:
    """XTS-AES over a fixed 32-byte key and 16-byte IV (SP 800-38E)."""

    def __init__(self, key: bytes, iv: bytes):
        if len(key) != 32:
            raise XtsKeyError("AES-XTS key must be 32 bytes, got %d" % len(key))
        if len(iv) != 16:
            raise XtsKeyError("AES-XTS IV must be 16 bytes, got %d" % len(iv))
        self._data_key = key[:16]
        self._tweak_key = key[16:]
        self._iv = iv

    @staticmethod
    def _aes_block(key: bytes, block: bytes, encrypt: bool) -> bytes:
        return AES.new(key, AES.MODE_ECB).encrypt(block) if encrypt \
            else AES.new(key, AES.MODE_ECB).decrypt(block)

    def _process(self, data: bytes, encrypt: bool) -> bytes:
        if len(data) % 16:
            raise ValueError("XTS data must be a multiple of 16 bytes, got %d" % len(data))
        tweak = self._aes_block(self._tweak_key, self._iv, True)
        out = bytearray()
        for i in range(0, len(data), 16):
            block = data[i:i + 16]
            mixed = bytes(a ^ b for a, b in zip(block, tweak))
            cblock = self._aes_block(self._data_key, mixed, encrypt)
            out += bytes(a ^ b for a, b in zip(cblock, tweak))
            tweak = _tweak_multiply(tweak)
        return bytes(out)

    def encrypt(self, data: bytes) -> bytes:
        return self._process(data, True)

    def decrypt(self, data: bytes) -> bytes:
        return self._process(data, False)


def make_xts_cipher(key: bytes, iv: bytes):
    """AES-128-XTS cipher for one sector. key=32B, iv=16B.

    Encrypts/decrypts any length that is a multiple of 16 bytes (Switch
    sectors are 0x200); the SP 800-38E known-answer vectors exercise the
    64-byte sector form.
    """
    return _XtsCipher(key, iv)


def sector_iv(abs_offset: int, mode: str = "sector") -> bytes:
    """16-byte little-endian IV for the sector at *abs_offset*.

    mode "sector" -> IV = sector index (abs_offset // 0x200)
    mode "offset" -> IV = absolute byte offset
    mode "zero"   -> IV = 0
    """
    if mode == "sector":
        v = abs_offset // SECTOR_SIZE
    elif mode == "offset":
        v = abs_offset
    elif mode == "zero":
        v = 0
    else:
        raise ValueError("unknown IV mode %r" % mode)
    return v.to_bytes(16, "little")


def decrypt_sector(data: bytes, key: bytes, abs_offset: int, mode: str = "sector") -> bytes:
    """Decrypt one 0x200 sector located at *abs_offset* in the image."""
    if len(data) != SECTOR_SIZE:
        raise ValueError("sector must be 0x200 bytes, got %d" % len(data))
    return make_xts_cipher(key, sector_iv(abs_offset, mode)).decrypt(data)


def decrypt_sectors(data: bytes, key: bytes, abs_start: int, count: int, mode: str = "sector") -> bytes:
    """Decrypt *count* consecutive 0x200 sectors whose first starts at *abs_start*."""
    if count < 1:
        raise ValueError("count must be >= 1")
    if len(data) < count * SECTOR_SIZE:
        raise ValueError("need %d bytes, have %d" % (count * SECTOR_SIZE, len(data)))
    out = bytearray()
    for i in range(count):
        off = abs_start + i * SECTOR_SIZE
        out += decrypt_sector(data[i * SECTOR_SIZE:(i + 1) * SECTOR_SIZE], key, off, mode)
    return bytes(out)


def find_magic(bl: bytes) -> List[tuple]:
    """All (offset, magic, label) hits for 4-byte magics, 4-byte aligned."""
    hits = []
    for off in range(0, len(bl) - 3, 4):
        m = bl[off:off + 4]
        if m in KNOWN_MAGICS:
            hits.append((off, m.decode("ascii"), KNOWN_MAGICS[m]))
    return hits
