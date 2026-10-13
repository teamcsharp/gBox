"""Console texture helpers shared by the title readers/writers.

  morton / twiddled_index / twiddle_rect   Dreamcast PowerVR twiddled addressing (Ninja PVR, NaomiLib, MvC2, MK Gold)
  argb1555 / rgb565 / argb4444 / rgb5a3 / ia8 / psx15   16-bit pixel words -> RGBA tuples (and numpy arrays)
  tim_parse / tim_build / tim_indices / tim_rgba          PS1 TIM (SmackDown 2, FF7, DOA++, MGS, RE2, Parasite Eve)
  gc_tiles                                 GameCube/Wii block-linear tile order (TPL / GVR / .gpl textures)
  facades: pvr_decode (gbox.ninja), tpl_read / tpl_decode_image (gbox.re4gc_models), txd_rasters (gbox.gta_vc_models)

tim_parse / tim_build are gbox.yukes_sd's original code (moved here; yukes_sd re-imports them).
"""
from __future__ import annotations

import struct

import numpy as np


# ---------------------------------------------------------------- PowerVR twiddling


def morton(x: int, y: int, bits: int = 12) -> int:
    """Twiddled offset of texel (x, y) in a square texture: y in the even bits, x in the odd bits."""
    r = 0
    for i in range(bits):
        r |= ((y >> i) & 1) << (2 * i) | ((x >> i) & 1) << (2 * i + 1)
    return r


