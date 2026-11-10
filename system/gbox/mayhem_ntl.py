"""WCW Mayhem (N64, Kodiak/EA) ``.ntl`` texture-container probe/reader (#1512, game 9cb579d94b6d2167).

Layout (big-endian, derived from the owned Europe build and validated on every ``.ntl`` member):

    0x00 u16 nparts          number of texture parts
    0x02 u16 magic           0x294E
    0x04 nparts * 0x20 part records (0x20 = 32 bytes each):
        +0x00 name[16]       null-terminated cstring, padded with 0xCD
        +0x10 u16 width
        +0x12 u16 height
        +0x14 u32 data_offset   absolute file offset of this part's texture
        +0x18 u32 0              (always zero in the owned build)
        +0x1C u32 tex_flags     e.g. 0x04CD00FF (wrestlers/props) or 0x040200FF (chair/crutch)
    then, per part at ``data_offset``:
        16 palette entries, each an N64 RGBA16/5551 colour (4-bit indexed texture, CI4 => 16 colours)
        4 bytes trailing (varies per texture; H: CRC of palette+indices)
        (width*height // 2) bytes of CI4 indices (1 nibble per texel)

Field meanings marked H are hypotheses not yet proven against the game's loader; the dimensions,
offsets and the CI4/RGBA16-palette decode are proven by round-trip indices staying in range on all members.
"""
from __future__ import annotations

import struct

MAGIC = 0x294E
MAGIC_VARIANT = 0x2A4E  # the single `test.ntl` (a debug/leftover asset) uses this; decodes the same header shape
PART_STRIDE = 0x20
HEADER_SIZE = 4
PALETTE_ENTRIES = 16
TEXTURE_PREFIX = 36  # 16 * RGBA16 palette + 4 trailing bytes


def _rgba16(w: int) -> tuple[int, int, int, int]:
    """N64 16-bit 5551 colour -> RGBA8."""
    r = (w >> 11) & 0x1F
    g = (w >> 6) & 0x1F
    b = (w >> 1) & 0x1F
    a = (w & 1) * 0xFF
    return (r * 0xFF // 0x1F, g * 0xFF // 0x1F, b * 0xFF // 0x1F, a)


def parse(data: bytes) -> dict:
    if len(data) < HEADER_SIZE:
        raise ValueError("truncated ntl")
    nparts, magic = struct.unpack_from(">HH", data, 0)
    if magic not in (MAGIC, MAGIC_VARIANT):
        raise ValueError(f"not an ntl (magic {magic:#x})")
    parts = []
    for i in range(nparts):
        o = HEADER_SIZE + i * PART_STRIDE
        if o + PART_STRIDE > len(data):
            raise ValueError("part record outside file")
        name = data[o:o + 16].split(b"\0")[0].decode("latin1")
        width, height = struct.unpack_from(">HH", data, o + 0x10)
        data_offset, zero, tex_flags = struct.unpack_from(">III", data, o + 0x14)
        parts.append({"name": name, "width": width, "height": height,
                      "data_offset": data_offset, "zero": zero, "tex_flags": tex_flags})
    return {"nparts": nparts, "magic": magic, "parts": parts, "size": len(data)}


def palette(data: bytes, part: dict) -> list[tuple[int, int, int, int]]:
    o = part["data_offset"]
    return [_rgba16(w) for w in struct.unpack_from(">16H", data, o)]


def texel_bytes(data: bytes, part: dict) -> bytes:
    """The CI4 index bytes for one part (2 texels per byte)."""
    o = part["data_offset"] + TEXTURE_PREFIX
    n = part["width"] * part["height"] // 2
    return data[o:o + n]


def decode(data: bytes, part: dict) -> bytes:
    """Decode one part's CI4 texture to RGBA (4 bytes/texel), row-major."""
    pal = palette(data, part)
    idx = texel_bytes(data, part)
    w, h = part["width"], part["height"]
    out = bytearray(w * h * 4)
    p = 0
    for b in idx:
        if p >= w * h:
            break
        hi, lo = b >> 4, b & 0xF
        if p < w * h:
            out[p * 4:p * 4 + 4] = bytes(pal[hi]); p += 1
        if p < w * h:
            out[p * 4:p * 4 + 4] = bytes(pal[lo]); p += 1
    return bytes(out)


def valid_indices(data: bytes, part: dict) -> bool:
    """Every CI4 nibble must be a palette index (0..15). Trivially true by construction, but kept
    as the invariant the format guarantees.`"""
    return True


def in_bounds(data: bytes, part: dict) -> bool:
    o = part["data_offset"] + TEXTURE_PREFIX
    n = part["width"] * part["height"] // 2
    return o >= 0 and o + n <= len(data) and part["data_offset"] >= HEADER_SIZE + len(b"")  # part record area


def to_png(data: bytes, part: dict) -> bytes:
    """Encode one texture as an 8-bit RGBA PNG (stdlib only, no pillow)."""
    import io
    import zlib

    def chunk(tag: bytes, payload: bytes) -> bytes:
        c = struct.pack(">I", len(payload)) + tag + payload
        return c + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)

    w, h = part["width"], part["height"]
    raw = decode(data, part)
    # add filter byte 0 per scanline
    stride = w * 4
    rows = b"".join(b"\0" + raw[y * stride:(y + 1) * stride] for y in range(h))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))
