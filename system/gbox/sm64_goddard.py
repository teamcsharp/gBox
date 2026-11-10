"""Read-only locator for Mario 64's uncompressed Goddard (boot head) texture bank.

Evidence (owned NTSC-U ROM): the Goddard engine segment is raw (not MIO0) and ends where the
first MIO0 block starts (0x24A320).  Its texture bank is a run of 32x32 RGBA16 tiles whose
background is 0x3800 (dark, alpha 0), found at 0x23A000..0x244FFF.  This module only locates
and decodes tiles; it never writes.  A textured head-projection writer additionally needs the
Goddard vertex/UV data and is NOT implemented (see docs/sprite-face-editor.md).
"""
from __future__ import annotations
import struct

TILE_W = TILE_H = 32
TILE_BYTES = TILE_W * TILE_H * 2
BG = 0x3800
SEARCH = (0x230000, 0x24A320)


def _is_tile(rom: bytes, off: int) -> bool:
    w = struct.unpack_from('>%dH' % (TILE_W * TILE_H), rom, off)
    return w.count(BG) >= TILE_W * TILE_H // 4 and len(set(w)) >= 2


def find_tiles(rom: bytes, search: tuple[int, int] = SEARCH) -> list[int]:
    """Offsets of 0x800-aligned 32x32 RGBA16 tiles with the Goddard 0x3800 transparent background."""
    lo, hi = search
    if len(rom) < hi:
        return []
    return [o for o in range(lo, hi - TILE_BYTES + 1, TILE_BYTES) if _is_tile(rom, o)]


def decode_tile(rom: bytes, off: int) -> list[tuple[int, int, int, int]]:
    out = []
    for v in struct.unpack_from('>%dH' % (TILE_W * TILE_H), rom, off):
        r, g, b = (v >> 11) & 31, (v >> 6) & 31, (v >> 1) & 31
        out.append((r * 255 // 31, g * 255 // 31, b * 255 // 31, 255 if v & 1 else 0))
    return out
