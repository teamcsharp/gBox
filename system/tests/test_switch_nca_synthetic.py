"""gbox.switch_nca parsing on a synthetic NCA header: the fixed fields and the per-section superblock offsets.

The vectors are built here and encrypted with the module's own XTS convention through a test-side encryptor, so this
runs without any prod.keys and catches the offsets a real header would silently get wrong (the pfs0 offset sits at
superblock+0x38, i.e. fs-header+0x40; reading at +0x38 returns the block size instead).
"""
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from gbox import switch_nca as N

HEADER_KEY = bytes(range(32))


def xts_encrypt(key: bytes, data: bytes, sector: int = N.SECTOR) -> bytes:
    """AES-128-XTS (big-endian sector index), the mirrored NCA-header convention."""
    k1, k2 = key[:16], key[16:]
    enc = Cipher(algorithms.AES(k2), modes.ECB()).encryptor()
    data_enc = Cipher(algorithms.AES(k1), modes.ECB()).encryptor()
    out = bytearray()
    for n, start in enumerate(range(0, len(data), sector)):
        block = data[start:start + sector]
        tweak = int.from_bytes(enc.update(n.to_bytes(16, "big")), "little")
        for off in range(0, len(block), 16):
            t = tweak.to_bytes(16, "little")
            piece = bytes(a ^ b for a, b in zip(block[off:off + 16], t))
            out += bytes(a ^ b for a, b in zip(data_enc.update(piece), t))
            carry = tweak >> 127
            tweak = (tweak << 1) & ((1 << 128) - 1)
            if carry:
                tweak ^= 0x87
    return bytes(out)


def header_bytes() -> bytes:
    header = bytearray(0xC00)
    header[0x200:0x204] = b"NCA3"
    header[0x204] = 0                      # distribution
    header[0x205] = 0                      # program
    header[0x206] = 8                      # crypto type (keyblob)
    header[0x207] = 0                      # kaek index
    struct.pack_into("<Q", header, 0x208, 0x30_0000)
    struct.pack_into("<Q", header, 0x210, 0x01002A000CD48000)
    header[0x220] = 8                      # crypto type 2
    files = [(0x20, 0x30), (0x30, 0x40)]   # two present sections
    for index, (start, end) in enumerate(files):
        struct.pack_into("<II", header, 0x240 + index * 0x10, start, end)
        base = 0x400 + index * N.SECTOR
        header[base + 2] = 1 if index == 0 else 0     # partition type (PFS0 / RomFS)
        header[base + 3] = 2 if index == 0 else 3     # fs type (PFS0 / RomFS)
        header[base + 4] = 3                          # crypt type CTR
        header[base + 0x140:base + 0x148] = bytes.fromhex("0102030405060708")
    # section 0's PFS0 superblock: block size 0x6900 at +0x30, pfs0 offset/size at +0x38/+0x40 (fs-header +0x40/+0x48)
    struct.pack_into("<I", header, 0x400 + 0x30, 0x6900)
    struct.pack_into("<Q", header, 0x400 + 0x40, 0x8000)
    struct.pack_into("<Q", header, 0x400 + 0x48, 0x1A3B14E)
    return xts_encrypt(HEADER_KEY, bytes(header))


def test_header_fields_and_section_offsets():
    parsed = N.decrypt_header(header_bytes(), {"header_key": HEADER_KEY.hex()})
    assert parsed["magic"] == b"NCA3"
    assert parsed["title_id"] == "01002A000CD48000"
    assert parsed["size"] == 0x30_0000
    assert parsed["keyblob"] == 8 and N.titlekek_index(parsed) == 7
    assert len(parsed["sections"]) == 2
    first, second = parsed["sections"]
    assert first["offset"] == 0x20 * N.SECTOR and first["size"] == (0x30 - 0x20) * N.SECTOR
    assert first["fs_type"] == N.FS_PFS0 and first["crypt_type"] == N.CRYPT_CTR
    assert first["pfs0_offset"] == 0x8000 and first["pfs0_size"] == 0x1A3B14E   # not the 0x6900 block size
    assert second["fs_type"] == N.FS_ROMFS and second["offset"] == 0x30 * N.SECTOR


def test_section_iv_and_ctr_round_trip():
    ctr = bytes.fromhex("0102030405060708")
    iv = N.section_iv(ctr, 0x12340)
    assert iv == bytes.fromhex("0807060504030201") + (0x12340 >> 4).to_bytes(8, "big")
    key = bytes(range(16))
    plain = b"PFS0" + bytes(28)
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes as m
    enc = Cipher(algorithms.AES(key), m.CTR(iv)).encryptor().update(plain)
    assert N.ctr_decrypt(key, enc, iv) == plain
