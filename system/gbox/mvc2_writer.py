"""MVC2 (Dreamcast) PLxx_DAT.BIN GFX1 writer: LZSS encoder + part replacement.

Inverse of :mod:`gbox.mvc2_dat` for slot 0 (part pixels).  The encoder emits
the stream format of the game's decompressor (1ST_READ ``loc_8c0354c0``):
MSB-first flag byte, bit clear = literal, bit set = one byte
``((dist-1) << 4) | (len-2)`` (dist 1..16, len 2..17).

``replace_part`` rewrites one part blob (same W/H, 4bpp indices in display
order), rebuilds the GFX1 pointer table and shifts every later section
offset by the size delta.  Nothing is written to disc images; callers get new
bytes to stage as a separate mod file.
"""
from __future__ import annotations

import struct

from . import mvc2_dat as M

MAX_LEN = 17
MAX_DIST = 16


def encodeA(data: bytes) -> bytes:
    """Greedy LZSS encode; ``M.decodeA(encodeA(d), len(d)) == d``."""
    out = bytearray()
    n = len(data)
    i = 0
    while i < n:
        flag_pos = len(out)
        out.append(0)
        flags = 0
        for bit in range(8):
            if i >= n:
                break
            best_len, best_d = 0, 0
            lim = min(MAX_LEN, n - i)
            for d in range(1, min(MAX_DIST, i) + 1):
                l = 0
                while l < lim and data[i + l - d] == data[i + l]:
                    l += 1
                if l > best_len:
                    best_len, best_d = l, d
            if best_len >= 2:
                flags |= 0x80 >> bit
                out.append(((best_d - 1) << 4) | (best_len - 2))
                i += best_len
            else:
                out.append(data[i])
                i += 1
        out[flag_pos] = flags
    return bytes(out)


def encode_part_pixels(indices: bytes, w: int, h: int) -> bytes:
    """Display-order per-pixel 4bpp indices -> LZSS(twiddled) payload."""
    if len(indices) != w * h:
        raise ValueError(f"need {w * h} indices, got {len(indices)}")
    return encodeA(M.twiddle_pal4(M.vflip(bytes(indices), w, h), w, h))


def replace_part(dat: bytes, sel: int, indices: bytes, w: int | None = None,
                 h: int | None = None) -> bytes:
    """Return a new DAT with part ``sel`` replaced by ``indices`` (W*H bytes, 0..15)."""
    gfx1, o0, o1, pw, ph = M.part_geom(dat, sel)
    if (w, h) not in ((None, None), (pw, ph)):
        raise ValueError(f"slot geometry is {pw}x{ph}; donor is {w}x{h}")
    if any(v > 15 for v in indices):
        raise ValueError("indices must be 4bpp (0..15)")
    n = M.part_count(dat)
    tab = list(struct.unpack_from(f"<{n}I", dat, gfx1))
    blob = bytes(dat[o0:o0 + 4]) + encode_part_pixels(indices, pw, ph)
    # keep the original blob's size slot when the new one is no larger, so
    # unrelated offsets stay put; otherwise shift everything after it.
    old_len = o1 - o0
    if len(blob) < old_len:
        blob += b"\x00" * (old_len - len(blob))
    delta = len(blob) - old_len
    new = bytearray(dat[:o0]) + blob + dat[o1:]
    if delta:
        for k in range(sel + 1, n):
            tab[k] += delta
        struct.pack_into(f"<{n}I", new, gfx1, *tab)
        secs = M.dat_sections(dat)
        shifted = [s + delta if s and s > o0 else s for s in secs]
        struct.pack_into("<16I", new, 0, *shifted)
    return bytes(new)
