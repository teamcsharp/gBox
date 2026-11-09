"""Nintendo Content Archive (NCA) reading on a client PC: the fixed header, key area, sections and ExeFS.

The project ships `hactool`, but it cannot read this library's containers: with every `prod.keys` on the share it ends
at `Invalid NCA header! Are keys correct?` for the RE6 base and update, on the i9's build and the Spark's alike. The
files are ordinary standard-crypto NCAs; the conventions below were verified against the RE6 update
(01002A000CD48800 v131072) by decrypting its header and ExeFS and matching the ExeFS `main` to the update profile's
hash (8b81f49f…). This module is the client-side path for the "full decrypting tasks" requirement, using only the
CPU (AES-NI through `cryptography`) and the public `prod.keys`.

The conventions, each measured rather than assumed:

* The fixed header (0xC00) is AES-128-XTS with the retail `header_key`, **sector index big-endian**; an encrypted
  NCA's magic is only visible after this ("NCA3" at 0x200).
* Section entries (0x240, 4 × 0x10) hold *sector* offsets: real offset = value × 0x200. The FS header for section i
  sits at 0x400 + i*0x200: `partition_type`, `fs_type` (2 = PFS0, 3 = RomFS), `crypt_type` (1 none, 2 XTS, 3 CTR,
  4 BKTR), the superblock at +0x8 and `section_ctr` at +0x140.
* PFS0 sections are CTR-encrypted from `section_offset + pfs0_offset`, with the IV
  `reversed(section_ctr) || big-endian((absolute_offset >> 4) as 8 bytes)`.
* A ticket's title key block sits at 0x180 in these retail tickets; the title key is that block AES-ECB-decrypted
  with `titlekek_<keyblob-1>`, where keyblob = max(crypto_type, crypto_type2) - 1 when either is set.
"""
import struct
from pathlib import Path

HEADER_SIZE = 0xC00
SECTOR = 0x200
MAGICS = (b"NCA0", b"NCA2", b"NCA3")
FS_PFS0, FS_ROMFS = 2, 3
CRYPT_NONE, CRYPT_XTS, CRYPT_CTR, CRYPT_BKTR = 1, 2, 3, 4
TICKET_TITLE_KEY = 0x180


def load_keys(path: str | Path) -> dict:
    """A prod.keys file as {lower-case name: hex value}; blank lines and comments are skipped."""
    out = {}
    for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        out[name.strip().lower()] = value.strip().lower()
    return out


def _ecb(key: bytes, data: bytes):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    return Cipher(algorithms.AES(key), modes.ECB()).decryptor()


def _ctr(key: bytes, data: bytes, iv: bytes):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    return Cipher(algorithms.AES(key), modes.CTR(iv)).decryptor()


def ecb_decrypt(key: bytes, data: bytes) -> bytes:
    return _ecb(key, data).update(data)


def ctr_decrypt(key: bytes, data: bytes, iv: bytes) -> bytes:
    return _ctr(key, data, iv).update(data)


def xts_decrypt(key: bytes, data: bytes, sector: int = SECTOR) -> bytes:
    """AES-128-XTS with a big-endian sector index (the NCA header's convention)."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    k1, k2 = key[:16], key[16:]
    enc = Cipher(algorithms.AES(k2), modes.ECB()).encryptor()
    dec = Cipher(algorithms.AES(k1), modes.ECB()).decryptor()
    out = bytearray()
    for n, start in enumerate(range(0, len(data), sector)):
        block = data[start:start + sector]
        tweak = int.from_bytes(enc.update(n.to_bytes(16, "big")), "little")
        for off in range(0, len(block), 16):
            t = tweak.to_bytes(16, "little")
            piece = bytes(a ^ b for a, b in zip(block[off:off + 16], t))
            out += bytes(a ^ b for a, b in zip(dec.update(piece), t))
            carry = tweak >> 127
            tweak = (tweak << 1) & ((1 << 128) - 1)
            if carry:
                tweak ^= 0x87
    return bytes(out)


def decrypt_header(raw: bytes, keys: dict) -> dict:
    """The fixed header of an NCA, decrypted: magic, identity and one record per present section."""
    if len(raw) < HEADER_SIZE:
        raise ValueError(f"an NCA header is {HEADER_SIZE:#x} bytes, got {len(raw)}")
    header = xts_decrypt(bytes.fromhex(keys["header_key"]), raw[:HEADER_SIZE])
    if header[0x200:0x204] not in MAGICS:
        raise ValueError("not an NCA header after decrypting with this header_key")
    keyblob = max(header[0x206], header[0x220])
    sections = []
    for index in range(4):
        start, end = struct.unpack_from("<II", header, 0x240 + index * 0x10)
        if not start:
            continue
        base = 0x400 + index * SECTOR
        sections.append({"index": index, "offset": start * SECTOR, "size": (end - start) * SECTOR,
                         "partition_type": header[base + 2], "fs_type": header[base + 3],
                         "crypt_type": header[base + 4], "section_ctr": header[base + 0x140:base + 0x148],
                         "pfs0_offset": struct.unpack_from("<Q", header, base + 0x38)[0],
                         "pfs0_size": struct.unpack_from("<Q", header, base + 0x40)[0]})
    return {"magic": header[0x200:0x204], "distribution": header[0x204], "content_type": header[0x205],
            "keyblob": keyblob, "kaek_index": header[0x207], "size": struct.unpack_from("<Q", header, 0x208)[0],
            "title_id": f"{struct.unpack_from('<Q', header, 0x210)[0]:016X}",
            "rights_id": header[0x230:0x240].hex(), "sections": sections, "header": header}


def titlekek_index(header: dict) -> int:
    """The titlekek index for the title key (keyblob, decremented when set; -1 means keyblob 0)."""
    return header["keyblob"] - 1 if header["keyblob"] else 0


def title_key(ticket: bytes, keys: dict, index: int, offset: int = TICKET_TITLE_KEY) -> bytes:
    """The title key: the ticket's block at `offset` AES-ECB-decrypted with titlekek_<index>."""
    if len(ticket) < offset + 0x10:
        raise ValueError(f"ticket is {len(ticket)} bytes, shorter than its title key block at {offset:#x}")
    name = f"titlekek_{index:02x}"
    if name not in keys:
        raise ValueError(f"no {name} in this keyset")
    return ecb_decrypt(bytes.fromhex(keys[name]), ticket[offset:offset + 0x10])


