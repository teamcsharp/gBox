"""Resident Evil - Dead Aim (PS2, SLUS-20669) IMAGE.BIN 'fpk' archive reader.

Evidence (owned USA CHD, request #1904): IMAGE.BIN is a nested little-endian
"fpk\\0" archive.  Layout of every fpk (offsets relative to the fpk start):
  0x00 magic 'fpk\\0', 0x08 version, 0x28 u32 payload_base, 0x2c u32 payload_size,
  0x40 64-byte archive name, 0x80.. 16-byte records
  [u32 0, u32 offset(rel. payload_base), u32 size, char[4] ext] (zero ext ends table).
Entries whose first 4 bytes are 'fpk\\0' are nested archives.  A character zone
(pcNNa.zone.bin) holds tsl (name list), tad, and mmo (mmodel.bin) whose first
entry is a 'CJFg' skeleton header (name + bone list, e.g. CJFgPC01A).
This is an inventory/reader only; no writer exists yet.
"""
from __future__ import annotations

import struct
from typing import Callable, Dict, List

FPK_MAGIC = b"fpk\0"
CJFG_MAGIC = b"CJFg"
ReadAt = Callable[[int, int], bytes]


def parse_fpk(read_at: ReadAt, base: int, depth: int = 0, path: str = "",
              out: List[Dict] | None = None, max_depth: int = 4) -> List[Dict]:
    """Walk an fpk archive recursively; return flat entry dicts (absolute offsets)."""
    out = [] if out is None else out
    head = read_at(base, 0xC0)
    if head[:4] != FPK_MAGIC:
        return out
    name = head[0x40:0x80].split(b"\0")[0].decode("latin1")
    payload_base = struct.unpack_from("<I", head, 0x28)[0]
    pos = 0x80
    idx = 0
    while pos + 16 <= payload_base:
        _pad, off, size, ext = struct.unpack("<III4s", read_at(base + pos, 16))
        if ext == b"\0\0\0\0":
            break
        absoff = base + payload_base + off
        magic = read_at(absoff, 4)
        entry = {"path": f"{path}/{name}", "idx": idx, "offset": absoff, "size": size,
                 "ext": ext.rstrip(b"\0").decode("latin1"), "magic": magic.hex(), "depth": depth}
        out.append(entry)
        if magic == FPK_MAGIC and depth < max_depth:
            parse_fpk(read_at, absoff, depth + 1, f"{path}/{name}#{idx}", out, max_depth)
        pos += 16
        idx += 1
    return out


def character_skeletons(read_at: ReadAt, entries: List[Dict]) -> List[Dict]:
    """Return 'CJFg' skeleton headers (character model slots) found in entries."""
    found = []
    for e in entries:
        if e["ext"] == "fjc" and e["magic"] == CJFG_MAGIC.hex():
            d = read_at(e["offset"], 0x40)
            found.append({"name": d[4:16].split(b"\0")[0].decode("latin1"),
                          "offset": e["offset"], "size": e["size"], "path": e["path"]})
    return found
