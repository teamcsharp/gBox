"""Resident Evil - Dead Aim (PS2) character texture ('miz') and shape ('fsc') headers.

Evidence (owned USA CHD, SLUS_206.69, request #1904).  Little-endian.

miz ('wZIM', 0xC0-byte header + GS upload packets, pixels at 0x240):
  0x00 'wZIM', 0x2c u16 width, u16 height, 0x4c u32 palette bytes (0x400 -> 8bpp,
  0x40 -> 4bpp).  Pixels (w*h*bpp/8 bytes) start at 0x240 and are followed
  directly by the palette (RGBA8888 entries, alpha 0..0x80); file size equals
  0x240 + pixel bytes + palette bytes (+ optional pad).  8bpp pixels are
  row-linear (smoothness metric 55.6 raw vs 101 after PSMT8 unswizzle).
  Palette index order is not yet confirmed (CSM1 swap gives 61.4 vs 55.6 raw).

fsc ('CSFg', one per mesh part in allshp.bin): 0x0f ASCII kind tag (e.g. 'CARM',
  'CBRU'), name string after it; five u32 at 0x38 section table:
  [data_start(0x4c), s1, s2, s3, end] with end == file size.  Vertex/strip
  encoding of the sections is NOT decoded yet.
"""
from __future__ import annotations

import struct
from typing import Dict, Tuple

MIZ_MAGIC = b"wZIM"
FSC_MAGIC = b"CSFg"
MIZ_PIXELS = 0x240


def parse_miz(data: bytes) -> Dict:
    if data[:4] != MIZ_MAGIC:
        raise ValueError("not a miz texture")
    w, h = struct.unpack_from("<HH", data, 0x2C)
    pal_bytes = struct.unpack_from("<I", data, 0x4C)[0]
    bpp = {0x400: 8, 0x40: 4}.get(pal_bytes)
    if bpp is None:
        raise ValueError("unsupported palette size 0x%x" % pal_bytes)
    npix = w * h * bpp // 8
    need = MIZ_PIXELS + npix + pal_bytes
    if len(data) < need:
        raise ValueError("truncated miz: %d < %d" % (len(data), need))
    return {"width": w, "height": h, "bpp": bpp, "pixels": data[MIZ_PIXELS:MIZ_PIXELS + npix],
            "palette": data[MIZ_PIXELS + npix:need], "pad": len(data) - need}


def miz_to_rgba(tex: Dict) -> bytes:
    pal = tex["palette"]
    cols = [bytes((pal[i * 4], pal[i * 4 + 1], pal[i * 4 + 2], min(255, pal[i * 4 + 3] * 2)))
            for i in range(len(pal) // 4)]
    out = bytearray()
    px = tex["pixels"]
    for i in range(tex["width"] * tex["height"]):
        idx = px[i] if tex["bpp"] == 8 else (px[i >> 1] >> (4 * (i & 1))) & 15
        out += cols[idx]
    return bytes(out)


def parse_fsc_header(data: bytes) -> Dict:
    if data[:4] != FSC_MAGIC:
        raise ValueError("not an fsc shape")
    tag = data[0x0F:0x13].split(b"\0")[0].decode("latin1")
    name = data[0x14:0x34].split(b"\0")[0].decode("latin1")
    sec = struct.unpack_from("<5I", data, 0x38)
    return {"kind": tag, "name": name, "sections": sec, "size_matches": sec[4] == len(data)}
