"""Tetris 4D (Japan) - Dreamcast Ninja PVR character/texture reader and writer.

Verified against the owned build (source identity reused across stages):

    CHD           531a6ce7fb56c8bdb367d9c98eb724b13404d548f0e817e9958a6f55fb456058
    1ST_READ.BIN  5579d8c6f9e21e570eecb880d4ac52d688c3ba17428ce2cd7be81c9b66a86055

Asset slots on the disc (all Sega Ninja PVR, GBIX + PVRT chunks):

    MENU/MENUMODEL/05*.PVR   7 character portraits, 64x64, pixfmt 2 (ARGB4444),
                             data format 0x03 (VQ 2x2 codebook, 256 entries),
                             GBIX 5100..5106, 3104 bytes each
    GAME/AO.PVR .. WAKU.PVR  gameplay textures, 16x16 / 32x32, pixfmt 1 (RGB565),
                             data format 0x02 (twiddled + mip chain) / 0x01 (twiddled)
    GAME/TETRIS.PVR         128x64, pixfmt 2 (ARGB4444), data format 0x09 (linear)

Every storage mode used by this title round-trips byte-exactly through
encode_pvr_like(), and the 7 character portraits accept a donor image of
identical dimensions (donor_swap) without changing the file size, the GBIX id
or the texture format.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from gbox import ninja

GBIX_MAGIC = b"GBIX"
PVRT_MAGIC = b"PVRT"

DFMT_TWIDDLED = 0x01
DFMT_TWIDDLED_MIP = 0x02
DFMT_VQ = 0x03
DFMT_VQ_MIP = 0x04
DFMT_LINEAR = 0x09

DFMT_NAMES = {
    0x01: "twiddled",
    0x02: "twiddled-mipmapped",
    0x03: "vq-2x2",
    0x04: "vq-2x2-mipmapped",
    0x09: "linear",
    0x0B: "linear-stride",
}

PIX_NAMES = {0: "ARGB1555", 1: "RGB565", 2: "ARGB4444"}

#: Portrait slots shipped with the game (7 playable characters), in GBIX order.
CHARACTER_SLOTS = (
    "05AKA", "05AO", "05KIIRO", "05MIDORI",
    "05MURASAKI", "05ORANGE", "05PINK",
)

#: GBIX texture ids of the character portraits (read from the owned disc).
CHARACTER_GBIX = {slot: 5100 + i for i, slot in enumerate(CHARACTER_SLOTS)}


@dataclass(frozen=True)
class PvrHeader:
    pvrt_offset: int
    chunk_size: int
    pixfmt: int
    dfmt: int
    width: int
    height: int
    gbix: int | None

    @property
    def storage(self) -> str:
        return DFMT_NAMES.get(self.dfmt, "unknown-%#x" % self.dfmt)

    @property
    def pixel_format(self) -> str:
        return PIX_NAMES.get(self.pixfmt, "unknown-%d" % self.pixfmt)

    def describe(self) -> str:
        gb = "none" if self.gbix is None else str(self.gbix)
        return "%dx%d %s %s gbix=%s" % (
            self.width, self.height, self.pixel_format, self.storage, gb)


def parse_pvr(data: bytes) -> PvrHeader:
    """Parse a Ninja PVR file (GBIX chunk optional, PVRT chunk required)."""
    off = data.find(PVRT_MAGIC)
    if off < 0:
        raise ValueError("not a PVR file: no PVRT chunk")
    size = struct.unpack_from("<I", data, off + 4)[0]
    if off + 8 + size > len(data):
        raise ValueError("truncated PVR chunk")
    pixfmt, dfmt = data[off + 8], data[off + 9]
    w, h = struct.unpack_from("<HH", data, off + 12)
    gbix = None
    g = data.find(GBIX_MAGIC)
    if 0 <= g < off and g + 8 <= len(data):
        gbix = struct.unpack_from("<I", data, g + 8)[0]
    return PvrHeader(off, size, pixfmt, dfmt, w, h, gbix)


def decode_pvr(data: bytes) -> tuple[int, int, bytes]:
    """Decode a PVR into (width, height, RGBA8888 bytes)."""
    w, h, rgba, _desc = ninja.pvr_decode(data)
    return w, h, rgba


def _encode_twiddled(hdr: PvrHeader, arr: np.ndarray, body: bytes) -> bytes:
    w, h = hdr.width, hdr.height
    s = min(w, h)
    if w % s or h % s or (w // s) * (h // s) * s * s != w * h:
        raise ValueError("non-square twiddled layouts are not supported")
    base_len = w * h * 2
    base = bytearray(base_len)
    for y in range(h):
        for x in range(w):
            blk = (y // s) * (w // s) + (x // s)
            off = 2 * (blk * s * s + ninja._twiddle(x % s, y % s))
            struct.pack_into("<H", base, off, ninja._px16(arr[y, x], hdr.pixfmt))
    if hdr.dfmt == DFMT_TWIDDLED_MIP:
        # mip chain lives in front of the base level; keep it verbatim
        return body[:len(body) - base_len] + bytes(base)
    return bytes(base)


def _encode_linear(hdr: PvrHeader, arr: np.ndarray, body: bytes) -> bytes:
    w, h = hdr.width, hdr.height
    out = bytearray(w * h * 2)
    for y in range(h):
        for x in range(w):
            struct.pack_into("<H", out, 2 * (y * w + x),
                             ninja._px16(arr[y, x], hdr.pixfmt))
    return bytes(out)


def _encode_vq(hdr: PvrHeader, arr: np.ndarray, body: bytes) -> bytes:
    """Re-index a VQ texture against its own codebook (codebook kept verbatim).

    The donor image is quantised with the slot's existing codebook, so the
    file size, the codebook and the texture format all stay identical.  A
    block whose original codebook entry still matches exactly keeps its
    original index, which makes the no-op round-trip byte-exact.
    """
    w, h = hdr.width, hdr.height
    if hdr.dfmt == DFMT_VQ_MIP:
        raise ValueError("mipmapped VQ is not supported by this writer")
    cb = bytearray(body[:2048])
    idx = bytearray(body[2048:])
    raw = [[struct.unpack_from("<H", cb, (c * 4 + k) * 2)[0] for k in range(4)]
           for c in range(256)]
    px = np.zeros((h, w), dtype=np.uint16)
    for y in range(h):
        for x in range(w):
            px[y, x] = ninja._px16(arr[y, x], hdr.pixfmt)
    for by in range(h // 2):
        for bx in range(w // 2):
            blk = [int(px[by * 2, bx * 2]), int(px[by * 2 + 1, bx * 2]),
                   int(px[by * 2, bx * 2 + 1]), int(px[by * 2 + 1, bx * 2 + 1])]
            ti = ninja._twiddle(bx, by)
            if raw[idx[ti]] == blk:
                continue
            best, best_d = idx[ti], None
            for c in range(256):
                e = raw[c]
                d = sum((e[k] - blk[k]) ** 2 for k in range(4))
                if best_d is None or d < best_d:
                    best_d, best = d, c
            idx[ti] = best
    return bytes(cb) + bytes(idx)


def encode_pvr_like(old: bytes, rgba: bytes) -> bytes:
    """Re-encode `old` with the pixels in `rgba`, preserving format and size."""
    hdr = parse_pvr(old)
    w, h = hdr.width, hdr.height
    if len(rgba) != w * h * 4:
        raise ValueError("pixel buffer is %d bytes, expected %d"
                         % (len(rgba), w * h * 4))
    arr = np.frombuffer(rgba, dtype=np.uint8).reshape(h, w, 4)
    q, size = hdr.pvrt_offset, hdr.chunk_size
    body = old[q + 16:q + 8 + size]
    if hdr.dfmt in (DFMT_TWIDDLED, DFMT_TWIDDLED_MIP):
        new_body = _encode_twiddled(hdr, arr, body)
    elif hdr.dfmt == DFMT_VQ:
        new_body = _encode_vq(hdr, arr, body)
    elif hdr.dfmt in (DFMT_LINEAR, 0x0B):
        new_body = _encode_linear(hdr, arr, body)
    else:
        raise ValueError("unsupported PVR data format %#x" % hdr.dfmt)
    return old[:q + 16] + new_body + old[q + 8 + size:]


def donor_swap(target: bytes, donor: bytes) -> bytes:
    """Put the donor image into the target slot (identical dimensions required).

    The target keeps its own format, codebook and size, so the result can be
    written straight back over the disc asset.
    """
    t, d = parse_pvr(target), parse_pvr(donor)
    if (t.width, t.height) != (d.width, d.height):
        raise ValueError("donor is %dx%d, target slot is %dx%d"
                         % (d.width, d.height, t.width, t.height))
    _w, _h, rgba = decode_pvr(donor)
    return encode_pvr_like(target, rgba)


def portrait_slots(names) -> list[str]:
    """Select the character portrait assets from a list of disc file names."""
    out = []
    for n in names:
        up = n.upper()
        if "MENUMODEL" in up and up.rsplit("/", 1)[-1].startswith("05") \
                and up.endswith(".PVR"):
            out.append(n)
    return sorted(out)
