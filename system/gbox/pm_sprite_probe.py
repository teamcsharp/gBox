"""Paper Mario (USA) N64 sprite probe (#1673 analysis): CI4 raster + RGBA5551 palette -> PNG, stdlib only.

Reuses ``pm_inventory`` for the ROM parse. Verified layout (decomp src/sprite.c + tools/splat_ext/sprite.py, re-checked
here against the ROM):

* player sprite i (Yay0) uses raster set i; set i owns ``count`` consecutive packed load descriptors
  {size/16 in bits 20-31, pool offset in bits 0-19, relative to the player raster table}. A descriptor's
  *cache position* is the running sum of the sizes of the earlier descriptors of that set; the sprite's raster record
  ``{s32 cache_pos, u8 w, u8 h, u8 default_palette}`` must equal it (checked by ``player_raster``).
* pixels are uncompressed CI4 (two pixels per byte, high nibble first), ``w*h//2`` bytes at the pool offset.
* NPC raster record ``{u32 image, u8 w, u8 h, u8 palette, 0xFF}``: pixels are inside the decompressed sprite.
* palettes are 16 big-endian RGBA5551 colours (32 B); colour index 0 is drawn transparent.
Writer limits: raster <= 0xFFF0 B (12-bit size/16), pool offset < 2**20, 16 colours per palette.
"""
from __future__ import annotations

import struct
import zlib

from . import pm_inventory as pm


def rgba5551(c: int) -> tuple[int, int, int, int]:
    e = lambda v: (v << 3) | (v >> 2)
    return e((c >> 11) & 31), e((c >> 6) & 31), e((c >> 1) & 31), 255 if c & 1 else 0


def ci4_to_png(pix: bytes, w: int, h: int, pal: bytes) -> bytes:
    """8-bit RGBA PNG (stdlib zlib). Palette index 0 is fully transparent, matching the game's CI4 TLUT use."""
    if len(pal) < 32 or len(pix) < w * h // 2:
        raise ValueError("short palette or pixel data")
    cols = [rgba5551(v) for v in struct.unpack(">16H", pal[:32])]
    rows = []
    for y in range(h):
        row = bytearray([0])
        for x in range(w):
            i = y * w + x
            n = (pix[i >> 1] >> 4) if not i & 1 else pix[i >> 1] & 15
            row += bytes((0, 0, 0, 0)) if n == 0 else bytes(cols[n])
        rows.append(bytes(row))

    def chunk(t: bytes, d: bytes) -> bytes:
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def _lists(d: bytes):
    rl, pl = struct.unpack_from(">II", d, 0)
    return pm.offset_list(d, rl), pm.offset_list(d, pl)


def player_sprite(rom: bytes, index: int) -> dict:
    """Decode player sprite ``index`` rasters via its raster set; asserts every cache_pos matches the decomp rule."""
    hdr = pm.sprite_header(rom)
    base = hdr["player_rasters"]
    ranges, info, ci4 = struct.unpack_from(">III", rom, base)
    starts = struct.unpack_from(f">{(info - ranges) // 4}I", rom, base + ranges)
    descs = struct.unpack_from(f">{(ci4 - info) // 4}I", rom, base + info)
    s, e = pm._yay0_table(rom, hdr["player_yay0"], hdr["npc_yay0"], 13)[index]
    d = pm.yay0_decompress(rom, s)
    ras, pals = _lists(d)
    first, count = starts[index], starts[index + 1] - starts[index]
    if count != len(ras):
        raise ValueError(f"set {index} has {count} descriptors but sprite lists {len(ras)} rasters")
    pos, out = 0, []
    for j, ro in enumerate(ras):
        cache_pos, w, h, pal = struct.unpack_from(">iBBB", d, ro)
        v = descs[first + j]
        size, off = (v >> 20) << 4, v & 0xFFFFF
        if cache_pos != pos:
            raise ValueError(f"raster {j}: cache_pos {cache_pos} != running {pos}")
        pos += size
        out.append({"index": j, "w": w, "h": h, "palette": pal, "pool_offset": off, "size": size,
                    "pixels": rom[base + off: base + off + w * h // 2]})
    return {"palettes": [d[p:p + 32] for p in pals], "rasters": out}


def npc_sprite(rom: bytes, index: int) -> dict:
    hdr = pm.sprite_header(rom)
    s, e = pm._yay0_table(rom, hdr["npc_yay0"], hdr["end"])[index]
    d = pm.yay0_decompress(rom, s)
    ras, pals = _lists(d)
    out = []
    for j, ro in enumerate(ras):
        img, w, h, pal, tail = struct.unpack_from(">IBBBB", d, ro)
        out.append({"index": j, "w": w, "h": h, "palette": pal, "pixels": d[img:img + w * h // 2]})
    return {"palettes": [d[p:p + 32] for p in pals], "rasters": out}


def raster_png(spr: dict, j: int, pal: int | None = None) -> bytes:
    r = spr["rasters"][j]
    return ci4_to_png(r["pixels"], r["w"], r["h"], spr["palettes"][r["palette"] if pal is None else pal])
