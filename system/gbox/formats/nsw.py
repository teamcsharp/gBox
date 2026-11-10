"""Nintendo Switch game-card images: XCI partition table, HFS0 file table, NCA header names.

This is a LISTING reader only -- it parses plaintext headers to enumerate what a card holds. It never decrypts
content: Hash0/HashIV/NAVI tables and NCA body sections (where asset data actually lives) are AES-encrypted with
titlekeys and out of scope here. It answers the assimilation question "what containers does this owned build
actually contain" for .xci files, which gbox.formats.disc refuses to list
("not a disc image, ROM, archive or folder gBox can list").

Layout facts used (plaintext regions):
  XCI0 (classic card): magic "XCI0" at 0; partition table at 0x1000: u64 LE image start offset, u64 LE image size,
        u16 LE header size, u8 header version, u8 flags, ASCII name padded with spaces to 16 ("HFS0PARTT").
  XCI HEAD variant (Switch cartridge image per `file`): "HEAD" magic at 0x100 (0..0xFF is an RSA signature), root HFS0 address at
        0x130 (u64 LE) pointing to a top-level HFS0 whose children are the real partitions (update/normal/secure).
        The secure partition contains the game's NCA files.
  HFS0: magic "HFS0" at 0; u32 LE file count (+4); u32 LE string pool size (+8);
        64-byte entries at +16 each: u64 LE data offset (relative to file-data start), u64 LE size,
        u32 LE name offset (into string pool), u32 LE header size, u64 LE ext; sha256 at +32.
        File data starts at base + 16 + count*64 + pool_size.
  NCA:  (NOTE: on retail cards NCA headers are AES-XTS encrypted, so header_names is usually empty.)
        magic "NCA3" at 0 with plaintext header-name strings at 0x200/0x220/0x240
        (main/program/control, e.g. "Qnv9CtUJy...").

Failure policy: truncated images and out-of-range offsets/counts raise ValueError; a non-XCI stream raises
ValueError, so callers never mistake a mislabelled file for a card.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import BinaryIO, Callable, List

XCI0_MAGIC = b"XCI0"
HEAD_MAGIC = b"HEAD"
HFS0_MAGIC = b"HFS0"
NCA3_MAGIC = b"NCA3"
XCI_PARTITION_TABLE_OFFSET = 0x1000
XCI_PARTITION_HEADER_SIZE = 0x20
# HEAD variant: root HFS0 address is a u64 LE at this offset
XCI_HEAD_MAGIC_OFFSET = 0x100
XCI_HEAD_ROOT_HFS0_OFFSET = 0x130
HFS0_ENTRY_SIZE = 64
HFS0_HEADER_SIZE = 16  # magic(4) + count(4) + pool_size(4) + pad(4)
# plaintext header-name slots inside an NCA header (main/program/control), fixed offsets
NCA_HEADER_NAME_SLOTS = (0x200, 0x220, 0x240)


@dataclass(frozen=True)
class XciPartition:
    name: str
    offset: int      # absolute byte offset of the partition image inside the .xci
    size: int
    version: int
    flags: int


@dataclass(frozen=True)
class Hfs0Entry:
    name: str
    offset: int      # absolute byte offset inside the .xci
    size: int
    sha256: str      # hex digest stored in the entry table (plaintext)


@dataclass
class XciInfo:
    partitions: List[XciPartition] = field(default_factory=list)
    hfs0: dict = field(default_factory=dict)          # partition name -> list[Hfs0Entry]
    ncas: List[dict] = field(default_factory=list)    # {partition, entry, offset, size, header_names}
    warnings: List[str] = field(default_factory=list)


def _read_at(read_at: Callable[[int, int], bytes], off: int, size: int) -> bytes:
    data = read_at(off, size)
    if len(data) != size:
        raise ValueError("truncated image reading %d bytes at offset 0x%x (got %d)" % (size, off, len(data)))
    return data


def _ascii(data: bytes) -> str:
    return data.split(b"\0", 1)[0].rstrip().decode("ascii", "replace")


def parse_xci_header(read_at: Callable[[int, int], bytes]) -> List[XciPartition]:
    """Parse the XCI partition table. Handles both classic XCI0 and HEAD variants."""
    magic = _read_at(read_at, 0, 4)
    parts: List[XciPartition] = []
    # Real cards: bytes 0..0xFF are an RSA signature; the "HEAD" magic sits at 0x100.
    if magic != XCI0_MAGIC and _read_at(read_at, XCI_HEAD_MAGIC_OFFSET, 4) == HEAD_MAGIC:
        magic = HEAD_MAGIC

    if magic == XCI0_MAGIC:
        # Classic XCI0: partition table at 0x1000
        off = XCI_PARTITION_TABLE_OFFSET
        while True:
            head = _read_at(read_at, off, XCI_PARTITION_HEADER_SIZE)
            start, size = struct.unpack_from("<QQ", head, 0)
            header_size, version, flags = struct.unpack_from("<HBB", head, 16)
            name = head[20:36].decode("ascii", "replace")
            if name.strip() == "HFS0PARTT":
                parts.append(XciPartition("HFS0PARTT", start, size, version, flags))
            if not flags & 1:  # bit 0 = more entries follow
                break
            off += max(header_size, XCI_PARTITION_HEADER_SIZE)
        if not parts:
            raise ValueError("XCI0 partition table has no HFS0PARTT entry")

    elif magic == HEAD_MAGIC:
        # HEAD variant: root HFS0 at offset stored at 0x130
        root_hfs0 = struct.unpack_from("<Q", _read_at(read_at, XCI_HEAD_ROOT_HFS0_OFFSET, 8), 0)[0]
        if root_hfs0 == 0:
            raise ValueError("HEAD variant: root HFS0 address is 0")
        # The root HFS0 contains sub-partitions (update, normal, secure).
        # Each is itself an HFS0 partition. We list them as XciPartition entries.
        entries = parse_hfs0(read_at, root_hfs0)
        for e in entries:
            parts.append(XciPartition(e.name, e.offset, e.size, 0, 0))
        if not parts:
            raise ValueError("HEAD variant: root HFS0 has no entries")

    else:
        raise ValueError("not an XCI image (magic %r at 0)" % magic)

    return parts


def parse_hfs0(read_at: Callable[[int, int], bytes], base: int) -> List[Hfs0Entry]:
    """HFS0 partition at absolute offset `base`: file table + string pool -> entries with absolute offsets.

    HFS0 layout:
      +0   magic "HFS0" (4 bytes)
      +4   u32 LE file count
      +8   u32 LE string pool size
      +12  u32 LE padding
      +16  64-byte file entries (count of them)
      +16 + count*64   string pool (pool_size bytes)
      +16 + count*64 + pool_size   file data
    """
    if _read_at(read_at, base, 4) != HFS0_MAGIC:
        raise ValueError("no HFS0 magic at 0x%x (found %r)" % (base, read_at(base, 4)))
    count, pool_size = struct.unpack_from("<II", _read_at(read_at, base + 4, 8), 0)
    if count == 0 and pool_size == 0:
        return []
    if pool_size > 1 << 28:
        raise ValueError("implausible HFS0 string pool size %d at 0x%x" % (pool_size, base))

    table_off = base + HFS0_HEADER_SIZE
    pool_off = table_off + count * HFS0_ENTRY_SIZE
    data_base = pool_off + pool_size
    pool = _read_at(read_at, pool_off, pool_size)

    entries = []
    for i in range(count):
        rec = _read_at(read_at, table_off + i * HFS0_ENTRY_SIZE, HFS0_ENTRY_SIZE)
        ext_off, size, name_off, _header_sz, _ext = struct.unpack_from("<QQIIQ", rec, 0)
        sha = rec[32:64].hex()
        if name_off >= pool_size:
            raise ValueError("HFS0 entry %d name offset %d outside pool (%d)" % (i, name_off, pool_size))
        end = pool.index(b"\0", name_off) if b"\0" in pool[name_off:] else pool_size
        entries.append(Hfs0Entry(
            pool[name_off:end].decode("ascii", "replace"),
            data_base + ext_off,
            size,
            sha,
        ))
    return entries


def read_nca_header_names(read_at: Callable[[int, int], bytes], nca_offset: int) -> List[str]:
    """Plaintext NCA3 header-name slots (main/program/control ids); [] if the member is not an NCA3."""
    if _read_at(read_at, nca_offset, 4) != NCA3_MAGIC:
        return []
    names = []
    for slot in NCA_HEADER_NAME_SLOTS:
        raw = _read_at(read_at, nca_offset + slot, 32)
        name = _ascii(raw)
        if name:
            names.append(name)
    return names


def _file_read_at(path: str) -> Callable[[int, int], bytes]:
    fh: BinaryIO = open(path, "rb")

    def read_at(off: int, size: int) -> bytes:
        fh.seek(off)
        return fh.read(size)

    read_at.close = fh.close  # type: ignore[attr-defined]
    return read_at


def list_xci(path: str) -> XciInfo:
    """Enumerate one owned .xci end-to-end: partitions, HFS0 file tables, NCA header names."""
    read_at = _file_read_at(path)
    try:
        return list_xci_from(read_at)
    finally:
        read_at.close()  # type: ignore[attr-defined]


def list_xci_from(read_at: Callable[[int, int], bytes]) -> XciInfo:
    info = XciInfo()
    info.partitions = parse_xci_header(read_at)
    for part in info.partitions:
        try:
            entries = parse_hfs0(read_at, part.offset)
        except ValueError as exc:  # encrypted/unreadable partition header: record, keep going
            info.warnings.append("partition %s: %s" % (part.name, exc))
            continue
        info.hfs0[part.name] = entries
        for e in entries:
            if e.size < 0x300:
                continue
            try:
                names = read_nca_header_names(read_at, e.offset)
            except ValueError:
                names = []
            if names:
                info.ncas.append({"partition": part.name, "entry": e.name, "offset": e.offset,
                                  "size": e.size, "sha256": e.sha256, "header_names": names})
    return info


def summarize(info: XciInfo) -> dict:
    return {"partitions": [{"name": p.name, "offset": p.offset, "size": p.size,
                            "version": p.version, "flags": p.flags} for p in info.partitions],
            "hfs0": {k: [{"name": e.name, "offset": e.offset, "size": e.size, "sha256": e.sha256}
                         for e in v] for k, v in info.hfs0.items()},
            "ncas": info.ncas,
            "warnings": info.warnings}


# --- NCA3 header decrypt + ExeFS (PFS0) reader (needs the owner's prod.keys; keys are never stored here) ---

def load_keys(path: str) -> dict:
    keys = {}
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if "=" in line:
                k, v = line.split("=", 1)
                try:
                    keys[k.strip()] = bytes.fromhex(v.strip())
                except ValueError:
                    pass
    return keys


def decrypt_nca_header(read_at: Callable[[int, int], bytes], nca_offset: int, header_key: bytes) -> bytes:
    """AES-128-XTS decrypt the 0xC00-byte NCA header; 0x200 sectors, tweak = big-endian sector number, sector 0 = NCA start."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    raw = _read_at(read_at, nca_offset, 0xC00)
    out = b""
    for i in range(6):
        c = Cipher(algorithms.AES(header_key), modes.XTS(i.to_bytes(16, "big"))).decryptor()
        out += c.update(raw[i * 0x200:(i + 1) * 0x200])
    if out[0x200:0x204] != NCA3_MAGIC:
        raise ValueError("NCA header did not decrypt to NCA3 (wrong header_key or not an NCA3)")
    return out


