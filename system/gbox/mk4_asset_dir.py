"""MK4 (USA) N64 (NM4E rev 0) boot-loaded asset directory reader.

Derived from the game's own loader (ROM 0x37340-0x37454, VA 0x80036740 and
the init at 0x800367dc): it DMAs ROM 0x132810..0x1333B0 to RAM, then walks
big-endian u16 (id|0x8000 flag, size) records starting at ROM 0x132A10 until
id == 0xFFFF.  Asset ``id`` lives at a running ROM offset that starts at
ROM 0x1333B0 and advances by each record's size.  z64 byte order.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

DIR_START = 0x132810
DIR_END = 0x1333B0
RECORDS_START = 0x132A10  # first 0x200 bytes of the DMA'd block are copied elsewhere
DATA_BASE = 0x1333B0
TERMINATOR = 0xFFFF


@dataclass(frozen=True)
class AssetEntry:
    id: int
    flag: int
    offset: int
    size: int


def parse_asset_dir(rom: bytes, max_entries: int = 8192) -> list[AssetEntry]:
    out: list[AssetEntry] = []
    pos, off = RECORDS_START, DATA_BASE
    while len(out) < max_entries:
        if pos + 2 > len(rom):
            raise ValueError("directory runs past end of ROM")
        raw = struct.unpack_from(">H", rom, pos)[0]
        pos += 2
        if raw == TERMINATOR:
            return out
        if pos + 2 > len(rom):
            raise ValueError("truncated record")
        size = struct.unpack_from(">H", rom, pos)[0]
        pos += 2
        out.append(AssetEntry(raw & 0x7FFF, raw >> 15, off, size))
        off += size
    raise ValueError("no terminator within max_entries")


def read_asset(rom: bytes, e: AssetEntry) -> bytes:
    return rom[e.offset:e.offset + e.size]
