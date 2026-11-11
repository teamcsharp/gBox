"""Konductra (NDS) stage-2 Nitro sprite parsers: NCLR / NCGR / NCER / NANR.

Read-only parsers plus byte-exact re-serialisers so a no-op roundtrip can be
proven before any writer exists.  Layouts were checked against the owned build
(ROM sha256 a71cafed...a6b1): every NCGR/NCLR/NCER/NANR has a 16-byte Nitro
header (magic, BOM 0xFEFF, version, size, hdr size 16, block count) followed by
tagged blocks (reversed 4CC: RAHC, TTLP, KBEC, KNBA ...).
"""
from __future__ import annotations

import struct

NITRO_MAGICS = {b"RGCN": "NCGR", b"RLCN": "NCLR", b"RECN": "NCER",
                b"RNAN": "NANR", b"RCSN": "NSCR"}

# OAM size table: (shape, size) -> (w, h) in pixels
OAM_DIMS = {
    (0, 0): (8, 8), (0, 1): (16, 16), (0, 2): (32, 32), (0, 3): (64, 64),
    (1, 0): (16, 8), (1, 1): (32, 8), (1, 2): (32, 16), (1, 3): (64, 32),
    (2, 0): (8, 16), (2, 1): (8, 32), (2, 2): (16, 32), (2, 3): (32, 64),
}


def blocks(data: bytes) -> dict[bytes, bytes]:
    """Return {block magic: block bytes incl. 8-byte block header}; validates ranges."""
    if data[:4] not in NITRO_MAGICS:
        raise ValueError(f"not a known Nitro container: {data[:4]!r}")
    bom, _ver, size, hdr, nblk = struct.unpack_from("<HHIHH", data, 4)
    if bom != 0xFEFF or hdr != 16 or size != len(data):
        raise ValueError("bad Nitro header (bom/hdr/size)")
    off, out = hdr, {}
    for _ in range(nblk):
        if off + 8 > len(data):
            raise ValueError("block header out of range")
        magic, bsz = struct.unpack_from("<4sI", data, off)
        if bsz < 8 or off + bsz > len(data):
            raise ValueError("block size out of range")
        out[magic] = data[off:off + bsz]
        off += bsz
    if off != len(data):
        raise ValueError("trailing bytes after last block")
    return out


def rebuild(data: bytes) -> bytes:
    """Re-serialise a Nitro container from its parsed blocks (no-op roundtrip)."""
    b = blocks(data)
    body = b"".join(b.values())
    head = data[:4] + struct.pack("<HHIHH", 0xFEFF, struct.unpack_from("<H", data, 6)[0],
                                  16 + len(body), 16, len(b))
    return head + body