def section_iv(section_ctr: bytes, offset: int) -> bytes:
    """The AES-CTR IV for a section: reversed(section_ctr) then (offset >> 4) big-endian in the low 8 bytes."""
    ofs = offset >> 4
    iv = bytearray(16)
    for j in range(8):
        iv[j] = section_ctr[0x8 - j - 1]
        iv[0x10 - j - 1] = ofs & 0xFF
        ofs >>= 8
    return bytes(iv)


def decrypt_section(raw: bytes, section: dict, key: bytes) -> bytes:
    """One section's bytes, CTR-decrypted (crypt_type 3); plain data (1) passes through."""
    start, size = section["offset"], section["size"]
    blob = raw[start:start + size]
    if len(blob) != size:
        raise ValueError(f"section {section['index']} runs past the end of the file")
    if section["crypt_type"] == CRYPT_NONE:
        return blob
    if section["crypt_type"] != CRYPT_CTR:
        raise ValueError(f"section {section['index']} uses crypt type {section['crypt_type']}, not CTR")
    return ctr_decrypt(key, blob, section_iv(section["section_ctr"], start))


def read_pfs0(blob: bytes) -> dict:
    """A PFS0 container's members as {name: bytes} (the ExeFS layout: main, main.npdm, rtld, sdk, subsdk0)."""
    magic, count, strings_size, _reserved = struct.unpack_from("<4sIII", blob, 0)
    if magic != b"PFS0":
        raise ValueError(f"not a PFS0 container (magic {magic!r})")
    entries = []
    for index in range(count):
        offset, size, name_at, _pad = struct.unpack_from("<QQII", blob, 0x10 + index * 0x18)
        entries.append((offset, size, name_at))
    table_at = 0x10 + count * 0x18
    table = blob[table_at:table_at + strings_size]
    data_at = table_at + strings_size
    files = {}
    for offset, size, name_at in entries:
        end = table.find(b"\x00", name_at)
        name = table[name_at:end if end >= 0 else None].decode("utf-8", "replace")
        files[name] = blob[data_at + offset:data_at + offset + size]
    return files


def exefs(raw: bytes, header: dict, keys: dict, ticket: bytes) -> dict:
    """The ExeFS members of an NCA whose PFS0 section is present (the update's main, npdm, rtld, sdk, subsdk0)."""
    pfs0 = next((s for s in header["sections"] if s["fs_type"] == FS_PFS0 and s["partition_type"] == 1), None)
    if pfs0 is None:
        raise ValueError("no PFS0 (ExeFS) section in this NCA")
    key = title_key(ticket, keys, titlekek_index(header))
    section = dict(pfs0)
    section["offset"] = pfs0["offset"] + pfs0["pfs0_offset"]
    section["size"] = pfs0["pfs0_size"]
    return read_pfs0(decrypt_section(raw, section, key))


def read_nca(path: str | Path, keys: dict) -> dict:
    """The header of an NCA file plus its section records (nothing decrypted beyond the header)."""
    raw = Path(path).read_bytes()[:HEADER_SIZE]
    return decrypt_header(raw, keys)
