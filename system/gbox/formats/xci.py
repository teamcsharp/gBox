"""Nintendo Switch game-card (XCI) container classification.

Two on-disk layouts exist and only one is readable without the console header key:

  standard  : bytes[0:4] == b"XCI0".  A plaintext header sits at 0x100 (image size,
              sector size, header size) and the NCSD partition table at 0x7000.  The
              HFS0 "secure" / "update" / "normal" partition tables are plaintext and
              walkable via :func:`gbox.formats.hfs0`.

  headerless: bytes[0x100:0x104] == b"HEAD" (the "headless" card dump produced by
              some flashers).  The NCSD partition table at 0x7000 is stored **encrypted
              (AES-XTS with the per-console header key)**, so the partition layout and
              every file inside cannot be enumerated without that key.  Offset 0x7000
              reads as a block of 0xFF / high-entropy bytes and the 0x100 header fields
              decode to nonsense (sector size 0xFFFFFFFF, header size in the hundreds
              of megabytes).

This module deliberately does **not** attempt to decrypt anything.  It classifies the
container, reports whether the partition table is readable, and points plaintext HFS0
walking at the shared :mod:`gbox.formats.hfs0` reader (which implements the real
0x40-byte entry layout, not the stale 24-byte layout this module once bundled).

``classify`` is the honest gate a title reader calls before claiming it can inventory a
Switch card: a headerless card whose NCSD slot is 0xFF-filled is reported as a concrete
prerequisite (``header_key_required``), never silently mis-listed.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from . import hfs0

# XCI header magic (standard card) and headerless signature (at 0x100).
XCI_MAGIC = b"XCI0"
HEADLESS_MAGIC = b"HEAD"
# NCSD partition table offset (standard card only).
NCSD_OFFSET = 0x7000
# A header is "encrypted" when its NCSD slot is blank-filled.
_FILL = b"\xff"

HFS0_MAGIC = hfs0.MAGIC


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
    # plaintext HFS0 magic offsets in the head region (audit aid)
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


def read_hfs0(read_at, base: int, file_size: int | None = None) -> list[hfs0.Hfs0Entry]:
    """Parse a plaintext HFS0 table at ``base`` via the shared reader; raises ValueError if absent/invalid.

    ``read_at(offset, size) -> bytes`` reads absolute bytes from the image.  Returned
    ``Hfs0Entry.offset`` fields are absolute image offsets.
    """
    return hfs0.parse_hfs0(read_at, base, file_size)
