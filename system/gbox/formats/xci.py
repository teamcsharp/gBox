"""Nintendo Switch game-card (XCI) container classification and HFS0 table reading.

Two on-disk layouts exist and only one is readable without the console header key:

  standard  : bytes[0:4] == b"XCI0".  A plaintext header sits at 0x100 (image size,
              sector size, header size) and the NCSD partition table at 0x7000.  The
              HFS0 "secure" / "update" / "normal" partition tables are plaintext and
              walkable with :func:`read_hfs0`.
  headerless: bytes[0x100:0x104] == b"HEAD" (the "headless" card dump produced by
              some flashers).  The NCSD partition table at 0x7000 is stored **encrypted
              (AES-XTS with the per-console header key)**, so the partition layout and
              every file inside cannot be enumerated without that key.  Offset 0x7000
              reads as a block of 0xFF / high-entropy bytes and the 0x100 header fields
              decode to nonsense (sector size 0xFFFFFFFF, header size in the hundreds
              of megabytes).

This module deliberately does **not** attempt to decrypt anything.  It classifies the
container, reports whether the partition table is readable, and parses only plaintext
HFS0 tables it can actually find.  An encrypted container is reported as a concrete
prerequisite (``header_key_required``), never silently mis-listed.

gBox never bypasses ownership or decryption; :func:`classify` is the honest gate a
title reader calls before claiming it can inventory a Switch card.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

# XCI header magic (standard card) and headerless signature (at 0x100).
XCI_MAGIC = b"XCI0"
HEADLESS_MAGIC = b"HEAD"
# NCSD partition table offset (standard card only).
NCSD_OFFSET = 0x7000
# A header is "encrypted" when its NCSD slot is blank-filled.
_FILL = b"\xff"

HFS0_MAGIC = b"HFS0"


@dataclass(frozen=True)
class Hfs0Entry:
    """One file inside a plaintext HFS0 table."""

    name: str
    offset: int   # file start relative to the HFS0 header
    size: int
    hash_offset: int
    hash_size: int


@dataclass
class Hfs0Table:
    header_offset: int
    file_count: int
    string_table_size: int
    entries: list[Hfs0Entry] = field(default_factory=list)


@dataclass
class XciInfo:
    path: str
    size: int
    layout: str                 # "standard" | "headerless" | "unknown"
    partition_table_readable: bool
    header_key_required: bool
    notes: list[str] = field(default_factory=list)
    # headerless header fields (raw, for audit -- meaningless when encrypted)
    image_size: int = 0
    sector_size: int = 0
    # plaintext HFS0 tables discovered by a scan of the head region (audit aid)
    plaintext_hfs0: list[dict] = field(default_factory=list)


def _u32(b: bytes, off: int) -> int:
    return struct.unpack_from("<I", b, off)[0]


def classify(head: bytes, total_size: int, path: str = "") -> XciInfo:
    """Classify an XCI from its first ``len(head)`` bytes (>= 0x7040 recommended).

    No decryption is performed.  ``header_key_required`` is set for headerless cards
    whose NCSD slot is filled with 0xFF (i.e. the partition table is not plaintext).
    """
    notes: list[str] = []
    if len(head) < 0x104:
        return XciInfo(path, total_size, "unknown", False, False,
                       ["head too short to classify"])

    standard = head[0:4] == XCI_MAGIC
    headless = head[0x100:0x104] == HEADLESS_MAGIC

    # NCSD slot: a standard card has a plaintext (mostly non-0xFF) partition table.
    ncsd = head[NCSD_OFFSET:NCSD_OFFSET + 0x40] if len(head) >= NCSD_OFFSET + 0x40 else b""
    ncsd_filled = ncsd == b"" or ncsd == _FILL * len(ncsd) or ncsd.count(0x00) == len(ncsd)

    if standard and not ncsd_filled:
        layout = "standard"
        readable = True
        key_required = False
    elif headless and (ncsd_filled or _header_sane(head) is False):
        layout = "headerless"
        # Partition table at 0x7000 is encrypted (AES-XTS, per-console header key).
        readable = False
        key_required = True
        notes.append(
            "headerless XCI: NCSD partition table @0x7000 is encrypted "
            "(AES-XTS, per-console header key); files not enumerable without it"
        )
    elif standard:
        layout = "standard"
        readable = False
        key_required = False
        notes.append("standard magic but NCSD slot looks empty/encrypted")
    else:
        layout = "unknown"
        readable = False
        key_required = False
        notes.append("neither XCI0 nor HEAD signature located")

    image_size = _u32(head, 0x104) if len(head) >= 0x108 else 0
    sector_size = _u32(head, 0x108) if len(head) >= 0x10C else 0
    info = XciInfo(path, total_size, layout, readable, key_required, notes,
                   image_size, sector_size)
    # audit aid: surface any plaintext HFS0 magic in the head region
    for off in _find_hfs0_offsets(head):
        info.plaintext_hfs0.append({"offset": off})
    return info


def _header_sane(head: bytes) -> bool:
    """True only if the 0x100 header fields decode to plausible values."""
    if len(head) < 0x10C:
        return False
    sector = _u32(head, 0x108)
    header_size = _u32(head, 0x110) if len(head) >= 0x114 else 0
    return sector in (0x200,) and header_size <= 0x400


def _find_hfs0_offsets(head: bytes) -> list[int]:
    out: list[int] = []
    for off in range(0, len(head) - 4, 4):
        if head[off:off + 4] == HFS0_MAGIC:
            out.append(off)
    return out


def read_hfs0(read_at, base: int, max_files: int = 100_000) -> Hfs0Table:
    """Parse a plaintext HFS0 table whose header starts at ``base``.

    ``read_at(offset, size) -> bytes`` reads absolute bytes from the image.  Raises
    ValueError if the magic is absent or the header is not self-consistent.
    """
    hdr = read_at(base, 16)
    if len(hdr) < 16 or hdr[0:4] != HFS0_MAGIC:
        raise ValueError(f"no HFS0 magic at {base}")
    file_count = _u32(hdr, 4)
    string_table_size = _u32(hdr, 8)
    if file_count == 0 or file_count > max_files:
        raise ValueError(f"implausible HFS0 file_count={file_count}")
    entries_bytes = read_at(base + 16, file_count * 24)
    if len(entries_bytes) < file_count * 24:
        raise ValueError("truncated HFS0 entry table")
    names_bytes = read_at(base + 16 + file_count * 24, string_table_size)
    if len(names_bytes) < string_table_size:
        raise ValueError("truncated HFS0 string table")
    entries: list[Hfs0Entry] = []
    for i in range(file_count):
        s = i * 24
        (name_off, name_size, hash_off, hash_size) = struct.unpack_from(
            "<IIII", entries_bytes, s)[:4]
        name = names_bytes[name_off:name_off + name_size].decode("utf-8", "replace")
        data_off = base + 16 + file_count * 24 + string_table_size
        entries.append(Hfs0Entry(name, data_off + hash_off, hash_size,
                                 hash_off, hash_size))
    return Hfs0Table(base, file_count, string_table_size, entries)
