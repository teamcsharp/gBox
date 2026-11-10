"""Switch NCA header / section-table reader (header_key AES-XTS, key-area AES-ECB).

Read-only. Keys come from a prod.keys-style mapping supplied by the caller;
no key material is stored in this module.  Layout per the public Switch
NCA spec (switchbrew "NCA" page); fields not proven against the game's own
loader are labelled by the caller as hypotheses.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

HEADER_SIZE = 0xC00
SECTOR = 0x200
MEDIA_UNIT = 0x200

CONTENT_TYPES = {0: "Program", 1: "Meta", 2: "Control", 3: "Manual", 4: "Data", 5: "PublicData"}
FS_TYPES = {0: "RomFS", 1: "PartitionFS"}
ENC_TYPES = {0: "Auto", 1: "None", 2: "AesXts", 3: "AesCtr", 4: "AesCtrEx", 5: "AesCtrSkip", 6: "AesCtrExSkip"}


def parse_keys(text: str) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        try:
            out[k.strip().lower()] = bytes.fromhex(v)
        except ValueError:
            pass
    return out


def _xts(key: bytes, data: bytes, sector0: int, encrypt: bool) -> bytes:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    out = bytearray()
    for i in range(0, len(data), SECTOR):
        tweak = (sector0 + i // SECTOR).to_bytes(16, "big")
        c = Cipher(algorithms.AES(key), modes.XTS(tweak))
        op = c.encryptor() if encrypt else c.decryptor()
        out += op.update(data[i:i + SECTOR]) + op.finalize()
    return bytes(out)


def decrypt_header(raw: bytes, header_key: bytes) -> bytes:
    if len(raw) < HEADER_SIZE:
        raise ValueError("need 0xC00 bytes of NCA header")
    return _xts(header_key, raw[:HEADER_SIZE], 0, False)


def encrypt_header(plain: bytes, header_key: bytes) -> bytes:
    return _xts(header_key, plain, 0, True)


@dataclass
class Section:
    index: int
    start: int
    end: int
    fs_type: str = ""
    hash_type: int = 0
    encryption: str = ""
    ctr_upper: bytes = b""

    @property
    def size(self) -> int:
        return self.end - self.start


@dataclass
class NcaHeader:
    magic: str
    content_type: str
    distribution: int
    key_generation: int
    key_area_index: int
    nca_size: int
    title_id: int
    sdk_version: int
    rights_id: bytes
    has_rights_id: bool
    encrypted_key_area: bytes
    sections: list[Section] = field(default_factory=list)


def parse_header(plain: bytes) -> NcaHeader:
    magic = plain[0x200:0x204].decode("latin1")
    if magic not in ("NCA2", "NCA3"):
        raise ValueError(f"bad NCA magic {magic!r}")
    dist, ctype, kg_old, kai = plain[0x204], plain[0x205], plain[0x206], plain[0x207]
    size, tid = struct.unpack_from("<QQ", plain, 0x208)
    sdk = struct.unpack_from("<I", plain, 0x21C)[0]
    kg_new = plain[0x220]
    rights = bytes(plain[0x230:0x240])
    hdr = NcaHeader(
        magic=magic, content_type=CONTENT_TYPES.get(ctype, f"?{ctype}"), distribution=dist,
        key_generation=max(kg_old, kg_new), key_area_index=kai, nca_size=size, title_id=tid,
        sdk_version=sdk, rights_id=rights, has_rights_id=any(rights),
        encrypted_key_area=bytes(plain[0x300:0x340]),
    )
    for i in range(4):
        s, e = struct.unpack_from("<II", plain, 0x240 + 16 * i)
        if e <= s:
            continue
        fh = plain[0x400 + 0x200 * i: 0x400 + 0x200 * (i + 1)]
        hdr.sections.append(Section(
            index=i, start=s * MEDIA_UNIT, end=e * MEDIA_UNIT,
            fs_type=FS_TYPES.get(fh[2], f"?{fh[2]}"), hash_type=fh[3],
            encryption=ENC_TYPES.get(fh[4], f"?{fh[4]}"), ctr_upper=bytes(fh[0x140:0x148]),
        ))
    return hdr


def key_area_key_name(hdr: NcaHeader) -> str:
    gen = max(hdr.key_generation - 1, 0)
    kind = {0: "application", 1: "ocean", 2: "system"}[hdr.key_area_index]
    return f"key_area_key_{kind}_{gen:02x}"


def decrypt_key_area(hdr: NcaHeader, keys: dict[str, bytes]) -> list[bytes]:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    kaek = keys[key_area_key_name(hdr)]
    d = Cipher(algorithms.AES(kaek), modes.ECB()).decryptor()
    ka = d.update(hdr.encrypted_key_area) + d.finalize()
    return [ka[i:i + 16] for i in range(0, 64, 16)]


# ---- section decryption (AES-CTR) and PartitionFS ------------------------

def ctr_iv(ctr_upper: bytes, byte_offset: int) -> bytes:
    """Section CTR: upper 8 bytes = header field reversed (BE), lower = offset/16 BE."""
    return bytes(reversed(ctr_upper)) + (byte_offset >> 4).to_bytes(8, "big")


def decrypt_ctr(key: bytes, ctr_upper: bytes, section_rel_off: int, data: bytes, section_abs_off: int) -> bytes:
    """Decrypt `data` read at section-relative `section_rel_off`.

    The counter is based on the offset from the NCA start (section start +
    relative offset), which must be 16-byte aligned for this helper.
    """
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    off = section_abs_off + section_rel_off
    if off % 16:
        raise ValueError("unaligned CTR offset")
    c = Cipher(algorithms.AES(key), modes.CTR(ctr_iv(ctr_upper, off))).decryptor()
    return c.update(data) + c.finalize()


def hierarchical_sha256_data_region(fs_header: bytes) -> tuple[int, int]:
    """(offset, size) of the data layer inside a HierarchicalSha256 section."""
    layers = struct.unpack_from("<I", fs_header, 0x8 + 0x20 + 4)[0]
    base = 0x8 + 0x20 + 8
    regions = [struct.unpack_from("<QQ", fs_header, base + 16 * i) for i in range(layers)]
    return regions[-1]


def parse_pfs0(buf: bytes) -> list[tuple[str, int, int]]:
    """(name, offset-in-buf, size) for a PFS0 image."""
    if buf[:4] != b"PFS0":
        raise ValueError("not PFS0")
    n, strsz = struct.unpack_from("<II", buf, 4)
    table = 0x10
    strs = table + 0x18 * n
    data0 = strs + strsz
    out = []
    for i in range(n):
        off, size, noff = struct.unpack_from("<QQI", buf, table + 0x18 * i)
        end = buf.index(b"\0", strs + noff)
        out.append((buf[strs + noff:end].decode("ascii"), data0 + off, size))
    return out


# ---- RomFS (inside IVFC) -------------------------------------------------

def ivfc_data_level(fs_header: bytes) -> tuple[int, int]:
    """(offset, size) of the data level (last IVFC level) within the section."""
    if fs_header[8:12] != b"IVFC":
        raise ValueError("not IVFC")
    levels = struct.unpack_from("<I", fs_header, 0x8 + 0xC)[0]
    n = max(levels - 1, 1)  # header counts the master-hash level; 6 data levels
    base = 0x8 + 0x10
    regions = [struct.unpack_from("<QQ", fs_header, base + 24 * i) for i in range(n)]
    return regions[-1]


def parse_romfs_tables(read, size_limit: int | None = None):
    """Walk a RomFS image through read(offset, size)->bytes (plaintext).

    Returns list of (path, data_offset_in_romfs, size).
    """
    hdr = read(0, 0x50)
    (_hs, _dho, _dhs, dmo, dms, _fho, _fhs, fmo, fms, data_off) = struct.unpack_from("<10Q", hdr, 0)
    dirs = read(dmo, dms)
    files = read(fmo, fms)

    def dname(off):
        parent, sib, child, ffile, nxt, nlen = struct.unpack_from("<IIIIII", dirs, off)
        return parent, sib, child, ffile, dirs[off + 24: off + 24 + nlen].decode("utf-8", "replace")

    out: list[tuple[str, int, int]] = []

    def walk(doff, prefix):
        _p, _s, child, ffile, _n = dname(doff)
        fo = ffile
        while fo != 0xFFFFFFFF:
            parent, sib, doffs, dsize, nxt, nlen = struct.unpack_from("<IIQQII", files, fo)
            name = files[fo + 32: fo + 32 + nlen].decode("utf-8", "replace")
            out.append((prefix + name, data_off + doffs, dsize))
            fo = sib
        co = child
        while co != 0xFFFFFFFF:
            _pp, csib, _cc, _cf, cname = dname(co)
            walk(co, prefix + cname + "/")
            co = csib

    walk(0, "")
    return out
