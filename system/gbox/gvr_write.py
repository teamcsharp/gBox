"""Write GameCube GVR textures (the reader is `pso_gc.gvr_decode`; this is the missing writer for A8's swap)."""
from __future__ import annotations

import struct

import numpy as np

GVR_RGBA8 = 6
_BLOCK = {6: (4, 4, 64)}


def gvr_chunk(rgba: np.ndarray, *, gbix: int | None = None, fmt: int = GVR_RGBA8, pal_fmt: int = 0,
              flags: int = 0, palette: bytes = b"") -> bytes:
    """A `GBIX` (optional) + `GVRT` chunk for an RGBA uint8 image.

    The texel encoding is per `fmt`: only RGBA8 (`fmt=6`) is implemented here, because it is lossless and every
    player-texture path can then be rebuilt exactly. The header layout is the one `pso_gc.gvr_header` reads:
    `"GVRT"` + little-endian chunk size + `4 bytes` + `pal_fmt<<4 | flags` + `fmt` + big-endian width, height + texels.
    """
    rgba = np.asarray(rgba, dtype=np.uint8)
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError("RGBA (h, w, 4) expected")
    h, w = rgba.shape[:2]
    if fmt != GVR_RGBA8:
        raise ValueError(f"GVR format {fmt} is not implemented (only RGBA8)")
    texels = _rgba8(rgba)
    # header: "GVRT", LE size, 2 filler, pal/flag, fmt, W, H (big-endian), then texels at +16
    head = b"GVRT" + struct.pack("<I", 16 + len(texels)) + bytes(2) + bytes([(pal_fmt << 4) | flags, fmt]) + \
        struct.pack(">HH", w, h)
    if palette:
        texels = palette + texels
    body = head + texels
    if gbix is not None:
        return b"GBIX" + struct.pack("<I", 4) + struct.pack(">I", gbix & 0xFFFFFFFF) + body
    return body


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