def nca_sections(h: bytes) -> List[dict]:
    secs = []
    for i in range(4):
        s, e = struct.unpack_from("<II", h, 0x240 + i * 16)
        if e <= s:
            continue
        fh = h[0x400 + i * 0x200:0x600 + i * 0x200]
        secs.append({"index": i, "start": s * 0x200, "end": e * 0x200, "fs_type": fh[2], "hash_type": fh[3],
                     "enc_type": fh[4], "ctr": fh[0x140:0x148]})
    return secs


def read_nca_section(read_at, nca_offset: int, h: bytes, keys: dict, sec: dict, rel: int, size: int) -> bytes:
    """Read `size` bytes at section-relative `rel`, decrypting AES-CTR (enc_type 3) with the key-area CTR key (key-area rights only)."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    off = sec["start"] + rel
    data = _read_at(read_at, nca_offset + off, size)
    if sec["enc_type"] == 1:
        return data
    if sec["enc_type"] != 3:
        raise ValueError("unsupported section encryption %d" % sec["enc_type"])
    if h[0x230:0x240] != bytes(16):
        raise ValueError("rights_id set: titlekey crypto not implemented here")
    gen = max(h[0x206], h[0x220]); gen = gen - 1 if gen > 0 else 0
    kek = keys["key_area_key_application_%02x" % gen]
    ka = Cipher(algorithms.AES(kek), modes.ECB()).decryptor().update(h[0x300:0x340])
    ctr_key = ka[0x10 * 2:0x10 * 3]
    base = off & ~0xF
    pad = off - base
    iv = sec["ctr"][::-1] + (base >> 4).to_bytes(8, "big")
    d = Cipher(algorithms.AES(ctr_key), modes.CTR(iv)).decryptor()
    return d.update(b"\0" * pad + data)[pad:]


def list_exefs(read_at, nca_offset: int, keys: dict) -> List[dict]:
    """ExeFS PFS0 members (name, section-relative offset, size) of a Program NCA whose first section is HierarchicalSha256 PFS0."""
    h = decrypt_nca_header(read_at, nca_offset, keys["header_key"])
    sec = nca_sections(h)[0]
    fh = h[0x400:0x600]
    bs, lc = struct.unpack_from("<II", fh, 0x28)
    doff, dsz = struct.unpack_from("<QQ", fh, 0x30 + (lc - 1) * 16)
    head = read_nca_section(read_at, nca_offset, h, keys, sec, doff, 0x4000)
    if head[:4] != b"PFS0":
        raise ValueError("section 0 data layer is not PFS0")
    cnt, strsz = struct.unpack_from("<II", head, 4)
    pool = 16 + cnt * 24
    names = head[pool:pool + strsz]
    out = []
    for i in range(cnt):
        o, sz, no = struct.unpack_from("<QQI", head, 16 + i * 24)
        out.append({"name": names[no:names.index(b"\0", no)].decode(), "offset": doff + pool + strsz + o, "size": sz})
    return out


def lz4_block_decompress(src: bytes, out_size: int) -> bytes:
    """Pure-python LZ4 block decoder (no frame header), as used by NSO segments."""
    out = bytearray()
    i, n = 0, len(src)
    while i < n:
        tok = src[i]; i += 1
        lit = tok >> 4
        if lit == 15:
            while True:
                b = src[i]; i += 1; lit += b
                if b != 255:
                    break
        out += src[i:i + lit]; i += lit
        if i >= n:
            break
        off = src[i] | (src[i + 1] << 8); i += 2
        if off == 0 or off > len(out):
            raise ValueError("bad LZ4 match offset")
        ml = tok & 15
        if ml == 15:
            while True:
                b = src[i]; i += 1; ml += b
                if b != 255:
                    break
        ml += 4
        s = len(out) - off
        for k in range(ml):
            out.append(out[s + k])
    if len(out) != out_size:
        raise ValueError("LZ4 size mismatch %d != %d" % (len(out), out_size))
    return bytes(out)


def parse_nso(data: bytes) -> dict:
    """Decompress an NSO0 image: returns segments {text,ro,data} (bytes + memory offset) and bss size.
    Verifies each segment against the SHA-256 in the header when the hash flag is set."""
    import hashlib
    if data[:4] != b"NSO0":
        raise ValueError("not NSO0")
    flags = struct.unpack_from("<I", data, 0xC)[0]
    segs = {}
    for idx, name in enumerate(("text", "ro", "data")):
        foff, moff, dsz = struct.unpack_from("<III", data, 0x10 + idx * 0x10)
        csz = struct.unpack_from("<I", data, 0x60 + idx * 4)[0]
        raw = data[foff:foff + (csz if flags & (1 << idx) else dsz)]
        seg = lz4_block_decompress(raw, dsz) if flags & (1 << idx) else raw
        if flags & (1 << (3 + idx)):
            if hashlib.sha256(seg).digest() != data[0xA0 + idx * 0x20:0xC0 + idx * 0x20]:
                raise ValueError("%s segment hash mismatch" % name)
        segs[name] = {"mem_offset": moff, "size": dsz, "data": seg}
    return {"segments": segs, "bss_size": struct.unpack_from("<I", data, 0x3C)[0], "build_id": data[0x40:0x60].hex()}


def read_exefs_member(read_at, nca_offset: int, keys: dict, name: str) -> bytes:
    h = decrypt_nca_header(read_at, nca_offset, keys["header_key"])
    sec = nca_sections(h)[0]
    f = next(x for x in list_exefs(read_at, nca_offset, keys) if x["name"] == name)
    return read_nca_section(read_at, nca_offset, h, keys, sec, f["offset"], f["size"])
