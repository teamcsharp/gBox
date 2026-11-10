"""Prince of Persia: Warrior Within (GameCube, G2OE41) prince.bf 'BIG' archive TOC parser.

Layout proven against the owned build (343834624-byte prince.bf, disc offset 438532488):
  0x00 'BIG\\0'   0x04 u32 version (0x26)   0x08 u32 entry_count (2490)   0x0c u32 5
  0x44 entry_count * 8-byte records (u32 offset, u32 key), little-endian, offsets ascending,
  every offset < archive size, 0x800-aligned.
  Each payload starts with a u32 LE size such that size+4 fits the slot to the next offset
  (slack < 0x800). Verified for all 2490 entries. The key's meaning (name hash / type) is
  UNKNOWN; no names exist in the TOC.
Read-only; no model/texture decoding is claimed here.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"BIG\x00"
TOC_OFFSET = 0x44
ALIGN = 0x800


@dataclass(frozen=True)
class BigEntry:
    index: int
    offset: int
    key: int
    slot_size: int      # distance to next entry (or archive end)


class BigError(ValueError):
    pass


def parse_toc(head: bytes, archive_size: int) -> tuple[int, list[BigEntry]]:
    """Parse the header+TOC from the first bytes of the archive. Returns (version, entries)."""
    if head[:4] != MAGIC:
        raise BigError("bad magic %r" % head[:4])
    version, count = struct.unpack_from("<II", head, 4)
    if TOC_OFFSET + count * 8 > len(head):
        raise BigError("head too short for %d entries" % count)
    raw = [struct.unpack_from("<II", head, TOC_OFFSET + 8 * i) for i in range(count)]
    entries = []
    for i, (off, key) in enumerate(raw):
        nxt = raw[i + 1][0] if i + 1 < count else archive_size
        if off >= archive_size or nxt < off or off % ALIGN:
            raise BigError("entry %d offset 0x%x out of range/unaligned" % (i, off))
        entries.append(BigEntry(i, off, key, nxt - off))
    return version, entries


def payload_size(first4: bytes) -> int:
    """Leading u32 LE payload size of an entry (payload follows the 4 bytes)."""
    return struct.unpack("<I", first4[:4])[0]


def open_from_disc(disc, name: str = "prince.bf"):
    """disc: gbox.pop_ww_inventory.PoPWWDisc. Returns (base_offset, archive_size, version, entries)."""
    base, size = disc.files[name]
    head = disc.read_range(base, 0x44 + 8 * struct.unpack("<I", disc.read_range(base + 8, 4))[0])
    version, entries = parse_toc(head, size)
    return base, size, version, entries
