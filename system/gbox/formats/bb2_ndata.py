"""Bushido Blade 2 (PSX, USA SLUS-00663) NDATA archive reader.

Verified against the owned disc image (bin sha256
8d85a6753fda0381813b25174c07269df5b7137d56c70a73e5666dc380f921ea):

* ``NDATA/NDATA.INF`` is an array of little-endian ``(sector:u16, nsectors:u16)``
  records (2048-byte sectors into ``NDATA/NDATA.DAT``). 0xFFFF/0xFFFF marks an
  absent slot.  899 slots are used; the file has 901 dwords (trailing sentinel
  ``ffffffff`` + two words of padding/unknown).
* The slot *names* live in the boot EXE as a table of 899 u32 pointers
  (file offset 0x85de0 of SLUS_006.63) to ``DATAn\\NAME.DAT`` strings, in slot order.
* Each ``DATA0\\M###.DAT`` (character/fighter bank, 39 slots) starts with
  ``u32 n_sections`` followed by ``n_sections+1`` u32 byte offsets (the first equals
  4*(n+2); the last is the end-of-payload offset).  Sections are variable; section 0 is itself ``u32 count`` + offsets.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass

EXE_NAME_TABLE_OFFSET = 0x85DE0
SLOT_COUNT = 899
SECTOR = 2048
ABSENT = 0xFFFF


@dataclass(frozen=True)
class Slot:
    index: int
    name: str
    sector: int | None
    nsectors: int | None

    @property
    def present(self) -> bool:
        return self.sector is not None

    @property
    def offset(self) -> int:
        return (self.sector or 0) * SECTOR

    @property
    def size(self) -> int:
        return (self.nsectors or 0) * SECTOR


def parse_inf(inf: bytes, count: int = SLOT_COUNT):
    if len(inf) < count * 4:
        raise ValueError("NDATA.INF too short")
    out = []
    for i in range(count):
        s, n = struct.unpack_from("<HH", inf, i * 4)
        out.append(None if (s == ABSENT and n == ABSENT) else (s, n))
    last_end = 0
    for e in out:
        if e is None:
            continue
        if e[0] < last_end:
            raise ValueError("overlapping/non-monotonic INF record")
        last_end = e[0] + e[1]
    return out


def parse_name_table(exe: bytes, count: int = SLOT_COUNT,
                     table_offset: int = EXE_NAME_TABLE_OFFSET):
    """Resolve the slot-name pointer table in a PS-X EXE image."""
    if exe[:8] != b"PS-X EXE":
        raise ValueError("not a PS-X EXE")
    load, = struct.unpack_from("<I", exe, 0x18)
    base = load - 0x800
    names = []
    for i in range(count):
        p, = struct.unpack_from("<I", exe, table_offset + 4 * i)
        off = p - base
        if not 0 <= off < len(exe):
            raise ValueError(f"name pointer {i} out of range")
        m = re.match(rb"DATA\d\\[A-Z0-9_]+\.DAT", exe[off:off + 32])
        if not m:
            raise ValueError(f"slot {i}: bad name string")
        names.append(m.group().decode())
    return names


def build_slots(inf: bytes, exe: bytes):
    recs = parse_inf(inf)
    names = parse_name_table(exe)
    return [Slot(i, n, *(r or (None, None))) for i, (n, r) in enumerate(zip(names, recs))]


def parse_section_table(blob: bytes):
    """Return n+1 byte offsets (n section starts + end) of a Mxxx/Sxx style bank."""
    n, = struct.unpack_from("<I", blob, 0)
    if not 1 <= n <= 64:
        raise ValueError(f"implausible section count {n}")
    offs = list(struct.unpack_from(f"<{n + 1}I", blob, 4))
    if offs[0] != 4 * (n + 2) or any(b < a for a, b in zip(offs, offs[1:])) \
            or offs[-1] > len(blob):
        raise ValueError("section offsets not monotonic/in range")
    return offs


def read_slot(dat, slot: Slot) -> bytes:
    """``dat`` is a file object opened on NDATA.DAT."""
    dat.seek(slot.offset)
    data = dat.read(slot.size)
    if len(data) != slot.size:
        raise ValueError("short read")
    return data
