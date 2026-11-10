"""Madden NFL 2005 (GameCube, GNQE69) — PLYRFACE.DAT MMAP texture / face container (#2007).

Concrete codec identification from the owned disc bytes (read-only):

PLYRFACE.DAT is a TERF archive whose members are **uncompressed "MMAP" containers** — NOT
RefPack (no 0x10FB header). Each member holds a player portrait/face texture with a
GameCube RGB5A3 palette and an embedded ``FACE``/``FAC`` geometry block.

Observed MMAP header (big-endian), member[0] of PLYRFACE.DAT::

     0x00  "MMAP"                       magic
     0x04  u32  0x00020000              format version/flags
     0x08  u8[4] 01 02 03               4-component/bank order (see note)
     0x0c  u16  0x0002                  map count (2 texture regions)
     0x0e  u16  0x0002                  ?
     0x10  u32  0x00010000              ?
     0x14  u32  face_off = 0x2aa0       absolute offset of the FACE geometry block
     0x18  u32  pal_off  = 0x28         -> points into the region table start
     0x1c  u32  region1_off = 0x2860    first texture-region header
     0x20  u32  face_off2 = 0x2a80      "FACE" block (face geometry record)
     0x24  u32  ? = 0x2ab8
     0x28  region table:              repeated (dim_w u8, dim_h u8, pad u8, idx u8,
                                                       u32 unk, u32 pal_off, u32 data_off)
     0x28  u32  0x00800080  (128 x 128)   region 0 dimensions
     0x2c  u32  0x000e0000  (14)          region 0 palette entry count
     0x30  u32  0x00002000               region 0 palette byte offset (8 bytes/entry => 0x200)
     0x34  u32  0x00000060               region 0 pixel/index data offset
     0x38  u32  0x00400040  (64 x 64)     region 1 dimensions
     0x3c  u32  0x000e0000  (14)
     0x40  u32  0x00000800
     0x44  u32  0x00002060               region 1 pixel/index data offset
     ...

The RGB5A3 palette lives at member[0]+0x60 (14 x 8 = 0x70 bytes = 56 entries of 8 bytes,
i.e. 2 x RGBA5A3 per 8-byte word pair) and decodes to skin-tone colours, confirming big-endian
RGB5A3 (matches the GameCube's native 16-bit texture format).

0x2a80 "FACE" / 0x2ac0 "FAC" is the facial geometry block (vertex/index data) shared with
FACEGEOM.DAT members ("FAC\\0" ledger), i.e. the player's facial model, separate from the
portrait texture.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import List, Optional, Tuple

MMAP = b"MMAP"
FACE = b"FACE"
FAC = b"FAC\x00"
RGB5A3 = "rgb5a3"          # 16-bit big-endian, top bit = RGB565 else ARGB4444


@dataclass(frozen=True)
class MmapRegion:
    w: int
    h: int
    pal_entries: int
    flags: int
    word2: int      # u32 at +8  (unconfirmed): 0x2000 / 0x0800
    data_off: int   # u32 at +12 (confirmed to locate the palette / index data)


# Each region entry is 16 bytes = 4 big-endian u32 words:
#   word0 = (w << 16) | h              (confirmed: 0x00800080 -> 128x128, 0x00400040 -> 64x64)
#   word1 = (pal_entries << 16) | flags (confirmed: 0x000e0000 -> 14 palette entries)
#   word2 = ?                        (0x00002000 / 0x00000800, not yet confirmed)
#   word3 = data_off                 (0x60 / 0x2060; for region 0 this offsets the RGB5A3 palette)
_REGION_STRIDE = 16


@dataclass(frozen=True)
class MmapTexture:
    num_maps: int
    face_off: int
    regions: Tuple[MmapRegion, ...]
    palette_off: int
    palette: Tuple[Tuple[int, int, int, int], ...]   # decoded RGBA8
    raw_palette_bytes: bytes


def rgb5a3_word(w: int) -> Tuple[int, int, int, int]:
    """Decode one 16-bit big-endian RGB5A3 value to (r, g, b, a) 8-bit."""
    if w & 0x8000:
        r = (w >> 10) & 0x1F
        g = (w >> 5) & 0x1F
        b = w & 0x1F
        return (r * 255 // 31, g * 255 // 31, b * 255 // 31, 255)
    a = (w >> 12) & 0x7
    r = (w >> 8) & 0xF
    g = (w >> 4) & 0xF
    b = w & 0xF
    return (r * 255 // 15, g * 255 // 15, b * 255 // 15, a * 255 // 7)


def parse_mmap(data: bytes) -> MmapTexture:
    """Validate the MMAP header and decode the RGB5A3 palette + region table.

    Raises ValueError on an inconsistent header so the format claim stays falsifiable.
    """
    if len(data) < 0x48 or data[:4] != MMAP:
        raise ValueError("not a MMAP member (missing MMAP magic)")

    flags = struct.unpack_from(">I", data, 4)[0]
    num_maps = struct.unpack_from(">H", data, 0x0C)[0]
    if num_maps not in (1, 2):
        raise ValueError("unexpected MMAP map count %d" % num_maps)
    face_off = struct.unpack_from(">I", data, 0x14)[0]

    # Region table begins at 0x28; each region entry is 16 bytes (4 u32 words, see _REGION_STRIDE).
    regions: List[MmapRegion] = []
    p = 0x28
    for _ in range(num_maps):
        if p + _REGION_STRIDE > len(data):
            raise ValueError("region table overruns member at %#x" % p)
        w0 = struct.unpack_from(">I", data, p)[0]
        w1 = struct.unpack_from(">I", data, p + 4)[0]
        w2 = struct.unpack_from(">I", data, p + 8)[0]
        w3 = struct.unpack_from(">I", data, p + 12)[0]
        regions.append(MmapRegion(w0 >> 16, w0 & 0xFFFF, w1 >> 16, w1 & 0xFFFF, w2, w3))
        p += _REGION_STRIDE

    # Palette: region 0's data_off locates the RGB5A3 palette bytes with an 8-byte entry stride
    # (observed 14 entries => 0x70 bytes); decode 16-bit big-endian words.
    pal_off = regions[0].data_off
    pal_words = min(regions[0].pal_entries * 4, (len(data) - pal_off) // 2)
    if pal_words < regions[0].pal_entries:
        raise ValueError("palette overruns member at %#x" % pal_off)
    raw = bytes(data[pal_off:pal_off + pal_words * 2])
    palette = tuple(
        rgb5a3_word(struct.unpack_from(">H", raw, i)[0]) for i in range(0, pal_words * 2, 2)
    )
    return MmapTexture(num_maps, face_off, tuple(regions), pal_off, palette, raw)


def face_block_offsets(data: bytes) -> List[int]:
    """Offsets of every 'FACE' / 'FAC\\0' ledger inside a member (geometry blocks)."""
    out: List[int] = []
    i = 0
    while True:
        i = data.find(FACE, i)
        if i < 0:
            break
        out.append(i)
        i += 1
    return out
