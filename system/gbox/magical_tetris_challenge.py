"""Magical Tetris Challenge (Europe, PS1, SCES-021.54) native container reader.

Source identity (verified by streaming bytes, see tests): CHD sha256 5b81fb5c...c61c9a; disc is one MODE2/2352 data
track + one CD-DA track; ISO9660 holds 98 files.

PAC layout (verified on all 59 BIN/*.PAC of this build):
  u32 count, u32 total_size (== file size, multiple of 0x800)
  count x (u32 type, u32 size)          (little endian; size = unpadded payload bytes)
  payload i starts at 0x800 + sum(align(size_j, 0x800) for j < i)
The sum of aligned payloads + 0x800 equals total_size. Types are chunk kinds (5 = bulk graphics/mesh data in
PLxxxx.PAC, 6 = small table); their meaning is NOT established yet - only the container is.

PS-X EXE: SCES_021.54 starts with 'PS-X EXE'; load address/entry are read from the header, not assumed.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

ALIGN = 0x800


def _align(n: int, a: int = ALIGN) -> int:
    return (n + a - 1) // a * a


@dataclass(frozen=True)
class Chunk:
    index: int
    type: int
    size: int       # unpadded
    offset: int     # byte offset of the payload inside the PAC


def parse_pac(data: bytes) -> list[Chunk]:
    """Chunk table of a PAC. Raises ValueError unless counts, sizes and offsets are all consistent."""
    if len(data) < 8:
        raise ValueError("PAC too short")
    count, total = struct.unpack_from("<II", data, 0)
    if not 0 < count <= (ALIGN - 8) // 8:
        raise ValueError(f"implausible PAC chunk count {count}")
    if total != len(data) or total % ALIGN:
        raise ValueError(f"PAC total {total:#x} != file size {len(data):#x}")
    out, off = [], ALIGN
    for i in range(count):
        typ, size = struct.unpack_from("<II", data, 8 + 8 * i)
        if off + size > total:
            raise ValueError(f"chunk {i} runs past end of PAC")
        out.append(Chunk(i, typ, size, off))
        off += _align(size)
    if off != total:
        raise ValueError(f"aligned chunks end at {off:#x}, PAC total is {total:#x}")
    return out


def chunk_bytes(data: bytes, c: Chunk) -> bytes:
    return data[c.offset:c.offset + c.size]


def parse_psx_exe(data: bytes) -> dict:
    if data[:8] != b"PS-X EXE":
        raise ValueError("not a PS-X EXE")
    pc, gp, load, size = struct.unpack_from("<IIII", data, 0x10)
    sp = struct.unpack_from("<I", data, 0x30)[0]
    if size != len(data) - 0x800:
        raise ValueError(f"EXE text size {size:#x} != file size - 0x800")
    return {"pc": pc, "gp": gp, "load": load, "size": size, "sp": sp}


def tim_header(data: bytes) -> dict | None:
    """Parse a PS1 TIM header (flag/bpp, CLUT, image rect) or None if data is not a TIM."""
    if len(data) < 20 or struct.unpack_from("<I", data, 0)[0] != 0x10:
        return None
    flag = struct.unpack_from("<I", data, 4)[0]
    bpp = {0: 4, 1: 8, 2: 16, 3: 24}.get(flag & 3)
    if bpp is None or flag & ~0xB:
        return None
    o, clut = 8, None
    if flag & 8:
        bnum, x, y, w, h = struct.unpack_from("<IHHHH", data, o)
        if bnum != 12 + w * h * 2:
            return None
        clut = (x, y, w, h)
        o += bnum
    if o + 12 > len(data):
        return None
    bnum, x, y, w, h = struct.unpack_from("<IHHHH", data, o)
    if bnum != 12 + w * h * 2 or o + bnum > len(data):
        return None
    return {"bpp": bpp, "clut": clut, "rect": (x, y, w, h)}
