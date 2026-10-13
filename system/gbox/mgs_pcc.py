"""PS1 Metal Gear Solid textures (.pcc entries of a texture DAR): native decode / encode.

Layout, verified on all 128 textures of the US VR Missions init/1_0.dar (decode == MetalMintSolid's PNGs):

* a ZSoft PCX header (0x80 bytes): 0x0A, version 5, RLE encoding 1, 1 bit per plane, xmin/ymin/xmax/ymax,
  dpi 1600x1200, 16-colour EGA palette (RGB888) at 0x10, nplanes at 0x41 (4 = 16 colours), bytes per plane line
  at 0x42 (even), palette info 1, screen 640x480;
* MGS fields in the PCX filler at 0x4A (u16 each): magic 0x3039, flags, VRAM x, VRAM y, CLUT x, CLUT y,
  colour count, then 0, 1.  The game uploads the pixels to VRAM (x, y) as 4bpp (16 colours) and the palette to
  the CLUT at (x, y) as 15-bit colours; KMD face UVs (0..255) are scaled into the texture's VRAM rectangle;
* RLE pixel data: per scanline, nplanes planes of bytes-per-line bytes (bit 7 = leftmost pixel), with a byte
  >= 0xC0 meaning "repeat the next byte (b & 0x3F) times".

PS1 colour 0x0000 (black with the semi-transparency bit clear) is drawn as transparent, so encode() keeps every
opaque colour at least one 5-bit step above black and only writes black where the source pixel is transparent.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

MAGIC = 0x3039


@dataclass
class Pcc:
    width: int
    height: int
    palette: np.ndarray          # (n, 3) uint8
    index: np.ndarray            # (h, w) uint8 palette indices
    vram: tuple = (0, 0)
    clut: tuple = (0, 0)
    flags: int = 0
    header: bytes = b""          # the original 0x80-byte header (kept on re-encode)

    def rgba(self) -> np.ndarray:
        out = np.zeros((self.height, self.width, 4), np.uint8)
        out[..., :3] = self.palette[self.index]
        out[..., 3] = 255
        black = (self.palette[self.index] // 8).sum(-1) == 0
        out[black, 3] = 0
        return out


def _unrle(data: bytes, need: int, pos: int = 0x80) -> bytes:
    out = bytearray()
    n = len(data)
    while len(out) < need and pos < n:
        b = data[pos]
        pos += 1
        if b >= 0xC0:
            out += bytes([data[pos]]) * (b & 0x3F)
            pos += 1
        else:
            out.append(b)
    if len(out) < need:
        raise ValueError("PCC pixel data ends early")
    return bytes(out[:need])


def loads(data: bytes) -> Pcc:
    if len(data) < 0x80 or data[0] != 0x0A or data[2] != 1:
        raise ValueError("not an MGS PCC/PCX texture")
    bpp, (x0, y0, x1, y1) = data[3], struct.unpack_from("<4H", data, 4)
    planes, bpl = data[0x41], struct.unpack_from("<H", data, 0x42)[0]
    if bpp != 1 or planes not in (1, 2, 3, 4):
        raise ValueError(f"unsupported PCX layout: {bpp} bpp x {planes} planes")
    w, h = x1 - x0 + 1, y1 - y0 + 1
    magic, flags, vx, vy, cx, cy, ncol = struct.unpack_from("<7H", data, 0x4A)
    raw = np.frombuffer(_unrle(data, h * planes * bpl), np.uint8).reshape(h, planes, bpl)
    bits = np.unpackbits(raw, axis=2)[:, :, :w]                        # (h, planes, w), MSB first
    index = np.zeros((h, w), np.uint8)
    for p in range(planes):
        index |= (bits[:, p, :] << p).astype(np.uint8)
    pal = np.frombuffer(data[0x10:0x40], np.uint8).reshape(16, 3)[:1 << planes].copy()
    return Pcc(w, h, pal, index, (vx, vy) if magic == MAGIC else (0, 0), (cx, cy) if magic == MAGIC else (0, 0),
               flags, bytes(data[:0x80]))


def _rle(row: bytes) -> bytes:
    out = bytearray()
    i, n = 0, len(row)
    while i < n:
        b, run = row[i], 1
        while i + run < n and row[i + run] == b and run < 63:
            run += 1
        if run > 1 or b >= 0xC0:
            out += bytes([0xC0 | run, b])
        else:
            out.append(b)
        i += run
    return bytes(out)


def dumps(p: Pcc) -> bytes:
    """Re-encode *p* with its original header (size, VRAM and CLUT placement), new palette and pixels."""
    if not p.header:
        raise ValueError("encode needs the header of the texture it replaces")
    hdr = bytearray(p.header)
    planes, bpl = hdr[0x41], struct.unpack_from("<H", hdr, 0x42)[0]
    pal = np.zeros((16, 3), np.uint8)
    pal[:len(p.palette)] = p.palette[:16]
    hdr[0x10:0x40] = pal.tobytes()
    body = bytearray()
    for y in range(p.height):
        line = b""
        for pl in range(planes):
            bits = ((p.index[y] >> pl) & 1).astype(np.uint8)
            packed = np.packbits(np.pad(bits, (0, bpl * 8 - p.width)))
            line += packed.tobytes()
        body += _rle(line)                                  # PCX encoders run-length each scanline separately
    return bytes(hdr) + bytes(body)


def quantize(rgba: np.ndarray, colors: int = 16) -> tuple[np.ndarray, np.ndarray]:
    """RGBA image -> (palette (n,3), index map) for the PS1: opaque colours never collapse to 15-bit black;
    transparent pixels (alpha < 128) use a black palette entry, which the PS1 draws as see-through."""
    from PIL import Image
    a = rgba[..., 3] >= 128
    rgb = rgba[..., :3].astype(np.int32)
    rgb = np.where(rgb < 8, 8, rgb).astype(np.uint8)          # keep opaque texels off PS1 colour 0x0000
    need_clear = not a.all()
    n = colors - 1 if need_clear else colors
    img = Image.fromarray(rgb, "RGB").quantize(colors=n, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    pal = np.array(img.getpalette()[:3 * n], np.uint8).reshape(-1, 3)
    pal = np.maximum(pal, 8)
    idx = np.array(img, np.uint8)
    if need_clear:
        pal = np.vstack([pal, np.zeros((1, 3), np.uint8)])
        idx = np.where(a, idx, len(pal) - 1).astype(np.uint8)
    return pal, idx


def fit(rgba: np.ndarray, like: Pcc, budget: int | None = None) -> bytes:
    """Resample *rgba* to the size of the texture *like*, quantize to its colour count and encode it with *like*'s
    header.  With *budget*, colours are reduced until the encoded texture is no larger (the archive keeps its size)."""
    from PIL import Image
    img = Image.fromarray(rgba, "RGBA").resize((like.width, like.height), Image.Resampling.LANCZOS)
    arr = np.array(img)
    colors = min(16, len(like.palette))
    while True:
        pal, idx = quantize(arr, colors)
        data = dumps(Pcc(like.width, like.height, pal, idx, like.vram, like.clut, like.flags, like.header))
        if budget is None or len(data) <= budget or colors <= 2:
            return data
        colors -= 2
