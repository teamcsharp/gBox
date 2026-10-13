"""Metal Gear Solid: The Twin Snakes (GC) - `.tri` texture sets (stage file type 0x13): read and rewrite in place.

A texture set (big-endian):
  +0x10 u32 entry count, +0x14 flags, +0x18 u32 offset of an embedded standard GameCube TPL (magic 0x0020AF30)
  entries of 0x80 bytes from +0x20: +0x10 u32 texture strcode (what a model part names), +0x1c u32 TPL image index,
  the rest is the engine's per-texture GX register state (filled in at load; the TPL image header carries the size).
TPL images are C4 / C8 (with an IA8 / RGB565 / RGB5A3 palette), CMPR, RGBA8 ... at their own (often non power of two)
sizes, padded to whole tiles. `replace_image` rewrites one image's texels in its own place and format, so the set
keeps its size, layout and every offset.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

TPL_MAGIC = 0x0020AF30
TILE = {0: (8, 8, 4), 1: (8, 4, 8), 2: (8, 4, 8), 3: (4, 4, 16), 4: (4, 4, 16), 5: (4, 4, 16), 6: (4, 4, 32),
        8: (8, 8, 4), 9: (8, 4, 8), 10: (4, 4, 16), 14: (8, 8, 4)}
FORMAT_NAMES = {0: "I4", 1: "I8", 2: "IA4", 3: "IA8", 4: "RGB565", 5: "RGB5A3", 6: "RGBA8", 8: "C4", 9: "C8",
                10: "C14X2", 14: "CMPR"}


def _al(v: int, a: int) -> int:
    return (v + a - 1) // a * a


def image_size(fmt: int, w: int, h: int) -> int:
    bw, bh, bpp = TILE[fmt]
    return _al(w, bw) * _al(h, bh) * bpp // 8


@dataclass
class Image:
    index: int
    w: int
    h: int
    fmt: int
    data_off: int                 # inside the TPL
    pal_fmt: int | None
    pal_off: int | None
    pal_count: int


@dataclass
class Texture:
    entry: int
    hash: int
    image: int


class TextureSet:
    def __init__(self, data: bytes):
        self.data = bytearray(data)
        n = struct.unpack_from(">I", data, 0x10)[0]
        self.tpl = struct.unpack_from(">I", data, 0x18)[0]
        self.textures = [Texture(i, struct.unpack_from(">I", data, 0x20 + 0x80 * i + 0x10)[0] & 0xFFFFFF,
                                 struct.unpack_from(">I", data, 0x20 + 0x80 * i + 0x1C)[0]) for i in range(n)]
        t = self.tpl
        if struct.unpack_from(">I", data, t)[0] != TPL_MAGIC:
            raise ValueError("texture set without its TPL")
        cnt, to = struct.unpack_from(">II", data, t + 4)
        self.images = []
        for i in range(cnt):
            io, po = struct.unpack_from(">II", data, t + to + 8 * i)
            h, w, fmt, do = struct.unpack_from(">HHII", data, t + io)
            pf = poff = None
            pc = 0
            if po:
                pc, _u, _p, pf, poff = struct.unpack_from(">HBBII", data, t + po)
            self.images.append(Image(i, w, h, fmt, do, pf, poff, pc))

    def by_hash(self, h: int) -> Image | None:
        t = next((x for x in self.textures if x.hash == h), None)
        return self.images[t.image] if t and t.image < len(self.images) else None

    def rgba(self, img: Image) -> np.ndarray:
        raw = bytes(self.data[self.tpl + img.data_off: self.tpl + img.data_off + image_size(img.fmt, img.w, img.h)])
        pal = None
        if img.fmt in (8, 9, 10):
            pal = palette(bytes(self.data[self.tpl + img.pal_off: self.tpl + img.pal_off + 2 * img.pal_count]),
                          img.pal_fmt)
        return decode(img.fmt, img.w, img.h, raw, pal)

    def replace_image(self, img: Image, rgba: np.ndarray) -> None:
        """New texels for one image, same size and format (C4 / C8 get a fresh palette in place)."""
        from PIL import Image as PI
        rgba = np.asarray(PI.fromarray(np.asarray(rgba, np.uint8)).convert("RGBA").resize((img.w, img.h), PI.LANCZOS))
        if img.fmt in (8, 9):
            idx, pal = quantize(rgba, min(img.pal_count, 16 if img.fmt == 8 else 256), img.pal_fmt)
            raw = encode(img.fmt, img.w, img.h, idx)
            pal = pal + bytes(2 * img.pal_count - len(pal))
            o = self.tpl + img.pal_off
            self.data[o:o + len(pal)] = pal
        else:
            raw = encode(img.fmt, img.w, img.h, rgba)
        o = self.tpl + img.data_off
        assert len(raw) == image_size(img.fmt, img.w, img.h)
        self.data[o:o + len(raw)] = raw


# ---------------------------------------------------------------- pixels

def _565(c):
    c = np.asarray(c, np.int32)
    return np.stack([((c >> 11) & 31) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31,
                     np.full_like(c, 255)], -1).astype(np.uint8)


def _5a3(c):
    c = np.asarray(c, np.int32)
    opaque = (c & 0x8000) != 0
    r = np.where(opaque, ((c >> 10) & 31) * 255 // 31, ((c >> 8) & 15) * 17)
    g = np.where(opaque, ((c >> 5) & 31) * 255 // 31, ((c >> 4) & 15) * 17)
    b = np.where(opaque, (c & 31) * 255 // 31, (c & 15) * 17)
    a = np.where(opaque, 255, ((c >> 12) & 7) * 255 // 7)
    return np.stack([r, g, b, a], -1).astype(np.uint8)


def _ia8(c):
    c = np.asarray(c, np.int32)
    i, a = c & 0xFF, c >> 8
    return np.stack([i, i, i, a], -1).astype(np.uint8)


def palette(raw: bytes, fmt: int) -> np.ndarray:
    words = np.frombuffer(raw, ">u2")
    return {0: _ia8, 1: _565, 2: _5a3}[fmt](words)


def _untile(vals: np.ndarray, w: int, h: int, bw: int, bh: int) -> np.ndarray:
    """Tile-ordered values (one per texel, tiles of bw x bh row-major) -> (H, W, ...) image."""
    W, H = _al(w, bw), _al(h, bh)
    tail = vals.shape[1:]
    v = vals.reshape(H // bh, W // bw, bh, bw, *tail).swapaxes(1, 2).reshape(H, W, *tail)
    return v[:h, :w]


def _tile(img: np.ndarray, bw: int, bh: int) -> np.ndarray:
    h, w = img.shape[:2]
    W, H = _al(w, bw), _al(h, bh)
    pad = np.zeros((H, W) + img.shape[2:], img.dtype)
    pad[:h, :w] = img
    if h < H:
        pad[h:, :w] = img[-1:]
    if w < W:
        pad[:, w:] = pad[:, w - 1:w]
    return pad.reshape(H // bh, bh, W // bw, bw, *img.shape[2:]).swapaxes(1, 2).reshape(-1, *img.shape[2:])


def decode(fmt: int, w: int, h: int, raw: bytes, pal: np.ndarray | None = None) -> np.ndarray:
    """-> RGBA uint8 (h, w, 4)."""
    bw, bh, bpp = TILE[fmt]
    b = np.frombuffer(raw, np.uint8)
    if fmt == 14:
        W, H = _al(w, 8), _al(h, 8)
        blk = b.reshape(-1, 8)
        c0 = blk[:, 0].astype(np.int32) << 8 | blk[:, 1]
        c1 = blk[:, 2].astype(np.int32) << 8 | blk[:, 3]
        A, B = _565(c0).astype(np.int32), _565(c1).astype(np.int32)
        more = (c0 > c1)[:, None]
        p2 = np.where(more, (2 * A + B) // 3, (A + B) // 2)
        p3 = np.where(more, (A + 2 * B) // 3, 0)
        p3[:, 3] = np.where(more[:, 0], 255, 0)
        pals = np.stack([A, B, p2, p3], 1).astype(np.uint8)           # (n, 4, 4)
        bits = blk[:, 4:8]
        idx = np.stack([(bits[:, i // 4] >> (6 - 2 * (i % 4))) & 3 for i in range(16)], 1)   # (n, 16)
        px = pals[np.arange(len(blk))[:, None], idx]                  # (n, 16, 4)
        # n sub-blocks: per 8x8 tile, 2x2 sub-blocks of 4x4
        t = px.reshape(H // 8, W // 8, 2, 2, 4, 4, 4)                # ty tx sy sx py px c
        img = t.transpose(0, 2, 4, 1, 3, 5, 6).reshape(H, W, 4)
        return img[:h, :w].copy()
    if fmt in (0, 8):
        v = np.stack([b >> 4, b & 15], 1).reshape(-1)
    elif fmt in (1, 9):
        v = b
    elif fmt == 6:
        blk = b.reshape(-1, 2, 16, 2)                                 # AR block, GB block
        v = np.stack([blk[:, 0, :, 1], blk[:, 1, :, 0], blk[:, 1, :, 1], blk[:, 0, :, 0]], -1).reshape(-1, 4)
        return _untile(v, w, h, 4, 4).copy()
    else:
        v = b.view(">u2")
    if fmt in (8, 9, 10):
        v = (v & 0x3FFF) if fmt == 10 else v
        return _untile(pal[np.minimum(v, len(pal) - 1)], w, h, bw, bh).copy()
    if fmt == 0:
        px = np.stack([v * 17] * 4, -1)
    elif fmt == 1:
        px = np.stack([v] * 4, -1)
    elif fmt == 2:
        px = np.stack([(v & 15) * 17] * 3 + [(v >> 4) * 17], -1)
    elif fmt == 3:
        px = _ia8(v)
    elif fmt == 4:
        px = _565(v)
    else:
        px = _5a3(v)
    return _untile(px.astype(np.uint8), w, h, bw, bh).copy()


def quantize(rgba: np.ndarray, n: int, pal_fmt: int) -> tuple[np.ndarray, bytes]:
    """RGBA -> (index image, palette words) with PIL's median cut."""
    from PIL import Image as PI
    im = PI.fromarray(rgba, "RGBA")
    q = im.quantize(colors=n, method=PI.Quantize.FASTOCTREE)
    idx = np.asarray(q, np.uint8)
    p = np.asarray(q.getpalette(rawmode="RGBA")[:4 * n] if hasattr(q, "getpalette") else [], np.int32)
    p = np.resize(p, 4 * n).reshape(n, 4)
    if pal_fmt == 1:
        w = (p[:, 0] * 31 // 255) << 11 | (p[:, 1] * 63 // 255) << 5 | (p[:, 2] * 31 // 255)
    elif pal_fmt == 0:
        i = (p[:, :3].mean(1)).astype(np.int32)
        w = p[:, 3] << 8 | i
    else:
        op = p[:, 3] >= 224
        w = np.where(op, 0x8000 | (p[:, 0] * 31 // 255) << 10 | (p[:, 1] * 31 // 255) << 5 | (p[:, 2] * 31 // 255),
                     (p[:, 3] * 7 // 255) << 12 | (p[:, 0] * 15 // 255) << 8 | (p[:, 1] * 15 // 255) << 4 |
                     (p[:, 2] * 15 // 255))
    return idx, w.astype(">u2").tobytes()


def encode(fmt: int, w: int, h: int, img: np.ndarray) -> bytes:
    """(h, w) indices (C4 / C8) or (h, w, 4) RGBA -> texels in fmt's tile order."""
    bw, bh, _bpp = TILE[fmt]
    if fmt == 14:
        from .re4gc_models import cmpr_encode
        return cmpr_encode(img)
    if fmt in (8, 0):
        v = _tile(img if fmt == 8 else img[..., :3].mean(-1).astype(np.uint8) >> 4, bw, bh).astype(np.uint8)
        v = (v & 15) if fmt == 8 else v
        return (v[0::2] << 4 | v[1::2]).astype(np.uint8).tobytes()
    if fmt in (9, 1):
        v = _tile(img if fmt == 9 else img[..., :3].mean(-1).astype(np.uint8), bw, bh)
        return v.astype(np.uint8).tobytes()
    if fmt == 6:
        t = _tile(img, 4, 4).reshape(-1, 16, 4)
        ar = np.stack([t[..., 3], t[..., 0]], -1).reshape(-1, 32)
        gb = np.stack([t[..., 1], t[..., 2]], -1).reshape(-1, 32)
        return np.concatenate([ar, gb], 1).astype(np.uint8).tobytes()
    p = _tile(img, bw, bh).astype(np.int32)
    if fmt == 4:
        v = (p[:, 0] * 31 // 255) << 11 | (p[:, 1] * 63 // 255) << 5 | (p[:, 2] * 31 // 255)
    elif fmt == 5:
        op = p[:, 3] >= 224
        v = np.where(op, 0x8000 | (p[:, 0] * 31 // 255) << 10 | (p[:, 1] * 31 // 255) << 5 | (p[:, 2] * 31 // 255),
                     (p[:, 3] * 7 // 255) << 12 | (p[:, 0] * 15 // 255) << 8 | (p[:, 1] * 15 // 255) << 4 |
                     (p[:, 2] * 15 // 255))
    elif fmt == 3:
        v = p[:, 3] << 8 | p[:, :3].mean(1).astype(np.int32)
    else:
        raise ValueError(f"no encoder for {FORMAT_NAMES.get(fmt, fmt)}")
    return v.astype(">u2").tobytes()
