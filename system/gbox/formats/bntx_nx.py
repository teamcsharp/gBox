"""Nintendo Switch BNTX reader + Tegra X1 block-linear deswizzle + BCn decode.

Used for Bayonetta 2 (Switch) ``plXXXX.wtp``: a concatenation of standalone
BNTX files (each ``BNTX\0\0\0\0`` header, file size at +0x1C, one texture).
Layout (offsets from BRTI start; matches Switch-Toolbox / switchbrew BNTX):
  +0x12 u16 tile_mode (0 = block-linear)   +0x16 u16 mip count
  +0x1C u32 format (type<<8|data_type)     +0x24 width  +0x28 height
  +0x2C depth  +0x30 array len  +0x34 u32 layout (low 3 bits = log2 block height in GOBs)
  +0x50 u32 image size  +0x54 u32 alignment  +0x60 u64 name ptr  +0x70 u64 mip-ptr table
Mip pointers are absolute offsets inside the same BNTX file.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import List

import numpy as np

# type byte -> (name, bytes per 4x4 block)
BC_FORMATS = {0x1A: ("BC1", 8), 0x1B: ("BC2", 16), 0x1C: ("BC3", 16),
              0x1D: ("BC4", 8), 0x1E: ("BC5", 16), 0x20: ("BC7", 16)}
# ASTC type bytes 0x2D.. -> block footprint (w,h); all 16 bytes/block
ASTC_FOOTPRINT = {0x2D: (4, 4), 0x2E: (5, 4), 0x2F: (5, 5), 0x30: (6, 5), 0x31: (6, 6),
                  0x32: (8, 5), 0x33: (8, 6), 0x34: (8, 8), 0x35: (10, 5), 0x36: (10, 6),
                  0x37: (10, 8), 0x38: (10, 10), 0x39: (12, 10), 0x3A: (12, 12)}
MAX_DIM = 16384


@dataclass
class Texture:
    offset: int            # absolute offset of the BNTX container in the buffer
    name: str
    tile_mode: int
    mips: int
    fmt: int
    width: int
    height: int
    depth: int
    array_len: int
    block_height_log2: int
    image_size: int
    mip_offsets: List[int] = field(default_factory=list)  # relative to container

    @property
    def codec(self):
        t = self.fmt >> 8
        if t in ASTC_FOOTPRINT:
            return ("ASTC%dx%d" % ASTC_FOOTPRINT[t], 16)
        return BC_FORMATS.get(t)


def split_bntx(buf: bytes) -> List[int]:
    """Offsets of concatenated BNTX containers (each padded to 0x1000 in .wtp)."""
    out, pos = [], 0
    while pos + 0x40 <= len(buf) and buf[pos:pos + 8] == b"BNTX\0\0\0\0":
        size = struct.unpack_from("<I", buf, pos + 0x1C)[0]
        if size < 0x40 or pos + size > len(buf):
            raise ValueError(f"bad BNTX size {size:#x} at {pos:#x}")
        out.append(pos)
        pos = (pos + size + 0xFFF) & ~0xFFF
    return out


def parse_bntx(buf: bytes, base: int = 0) -> List[Texture]:
    if buf[base:base + 8] != b"BNTX\0\0\0\0":
        raise ValueError("not BNTX")
    size = struct.unpack_from("<I", buf, base + 0x1C)[0]
    end = base + size
    if size < 0x40 or end > len(buf):
        raise ValueError("BNTX truncated")
    n, tt = struct.unpack_from("<IQ", buf, base + 0x24)[0], struct.unpack_from("<Q", buf, base + 0x28)[0]
    if n > 4096 or tt + 8 * n > size:
        raise ValueError("bad texture table")
    res = []
    for i in range(n):
        b = struct.unpack_from("<Q", buf, base + tt + 8 * i)[0]
        if b + 0x78 > size or buf[base + b:base + b + 4] != b"BRTI":
            raise ValueError("bad BRTI")
        p = base + b
        u32 = lambda o: struct.unpack_from("<I", buf, p + o)[0]
        u16 = lambda o: struct.unpack_from("<H", buf, p + o)[0]
        u64 = lambda o: struct.unpack_from("<Q", buf, p + o)[0]
        mips = u16(0x16)
        nm = u64(0x60)
        name = ""
        if 0 < nm and nm + 2 <= size:
            ln = struct.unpack_from("<H", buf, base + nm)[0]
            name = buf[base + nm + 2:base + nm + 2 + ln].decode("utf-8", "replace")
        ml = u64(0x70)
        if mips > 32 or ml + 8 * mips > size:
            raise ValueError("bad mip table")
        offs = [struct.unpack_from("<Q", buf, base + ml + 8 * m)[0] for m in range(mips)]
        if any(o >= size for o in offs):
            raise ValueError("mip pointer out of range")
        w, h = u32(0x24), u32(0x28)
        if not (0 < w <= MAX_DIM and 0 < h <= MAX_DIM):
            raise ValueError("bad dimensions")
        res.append(Texture(base, name, u16(0x12), mips, u32(0x1C), w, h, u32(0x2C),
                           u32(0x30), u32(0x34) & 7, u32(0x50), offs))
    return res


def _gob_offset_table(bw: int, bh: int, bpb: int, bh_gobs: int) -> np.ndarray:
    """Byte offset in swizzled data of each (block_y, block_x) -> shape (bh,bw)."""
    pitch = bw * bpb
    gobs_x = (pitch + 63) // 64
    ys = np.arange(bh)[:, None]
    xb = (np.arange(bw) * bpb)[None, :]            # byte x of the block
    gob_row = ys // 8
    blk_row = gob_row // bh_gobs
    gob_in_blk = gob_row % bh_gobs
    gob_x = xb // 64
    x = xb % 64
    y = ys % 8
    in_gob = ((x % 64) // 32) * 256 + ((y % 8) // 2) * 64 + ((x % 32) // 16) * 32 + (y % 2) * 16 + (x % 16)
    gob_addr = (blk_row * gobs_x * bh_gobs + gob_x * bh_gobs + gob_in_blk) * 512
    return gob_addr + in_gob


def deswizzle(data: bytes, w: int, h: int, bpb: int, bh_log2: int, tex_block=(4, 4)) -> bytes:
    """Block-linear -> row-major block data (w,h in texels; tex_block = block edge)."""
    bw, bh = (w + tex_block[0] - 1) // tex_block[0], (h + tex_block[1] - 1) // tex_block[1]
    bh_gobs = 1 << bh_log2
    # Tegra shrinks block height for small surfaces
    while bh_gobs > 1 and (bh + 7) // 8 <= bh_gobs // 2:
        bh_gobs //= 2
    tbl = _gob_offset_table(bw, bh, bpb, bh_gobs)
    need = int(tbl.max()) + bpb
    if len(data) < need:
        raise ValueError(f"swizzled data short: {len(data)} < {need}")
    arr = np.frombuffer(data, dtype=np.uint8)
    idx = tbl[..., None] + np.arange(bpb)
    return arr[idx].reshape(-1).tobytes()


def _c565(c):
    r = ((c >> 11) & 31) * 255 // 31
    g = ((c >> 5) & 63) * 255 // 63
    b = (c & 31) * 255 // 31
    return np.stack([r, g, b], -1).astype(np.int32)


def _bc1_colors(blk: np.ndarray, force4: bool):
    c0 = blk[:, 0].astype(np.int32) | (blk[:, 1].astype(np.int32) << 8)
    c1 = blk[:, 2].astype(np.int32) | (blk[:, 3].astype(np.int32) << 8)
    a, b = _c565(c0), _c565(c1)
    four = (c0 > c1) | force4
    p2 = np.where(four[:, None], (2 * a + b) // 3, (a + b) // 2)
    p3 = np.where(four[:, None], (a + 2 * b) // 3, 0)
    pal = np.stack([a, b, p2, p3], 1)                      # (n,4,3)
    bits = blk[:, 4:8].astype(np.uint32)
    word = bits[:, 0] | (bits[:, 1] << 8) | (bits[:, 2] << 16) | (bits[:, 3] << 24)
    sel = (word[:, None] >> (2 * np.arange(16))[None, :]) & 3   # (n,16)
    rgb = np.take_along_axis(pal, sel[..., None].repeat(3, -1), 1)
    alpha = np.full((len(blk), 16), 255, np.int32)
    tr = (~four)[:, None] & (sel == 3)
    alpha[tr] = 0
    return rgb, alpha


def _bc4_values(blk: np.ndarray):
    a0, a1 = blk[:, 0].astype(np.int32), blk[:, 1].astype(np.int32)
    k = np.arange(8)[None, :]
    big = a0 > a1
    p_big = np.where(k < 2, np.where(k == 0, a0[:, None], a1[:, None]),
                     ((8 - k) * a0[:, None] + (k - 1) * a1[:, None]) // 7)
    p_small = np.where(k < 2, np.where(k == 0, a0[:, None], a1[:, None]),
                       np.where(k < 6, ((6 - k) * a0[:, None] + (k - 1) * a1[:, None]) // 5,
                                np.where(k == 6, 0, 255)))
    pal = np.where(big[:, None], p_big, p_small)
    bits = np.zeros(len(blk), dtype=np.uint64)
    for i in range(6):
        bits |= blk[:, 2 + i].astype(np.uint64) << np.uint64(8 * i)
    sel = ((bits[:, None] >> (3 * np.arange(16, dtype=np.uint64))[None, :]) & np.uint64(7)).astype(np.int64)
    return np.take_along_axis(pal, sel, 1)                  # (n,16)


def decode_bcn(linear: bytes, w: int, h: int, type_byte: int) -> np.ndarray:
    """Decode row-major BC1..BC5 blocks to RGBA uint8 (h,w,4)."""
    name, bpb = BC_FORMATS[type_byte]
    bw, bh = (w + 3) // 4, (h + 3) // 4
    blk = np.frombuffer(linear, dtype=np.uint8)[: bw * bh * bpb].reshape(-1, bpb)
    n = len(blk)
    out = np.zeros((n, 16, 4), np.uint8)
    if name == "BC1":
        rgb, al = _bc1_colors(blk, False)
        out[..., :3], out[..., 3] = rgb, al
    elif name in ("BC2", "BC3"):
        rgb, _ = _bc1_colors(blk[:, 8:], True)
        out[..., :3] = rgb
        if name == "BC3":
            out[..., 3] = _bc4_values(blk[:, :8])
        else:
            nib = np.zeros((n, 16), np.int32)
            for i in range(16):
                nib[:, i] = (blk[:, i // 2] >> (4 * (i % 2))) & 15
            out[..., 3] = nib * 17
    elif name == "BC4":
        v = _bc4_values(blk)
        out[..., 0] = out[..., 1] = out[..., 2] = v
        out[..., 3] = 255
    elif name == "BC5":
        out[..., 0] = _bc4_values(blk[:, :8])
        out[..., 1] = _bc4_values(blk[:, 8:])
        out[..., 3] = 255
    img = out.reshape(bh, bw, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)
    return img[:h, :w]


def _t2d(fn, linear: bytes, w: int, h: int, *extra) -> np.ndarray:
    import texture2ddecoder as t2d
    bgra = np.frombuffer(getattr(t2d, fn)(linear, w, h, *extra), np.uint8).reshape(h, w, 4)
    return bgra[..., [2, 1, 0, 3]].copy()


def decode_mip(buf: bytes, tex: Texture, level: int = 0) -> np.ndarray:
    codec = tex.codec
    if codec is None:
        raise NotImplementedError(f"format {tex.fmt:#x}")
    if tex.tile_mode != 0:
        raise NotImplementedError("linear tile_mode")
    _, bpb = codec
    t = tex.fmt >> 8
    fp = ASTC_FOOTPRINT.get(t, (4, 4))
    w, h = max(1, tex.width >> level), max(1, tex.height >> level)
    start = tex.offset + tex.mip_offsets[level]
    end = (tex.offset + tex.mip_offsets[level + 1]) if level + 1 < tex.mips else \
        tex.offset + struct.unpack_from("<I", buf, tex.offset + 0x1C)[0]
    lin = deswizzle(buf[start:end], w, h, bpb, tex.block_height_log2, fp)
    if t in ASTC_FOOTPRINT:
        return _t2d("decode_astc", lin, w, h, fp[0], fp[1])
    if t == 0x20:
        return _t2d("decode_bc7", lin, w, h)
    return decode_bcn(lin, w, h, t)


def write_png(path: str, img: np.ndarray) -> None:
    import struct as s, zlib
    h, w, _ = img.shape
    raw = b"".join(b"\0" + img[y].tobytes() for y in range(h))
    def ch(t, d):
        c = s.pack(">I", len(d)) + t + d
        return c + s.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", s.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                           + ch(b"IDAT", zlib.compress(raw, 6)) + ch(b"IEND", b""))