# ---------------------------------------------------------------- NCLR
def parse_nclr(data: bytes) -> dict:
    blk = blocks(data)[b"TTLP"]
    depth, _pad, size, count = struct.unpack_from("<IIII", blk, 8)
    raw = blk[24:24 + size]
    cols = struct.unpack(f"<{len(raw) // 2}H", raw)
    return {"depth": depth, "colors": list(cols), "banks": len(cols) // 16}


def rgb555(c: int) -> tuple[int, int, int]:
    return ((c & 31) * 255 // 31, ((c >> 5) & 31) * 255 // 31, ((c >> 10) & 31) * 255 // 31)


# ---------------------------------------------------------------- NCGR
def parse_ncgr(data: bytes) -> dict:
    blk = blocks(data)[b"RAHC"]
    th, tw, depth, _pad, flags, size, off = struct.unpack_from("<HHIIIII", blk, 8)
    bpp = {3: 4, 4: 8}[depth]
    tile_bytes = 32 if bpp == 4 else 64
    raw = blk[8 + off:8 + off + size]
    return {"tiles_h": th, "tiles_w": tw, "bpp": bpp, "tile_bytes": tile_bytes,
            "tile_count": len(raw) // tile_bytes, "pixel_data": raw, "flags": flags}


def tile_is_blank(ncgr: dict, idx: int) -> bool:
    t = ncgr["tile_bytes"]
    return not any(ncgr["pixel_data"][idx * t:(idx + 1) * t])


# ---------------------------------------------------------------- NCER
def parse_ncer(data: bytes) -> list[dict]:
    blk = blocks(data)[b"KBEC"]
    ncell, attr, cells_off, _map = struct.unpack_from("<HHII", blk, 8)
    body = blk[8:]
    cell_sz = 16 if attr == 1 else 8
    oam_base = cells_off + ncell * cell_sz
    cells = []
    for i in range(ncell):
        co = cells_off + i * cell_sz
        nobj, cattr, ooff = struct.unpack_from("<HHI", body, co)
        oams = []
        for j in range(nobj):
            a0, a1, a2 = struct.unpack_from("<HHH", body, oam_base + ooff + j * 6)
            shape, size = (a0 >> 14) & 3, (a1 >> 14) & 3
            x = a1 & 0x1FF
            oams.append({"y": a0 & 0xFF, "x": x - 512 if x >= 256 else x,
                         "shape": shape, "size": size, "dims": OAM_DIMS.get((shape, size)),
                         "tile": a2 & 0x3FF, "palette": (a2 >> 12) & 15,
                         "colors256": bool(a0 & 0x2000)})
        cells.append({"cell_attr": cattr, "oams": oams})
    return cells


# ---------------------------------------------------------------- NANR
def parse_nanr(data: bytes) -> dict:
    blk = blocks(data)[b"KNBA"]
    nseq, nframes, seq_off, frame_off, _fd = struct.unpack_from("<HHIII", blk, 8)
    return {"sequences": nseq, "frames": nframes}


def tiles_used(cells: list[dict]) -> list[int]:
    """Tile indices referenced by all OAMs of a cell bank (1D mapping, 4bpp)."""
    used = set()
    for c in cells:
        for o in c["oams"]:
            w, h = o["dims"] or (8, 8)
            for k in range((w // 8) * (h // 8)):
                used.add(o["tile"] + k)
    return sorted(used)


# ------------------------------------------------- stage 2/3: render + tile writer
def tile_pixels(ncgr: dict, idx: int) -> list[list[int]]:
    """8x8 palette indices of one 4bpp tile (low nibble = left pixel)."""
    t = ncgr["tile_bytes"]
    raw = ncgr["pixel_data"][idx * t:(idx + 1) * t]
    if ncgr["bpp"] == 4:
        px = [v for b in raw for v in (b & 15, b >> 4)]
    else:
        px = list(raw)
    return [px[r * 8:(r + 1) * 8] for r in range(8)]


def render_oam(ncgr: dict, colors: list[int], oam: dict):
    """Render one OAM to (w, h, rows of RGBA) using the 2D (sheet-width) tile map.

    Resolved on the owned build: sball 16x16 cells at tiles 724/726/728/730 only
    tile up consistently when each tile row advances by tiles_w (32), not by
    the 1D mapping (those cells would overlap).
    """
    w, h = oam["dims"]
    tw = ncgr["tiles_w"]
    bank = oam["palette"] * 16
    rows = []
    for py in range(h):
        row = []
        for px in range(w):
            t = oam["tile"] + (py // 8) * tw + px // 8
            ci = tile_pixels(ncgr, t)[py % 8][px % 8]
            if ci == 0:
                row.append((0, 0, 0, 0))
            else:
                row.append(rgb555(colors[bank + ci]) + (255,))
        rows.append(row)
    return w, h, rows


def write_png(path: str, w: int, h: int, rows, scale: int = 1) -> None:
    import zlib
    raw = b""
    for row in rows:
        line = b"".join(bytes(p) * scale for p in row)
        raw += (b"\x00" + line) * scale

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w * scale, h * scale, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def oam_tile_indices(oam: dict, tiles_w: int) -> list[int]:
    w, h = oam["dims"]
    return [oam["tile"] + r * tiles_w + c for r in range(h // 8) for c in range(w // 8)]


def replace_tiles(data: bytes, tile_map: dict[int, bytes]) -> bytes:
    """Return NCGR bytes with whole tiles replaced in place (same size; no pointers move)."""
    g = parse_ncgr(data)
    blk = blocks(data)[b"RAHC"]
    th, tw, depth, _p, flags, size, off = struct.unpack_from("<HHIIIII", blk, 8)
    base = data.index(blk) + 8 + off
    out = bytearray(data)
    tb = g["tile_bytes"]
    for idx, new in tile_map.items():
        if len(new) != tb or not 0 <= idx < g["tile_count"]:
            raise ValueError(f"tile {idx}: bad size/index")
        out[base + idx * tb:base + (idx + 1) * tb] = new
    return bytes(out)


def patch_rom_file(rom: bytes, start: int, old_len: int, new: bytes) -> bytes:
    """Same-size in-place file swap inside an NDS image (FAT unchanged)."""
    if len(new) != old_len:
        raise ValueError("size change unsupported (FAT/offset rewrite not implemented)")
    return rom[:start] + new + rom[start + old_len:]
