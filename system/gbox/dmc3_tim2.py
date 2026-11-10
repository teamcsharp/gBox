"""PS2 TIM2 decoder for DMC3 SE character texture banks (#1330, reader stage).

Layout follows the public TIM2 spec (file header 0x10: ``TIM2``, version u8,
format u8, pictures u16; picture header 0x30: total/clut/image sizes u32,
header size u16, clut colours u16, pic format, mipmaps, clut type, image type
u8, width/height u16).  CLUT type low 6 bits: 1=RGBA5551, 2=RGB24, 3=RGBA8888;
bit 7 set = linear (CSM2), clear = CSM1 swizzled (8-bit palettes swap index
bits 3 and 4).  Image type: 1=16bpp, 2=24bpp, 3=32bpp, 4=4bpp, 5=8bpp.  PS2
alpha is 0..0x80, so 0x80 is expanded to 0xFF.  Every size is bounded by the
source extent.
"""
from __future__ import annotations

import struct
import zlib

BPP = {1: 16, 2: 24, 3: 32, 4: 4, 5: 8}


def csm1_index(i: int) -> int:
    """CSM1 8-bit palette swizzle: swap bits 3 and 4 of the colour index."""
    return i ^ 0x18 if (i & 0x18) in (0x08, 0x10) else i


def _color(raw: bytes, kind: int) -> tuple[int, int, int, int]:
    if kind == 1:
        v = raw[0] | raw[1] << 8
        e = lambda x: (x << 3) | (x >> 2)
        return e(v & 31), e(v >> 5 & 31), e(v >> 10 & 31), 255 if v & 0x8000 else 0
    if kind == 2:
        return raw[0], raw[1], raw[2], 255
    return raw[0], raw[1], raw[2], min(255, raw[3] * 2) if raw[3] < 0x80 else 255


def parse_tim2(b: bytes) -> list[dict]:
    """Decode every picture to ``{width, height, rgba: bytes, ...}``."""
    if len(b) < 0x40 or b[:4] != b"TIM2":
        raise ValueError("not a TIM2 file")
    npic = struct.unpack_from("<H", b, 6)[0]
    base = 0x80 if b[5] == 1 else 0x10  # format 1 = 128-byte aligned header
    pics, pos = [], base
    for _ in range(npic):
        if pos + 0x30 > len(b):
            raise ValueError("truncated picture header")
        total, clut_sz, img_sz, hsz, ncol, fmt, mip, clut_t, img_t, w, h = \
            struct.unpack_from("<IIIHHBBBBHH", b, pos)
        if img_t not in BPP or not w or not h or total > len(b) - pos or hsz < 0x30:
            raise ValueError(f"bad picture header at {pos:#x}")
        if hsz + img_sz + clut_sz > total:
            raise ValueError("picture sections exceed total size")
        bits = BPP[img_t]
        if img_sz < w * h * bits // 8:
            raise ValueError("image data shorter than width*height")
        img = b[pos + hsz:pos + hsz + img_sz]
        pal = None
        if img_t in (4, 5):
            kind = clut_t & 0x3F
            if kind not in (1, 2, 3):
                raise ValueError(f"unsupported CLUT type {clut_t:#x}")
            n = 1 << bits
            sz = {1: 2, 2: 3, 3: 4}[kind]
            if ncol < n and ncol != n or clut_sz < n * sz:
                raise ValueError("CLUT smaller than the index range")
            raw = b[pos + hsz + img_sz:pos + hsz + img_sz + clut_sz]
            pal = [_color(raw[i * sz:i * sz + sz], kind) for i in range(n)]
            if img_t == 5 and not clut_t & 0x80:
                pal = [pal[csm1_index(i)] for i in range(n)]
        out = bytearray()
        for i in range(w * h):
            if img_t == 5:
                out += bytes(pal[img[i]])
            elif img_t == 4:
                out += bytes(pal[(img[i >> 1] >> 4) if i & 1 else (img[i >> 1] & 15)])
            else:
                out += bytes(_color(img[i * bits // 8:(i + 1) * bits // 8], {1: 1, 2: 2, 3: 3}[img_t]))
        pics.append({"width": w, "height": h, "image_type": img_t, "clut_type": clut_t,
                     "colors": ncol, "rgba": bytes(out)})
        pos += total
    return pics


def to_png(width: int, height: int, rgba: bytes) -> bytes:
    """Minimal RGBA PNG encoder for texture previews."""
    if len(rgba) != width * height * 4:
        raise ValueError("rgba size mismatch")
    raw = b"".join(b"\0" + rgba[y * width * 4:(y + 1) * width * 4] for y in range(height))

    def chunk(t: bytes, d: bytes) -> bytes:
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
