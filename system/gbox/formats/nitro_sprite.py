"""Nitro 2D character-sprite parsers (NCGR 'RGCN' tiles, NCLR 'RLCN' palettes) as used by the
Pokemon Black/White (IRAO) battle-sprite NARC ``a/0/0/4``.

Observed layout of a/0/0/4 (14285 members = 20 per species-form group; first group read from real bytes):
  +0 LZ11 NCGR (front tiles) +2 LZ11 NCGR (back tiles) +4 NCER ('RECN') +5 LZ11 NMCR ('RCMN' cell map)
  +6/+7 NANR/NMAR-style animation banks ('RAMN' ...) +18/+19 NCLR ('RLCN') normal / shiny palette.
Hypothesis (unproved): the NCGR file-size field in these sprites is stale (0x2030 vs real 0x1230);
parsing therefore trusts the RAHC data-size field and checks it against the buffer.
"""
from __future__ import annotations

import struct


def _hdr(blob: bytes, magic: bytes) -> int:
    if blob[:4] != magic or blob[4:6] != b"\xff\xfe":
        raise ValueError(f"not {magic!r}")
    hsize, nblk = struct.unpack_from("<HH", blob, 12)
    if hsize != 0x10 or nblk < 1:
        raise ValueError("bad Nitro header")
    return hsize


def parse_ncgr(blob: bytes) -> dict:
    """NCGR -> {tiles_y, tiles_x, depth_bpp (4|8), tile_data (bytes)}; tiles_y/x 0xFFFF = unsized."""
    pos = _hdr(blob, b"RGCN")
    if blob[pos:pos + 4] != b"RAHC":
        raise ValueError("missing RAHC")
    ty, tx, depth = struct.unpack_from("<HHI", blob, pos + 8)
    dsize, doff = struct.unpack_from("<II", blob, pos + 0x18)
    if depth not in (3, 4):
        raise ValueError(f"unsupported depth {depth}")
    if doff != 0x18:
        raise ValueError(f"unexpected RAHC data offset {doff:#x}")
    start = pos + 0x20
    data = blob[start:start + dsize]
    if len(data) != dsize:
        raise ValueError(f"tile data {len(data)} != RAHC size {dsize}")
    bpp = 4 if depth == 3 else 8
    return {"tiles_y": ty, "tiles_x": tx, "depth_bpp": bpp, "tile_data": data,
            "tile_count": dsize // (32 if bpp == 4 else 64)}


def parse_nclr(blob: bytes) -> dict:
    """NCLR -> {depth_bpp, colors: [(r,g,b)...]} (BGR555 expanded to 8 bits)."""
    pos = _hdr(blob, b"RLCN")
    if blob[pos:pos + 4] != b"TTLP":
        raise ValueError("missing TTLP")
    depth, _pad, psize, _cnt = struct.unpack_from("<IIII", blob, pos + 8)
    n = psize // 2
    words = struct.unpack_from(f"<{n}H", blob, pos + 0x18)
    cols = [((w & 31) * 255 // 31, ((w >> 5) & 31) * 255 // 31, ((w >> 10) & 31) * 255 // 31) for w in words]
    return {"depth_bpp": 4 if depth == 3 else 8, "colors": cols}


def tile_indices(ncgr: dict) -> list[list[int]]:
    """Per-tile 8x8 colour-index grids (row-major) from a parsed NCGR."""
    d, out = ncgr["tile_data"], []
    size = 32 if ncgr["depth_bpp"] == 4 else 64
    for t in range(ncgr["tile_count"]):
        raw = d[t * size:(t + 1) * size]
        if ncgr["depth_bpp"] == 4:
            px = [v for b in raw for v in (b & 15, b >> 4)]
        else:
            px = list(raw)
        out.append(px)
    return out


def build_ncgr(tile_data: bytes, tiles_y: int, tiles_x: int, bpp: int = 4) -> bytes:
    """Minimal NCGR writer (used for round-trip tests; real-file size field not reproduced)."""
    rahc = (b"RAHC" + struct.pack("<IHHIIIII", 0x20 + len(tile_data), tiles_y, tiles_x,
                                 3 if bpp == 4 else 4, 0, 0, len(tile_data), 0x18) + tile_data)
    return b"RGCN" + b"\xff\xfe\x01\x01" + struct.pack("<IHH", 0x10 + len(rahc), 0x10, 1) + rahc
