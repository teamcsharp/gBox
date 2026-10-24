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