def twiddled_index(x: int, y: int, w: int, h: int) -> int:
    """PVR twiddled address of a rectangular texture: square Morton blocks laid out along the longer side."""
    s = min(w, h)
    if w >= h:
        return (x // s) * s * s + morton(x % s, y)
    return (y // s) * s * s + morton(x, y % s)


def twiddle_rect(x: int, y: int, w: int, h: int) -> int:
    """General twiddle for power-of-two w x h (bits interleave while both sides still have them; y first)."""
    rv = sh = 0
    w >>= 1
    h >>= 1
    while w or h:
        if h:
            rv |= (y & 1) << sh
            h >>= 1
            y >>= 1
            sh += 1
        if w:
            rv |= (x & 1) << sh
            w >>= 1
            x >>= 1
            sh += 1
    return rv


def detwiddle(data, w: int, h: int, bpp: int = 16) -> bytes:
    """Twiddled texels (8 or 16 bpp) -> linear row-major order."""
    n = bpp // 8
    out = bytearray(w * h * n)
    for y in range(h):
        for x in range(w):
            s = twiddled_index(x, y, w, h) * n
            d = (y * w + x) * n
            out[d:d + n] = data[s:s + n]
    return bytes(out)


def twiddle(data, w: int, h: int, bpp: int = 16) -> bytes:
    """Linear texels -> twiddled order (the inverse of detwiddle)."""
    n = bpp // 8
    out = bytearray(w * h * n)
    for y in range(h):
        for x in range(w):
            d = twiddled_index(x, y, w, h) * n
            s = (y * w + x) * n
            out[d:d + n] = data[s:s + n]
    return bytes(out)


# ---------------------------------------------------------------- 16-bit pixel words


def argb1555(v: int) -> tuple:
    return ((v >> 10) & 31) * 255 // 31, ((v >> 5) & 31) * 255 // 31, (v & 31) * 255 // 31, 255 if v & 0x8000 else 0


def rgb565(v: int) -> tuple:
    return ((v >> 11) & 31) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31, 255


def argb4444(v: int) -> tuple:
    return ((v >> 8) & 15) * 17, ((v >> 4) & 15) * 17, (v & 15) * 17, ((v >> 12) & 15) * 17


def rgb5a3(v: int) -> tuple:
    """GameCube RGB5A3: top bit set = opaque RGB555, clear = ARGB3444."""
    if v & 0x8000:
        return ((v >> 10) & 31) * 255 // 31, ((v >> 5) & 31) * 255 // 31, (v & 31) * 255 // 31, 255
    return ((v >> 8) & 15) * 17, ((v >> 4) & 15) * 17, (v & 15) * 17, ((v >> 12) & 7) * 255 // 7


def ia8(v: int) -> tuple:
    """GameCube IA8 (alpha high byte, intensity low byte)."""
    i = v & 0xFF
    return i, i, i, v >> 8


def psx15(v: int, black_transparent: bool = True) -> tuple:
    """PS1 15-bit BGR + STP: 0x0000 is transparent unless black_transparent=False."""
    a = 0 if (v == 0 and black_transparent) else 255
    return (v & 31) * 255 // 31, ((v >> 5) & 31) * 255 // 31, ((v >> 10) & 31) * 255 // 31, a


PIXEL16 = {"argb1555": argb1555, "rgb565": rgb565, "argb4444": argb4444, "rgb5a3": rgb5a3, "ia8": ia8, "psx15": psx15}


def pixels16(words, fmt: str) -> np.ndarray:
    """Array of 16-bit words -> (..., 4) uint8 RGBA (vectorised form of the PIXEL16 functions)."""
    v = np.asarray(words, np.int64)
    c5 = lambda s: ((v >> s) & 31) * 255 // 31          # noqa: E731
    c4 = lambda s: ((v >> s) & 15) * 17                 # noqa: E731
    if fmt == "argb1555":
        rgba = [c5(10), c5(5), c5(0), np.where(v & 0x8000, 255, 0)]
    elif fmt == "rgb565":
        rgba = [c5(11), ((v >> 5) & 63) * 255 // 63, c5(0), np.full_like(v, 255)]
    elif fmt == "argb4444":
        rgba = [c4(8), c4(4), c4(0), c4(12)]
    elif fmt == "rgb5a3":
        op = (v & 0x8000) != 0
        rgba = [np.where(op, c5(10), c4(8)), np.where(op, c5(5), c4(4)), np.where(op, c5(0), c4(0)),
                np.where(op, 255, ((v >> 12) & 7) * 255 // 7)]
    elif fmt == "ia8":
        rgba = [v & 0xFF, v & 0xFF, v & 0xFF, v >> 8]
    elif fmt == "psx15":
        rgba = [c5(0), c5(5), c5(10), np.where(v == 0, 0, 255)]
    else:
        raise ValueError(f"unknown 16-bit pixel format {fmt!r}")
    return np.stack(rgba, -1).astype(np.uint8)


# ---------------------------------------------------------------- GameCube tiles

GC_BLOCK = {"I4": (8, 8), "IA4": (8, 4), "I8": (8, 4), "IA8": (4, 4), "RGB565": (4, 4), "RGB5A3": (4, 4),
            "RGBA8": (4, 4), "C4": (8, 8), "C8": (8, 4), "C14X2": (4, 4), "CMPR": (8, 8)}


def gc_tiles(w: int, h: int, fmt: str):
    """Yield (x, y) of every texel in GameCube storage order (blocks left to right, top to bottom; row-major inside a
    block). Texels outside w x h (padding up to the block size) are yielded too; callers skip them."""
    bw, bh = GC_BLOCK[fmt]
    for by in range(0, h, bh):
        for bx in range(0, w, bw):
            for y in range(by, by + bh):
                for x in range(bx, bx + bw):
                    yield x, y


# ---------------------------------------------------------------- PS1 TIM


def tim_indices(tim: dict) -> np.ndarray:
    """tim_parse's dict -> (h, w) texel values: CLUT indices for 4/8 bpp, raw 16-bit words for 16 bpp."""
    pix = np.asarray(tim["pix"], np.uint8)
    bpp = tim.get("bpp", 1)
    if bpp == 0:
        idx = np.zeros((pix.shape[0], pix.shape[1] * 2), np.uint8)
        idx[:, 0::2], idx[:, 1::2] = pix & 15, pix >> 4
        return idx
    if bpp == 1:
        return pix
    if bpp == 2:
        return pix.view("<u2")
    raise NotImplementedError("24-bit TIM")


def tim_rgba(tim: dict, clut_row: int = 0) -> np.ndarray:
    """tim_parse's dict -> (h, w, 4) RGBA through CLUT row `clut_row` (16-bpp TIMs need no CLUT)."""
    idx = tim_indices(tim)
    if tim.get("bpp", 1) == 2:
        return pixels16(idx, "psx15")
    cw = tim["clut_xy"][2]
    clut = np.asarray(tim["clut"]).reshape(-1, cw)[clut_row]
    return pixels16(clut, "psx15")[idx]


# ---------------------------------------------------------------- facades over title-owned decoders


def pvr_decode(data: bytes):
    """Dreamcast PVR (GBIX/PVRT) -> (w, h, rgba bytes, format name): gbox.ninja.pvr_decode."""
    from .. import ninja
    return ninja.pvr_decode(data)


def tpl_read(b: bytes):
    """GameCube TPL -> [TplImage]: gbox.re4gc_models.tpl_read."""
    from .. import re4gc_models
    return re4gc_models.tpl_read(b)


def tpl_decode_image(fmt: int, w: int, h: int, d: bytes) -> np.ndarray:
    from .. import re4gc_models
    return re4gc_models.tpl_decode_image(fmt, w, h, d)


def txd_rasters(txd: bytes):
    """RenderWare (PC/D3D) TXD -> rasters: gbox.gta_vc_models.txd_rasters."""
    from .. import gta_vc_models
    return gta_vc_models.txd_rasters(txd)


def tim_parse(t: bytes) -> dict:
    _magic, flags = struct.unpack_from("<II", t, 0)
    o, out = 8, {"bpp": flags & 3}
    if flags & 8:
        ln, cx, cy, cw, ch = struct.unpack_from("<IHHHH", t, o)
        out["clut_xy"] = (cx, cy, cw, ch)
        out["clut"] = np.frombuffer(t, "<u2", cw * ch, o + 12).copy()
        o += ln
    ln, px, py, pw, ph = struct.unpack_from("<IHHHH", t, o)
    out["rect"] = (px, py, pw, ph)
    out["pix"] = np.frombuffer(t, np.uint8, pw * 2 * ph, o + 12).reshape(ph, pw * 2).copy()
    return out


def tim_build(tim: dict) -> bytes:
    """tim_parse's dict -> TIM bytes. CLUT-less TIMs (16-bpp pages, e.g. CAW group 0x111) have no "clut_xy"."""
    px, py, pw, ph = tim["rect"]
    pix = np.asarray(tim["pix"], np.uint8).tobytes()
    flags, clut_block = tim.get("bpp", 1), b""
    if tim.get("clut_xy") is not None:
        cx, cy, cw, ch = tim["clut_xy"]
        clut = np.asarray(tim["clut"], "<u2").tobytes()
        if len(clut) != 2 * cw * ch:
            raise ValueError("TIM CLUT size doesn't match the header")
        flags, clut_block = flags | 8, struct.pack("<IHHHH", 12 + len(clut), cx, cy, cw, ch) + clut
    if len(pix) != 2 * pw * ph:
        raise ValueError("TIM pixel size doesn't match the header")
    return struct.pack("<II", 0x10, flags) + clut_block + struct.pack("<IHHHH", 12 + len(pix), px, py, pw, ph) + pix
