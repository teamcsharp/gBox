"""Write GameCube GVR textures (the reader is `pso_gc.gvr_decode`; this is the missing writer for A8's swap)."""
from __future__ import annotations

import struct

import numpy as np

GVR_RGBA8 = 6
GVR_CMPR = 14
_BLOCK = {6: (4, 4, 64), 14: (8, 8, 32)}


def gvr_chunk(rgba: np.ndarray, *, gbix: int | None = None, fmt: int = GVR_RGBA8, pal_fmt: int = 0,
              flags: int = 0, palette: bytes = b"") -> bytes:
    """A `GBIX` (optional) + `GVRT` chunk for an RGBA uint8 image.

    The texel encoding is per `fmt`: RGBA8 (`fmt=6`, lossless) and CMPR (`fmt=14`, the block format most class
    textures use; lossy but bounded). The header layout is the one `pso_gc.gvr_header` reads:
    `"GVRT"` + little-endian chunk size + `4 bytes` + `pal_fmt<<4 | flags` + `fmt` + big-endian width, height + texels.
    """
    rgba = np.asarray(rgba, dtype=np.uint8)
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError("RGBA (h, w, 4) expected")
    h, w = rgba.shape[:2]
    if fmt == GVR_RGBA8:
        texels = _rgba8(rgba)
    elif fmt == GVR_CMPR:
        texels = _cmpr(rgba)
    else:
        raise ValueError(f"GVR format {fmt} is not implemented (RGBA8 and CMPR only)")
    # header: "GVRT", LE size, 2 filler, pal/flag, fmt, W, H (big-endian), then texels at +16
    head = b"GVRT" + struct.pack("<I", 16 + len(texels)) + bytes(2) + bytes([(pal_fmt << 4) | flags, fmt]) + \
        struct.pack(">HH", w, h)
    if palette:
        texels = palette + texels
    body = head + texels
    if gbix is not None:
        return b"GBIX" + struct.pack("<I", 4) + struct.pack(">I", gbix & 0xFFFFFFFF) + body
    return body


def _rgb565(colors) -> int:
    r, g, b = (int(v) for v in colors[:3])
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def _expand565(value: int):
    r, g, b = (value >> 11) & 31, (value >> 5) & 63, value & 31
    return (r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)


def _cmpr(rgba: np.ndarray) -> bytes:
    """GX CMPR: 8x8 tiles of four 2x2 4x4 DXT1-style sub-blocks (the inverse of the decoder's fmt-14 branch)."""
    h, w = rgba.shape[:2]
    out = bytearray()
    for by in range(0, h, 8):
        for bx in range(0, w, 8):
            for sy in range(2):
                for sx in range(2):
                    px = []
                    for y in range(4):
                        row = min(by + sy * 4 + y, h - 1)
                        for x in range(4):
                            col = min(bx + sx * 4 + x, w - 1)
                            px.append(tuple(int(v) for v in rgba[row, col][:3]))
                    lum = [0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2] for p in px]
                    hi = max(range(16), key=lambda i: lum[i])
                    lo = min(range(16), key=lambda i: lum[i])
                    c0, c1 = _rgb565(px[hi]), _rgb565(px[lo])
                    a, b = _expand565(c0), _expand565(c1)
                    pal = [a, b,
                           tuple((2 * a[i] + b[i]) // 3 for i in range(3)),
                           tuple((a[i] + 2 * b[i]) // 3 for i in range(3))]
                    word = 0
                    for k, colour in enumerate(px):
                        best = min(range(4), key=lambda i: sum((colour[j] - pal[i][j]) ** 2 for j in range(3)))
                        word |= best << (30 - 2 * k)
                    out += struct.pack(">HHI", c0, c1, word)
    return bytes(out)


def _rgba8(rgba: np.ndarray) -> bytes:
    """GX RGBA8: 4x4 blocks, each texel two u16 (A<<8|R, G<<8|B) in block row-major - the inverse of the decoder."""
    h, w = rgba.shape[:2]
    out = bytearray()
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            block0, block1 = bytearray(), bytearray()
            for y in range(4):
                row = min(by + y, h - 1)
                for x in range(4):
                    col = min(bx + x, w - 1)
                    r, g, b, a = (int(v) for v in rgba[row, col])
                    block0 += struct.pack(">H", (a << 8) | r)
                    block1 += struct.pack(">H", (g << 8) | b)
            out += block0 + block1
    return bytes(out)
