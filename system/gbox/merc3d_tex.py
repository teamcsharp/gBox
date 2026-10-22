"""MT Framework Mobile (3DS) TEX reader: header, ETC1/ETC1A4 decode, PNG export.

Layout (verified on RE: The Mercenaries 3D EUR, uPl( Chris ).arc skins):
  0x00 'TEX\\0'
  0x04 u32 word0: bits0-11 version (0xA4); byte2 = material kind (hypothesis)
  0x08 u32 word1: bits0-5 mip count, bits6-18 width, bits19-31 height
  0x0C u32 word2: byte0 =1 (unknown), byte1 = pixel format (0x0B ETC1, 0x0C ETC1A4)
  0x10 mip chain, largest first, PICA200 8x8 tiles of 4x4 ETC blocks (Z-order).
"""
from __future__ import annotations
import struct, zlib

FMT_ETC1, FMT_ETC1A4 = 0x0B, 0x0C
_BPP = {FMT_ETC1: 4, FMT_ETC1A4: 8}
_MOD = [(2, 8, -2, -8), (5, 17, -5, -17), (9, 29, -9, -29), (13, 42, -13, -42),
        (18, 60, -18, -60), (24, 80, -24, -80), (33, 106, -33, -106), (47, 183, -47, -183)]
_Z = [(0, 0), (4, 0), (0, 4), (4, 4)]
_ZZ = [(0, 0), (1, 0), (0, 1), (1, 1)]


def parse_header(d: bytes) -> dict:
    if d[:4] != b"TEX\0":
        raise ValueError("not a TEX")
    w0, w1, w2 = struct.unpack_from("<3I", d, 4)
    h = {"version": w0 & 0xFFF, "kind": (w0 >> 16) & 0xFF, "mips": w1 & 0x3F, "width": (w1 >> 6) & 0x1FFF,
         "height": w1 >> 19, "format": (w2 >> 8) & 0xFF, "word2": w2}
    if h["format"] not in _BPP:
        raise ValueError(f"unsupported TEX format 0x{h['format']:02x}")
    return h


def mip_sizes(h: dict) -> list[int]:
    out, w, hh = [], h["width"], h["height"]
    for _ in range(h["mips"]):
        out.append(w * hh * _BPP[h["format"]] // 8)
        w, hh = max(w // 2, 1), max(hh // 2, 1)
    return out


def _clamp(v):
    return 0 if v < 0 else 255 if v > 255 else v


def _ext4(v): return (v << 4) | v
def _ext5(v): return (v << 3) | (v >> 2)


def _etc1_block(b8: bytes):
    """Decode one 3DS-stored ETC1 block (bytes reversed vs. standard) -> 16 RGB tuples, index x*4+y."""
    b = b8[::-1]
    hi, lo = struct.unpack(">II", b)
    diff, flip = (hi >> 1) & 1, hi & 1
    t1, t2 = (hi >> 5) & 7, (hi >> 2) & 7
    if diff:
        r = (hi >> 27) & 31; g = (hi >> 19) & 31; bl = (hi >> 11) & 31
        dr, dg, db = ((hi >> 24) & 7), ((hi >> 16) & 7), ((hi >> 8) & 7)
        dr -= 8 if dr > 3 else 0; dg -= 8 if dg > 3 else 0; db -= 8 if db > 3 else 0
        c1 = (_ext5(r), _ext5(g), _ext5(bl))
        c2 = (_ext5((r + dr) & 31), _ext5((g + dg) & 31), _ext5((bl + db) & 31))
    else:
        c1 = (_ext4((hi >> 28) & 15), _ext4((hi >> 20) & 15), _ext4((hi >> 12) & 15))
        c2 = (_ext4((hi >> 24) & 15), _ext4((hi >> 16) & 15), _ext4((hi >> 8) & 15))
    out = [None] * 16
    for x in range(4):
        for y in range(4):
            i = x * 4 + y
            sub2 = (y >= 2) if flip else (x >= 2)
            base, tab = (c2, t2) if sub2 else (c1, t1)
            idx = ((lo >> (16 + i)) & 1) << 1 | ((lo >> i) & 1)
            m = _MOD[tab][idx]
            out[i] = (_clamp(base[0] + m), _clamp(base[1] + m), _clamp(base[2] + m))
    return out


def decode_level(data: bytes, w: int, h: int, fmt: int, alpha_order: str = "col") -> bytes:
    """-> RGBA bytes, top row first of the stored (PICA bottom-up) orientation flipped to top-down."""
    pw, ph = max(w, 8), max(h, 8)
    pw, ph = (pw + 7) & ~7, (ph + 7) & ~7
    img = bytearray(pw * ph * 4)
    pos = 0
    bs = 16 if fmt == FMT_ETC1A4 else 8
    for ty in range(0, ph, 8):
        for tx in range(0, pw, 8):
            for zx, zy in _Z:
                blk = data[pos:pos + bs]
                pos += bs
                if len(blk) < bs:
                    raise ValueError("truncated TEX data")
                if fmt == FMT_ETC1A4:
                    al = int.from_bytes(blk[:8], "little"); col = _etc1_block(blk[8:])
                else:
                    al = None; col = _etc1_block(blk)
                for x in range(4):
                    for y in range(4):
                        a = 255
                        if al is not None:
                            n = (x * 4 + y) if alpha_order == "col" else (y * 4 + x)
                            a = _ext4((al >> (4 * n)) & 15)
                        r, g, b = col[x * 4 + y]
                        px, py = tx + zx + x, ty + zy + y
                        o = (py * pw + px) * 4
                        img[o:o + 4] = bytes((r, g, b, a))
    rows = [bytes(img[(ph - 1 - y) * pw * 4:(ph - 1 - y) * pw * 4 + w * 4]) for y in range(h)]
    return b"".join(rows)


def decode(d: bytes, level: int = 0, **kw):
    """-> (width, height, RGBA bytes) for mip ``level``."""
    h = parse_header(d)
    sizes = mip_sizes(h)
    if 0x10 + sum(sizes) != len(d):
        raise ValueError(f"size mismatch: header implies {0x10 + sum(sizes)}, have {len(d)}")
    off = 0x10 + sum(sizes[:level])
    w, hh = max(h["width"] >> level, 1), max(h["height"] >> level, 1)
    return w, hh, decode_level(d[off:off + sizes[level]], w, hh, h["format"], **kw)


def png(w: int, h: int, rgba: bytes) -> bytes:
    def ch(t, b):
        c = struct.pack(">I", len(b)) + t + b
        return c + struct.pack(">I", zlib.crc32(t + b) & 0xFFFFFFFF)
    raw = b"".join(b"\0" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))
    return (b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + ch(b"IDAT", zlib.compress(raw, 6)) + ch(b"IEND", b""))
