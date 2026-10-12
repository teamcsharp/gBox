"""Marvel vs. Capcom 2 (Dreamcast) character DAT container decoder.

A character's graphics live in ``PLxx_DAT.BIN`` on the data track.  The file
starts with a 16-slot u32 section table (offsets; a size is the delta to the
next non-zero offset):

  slot 0  GFX1: part pixels.  ``u32 4*nParts``, then ``nParts`` u32 part
          offsets (part 0 sits right after the table), then per-part blobs.
          A blob is a 4-byte header ``[lw][lh][sw][sh]`` followed by an
          LZSS stream; the decoded size is ``(sw*8)*(sh*8)//2`` 4bpp indices
          in Dreamcast twiddled order.  (A PAL8 part, 8bpp, is a rare escape
          hatch for other characters; PL00 decodes clean as 4bpp.)
  slot 1  GFX2: sprite assembly.  ``u32 4*nSprites``, then ``nSprites`` u32
          offsets into the section.  Each sprite: ``u16 count`` then
          ``count`` 8-byte records ``{s16 dx, s16 dy, u16 flags, u16 sel}``;
          the part is placed at the running ``(px, py)`` with
          ``px += dx; py -= dy``.  flags: 0x4000 = flip X, 0x8000 = flip Y.
  slot 2  palette head (small); the palette space proper starts here and
          spans 65536 bytes = 2048 banks x 16 colors x u16 ARGB4444 LE
          (index 0 is transparent).  The game's "slot 3 is always 64 KB"
          observation is the bulk of that palette space.
  slot 5  animation: a small pre-table (0x100 bytes; 0x200 for character
          0x34), a u32 group-pointer table until a null entry, then per
          group a sub-animation pointer table and 20-byte cells
          ``{u8 dur@2, u8 ender@3 (bit 0x80 = last), u16 sprite_id@4,
          u8 render_extra@0x11, u8 hitbox_group@0x12}``.
  slot 6  hitbox pattern table.

The LZSS codec is byte-exact with the game's own decompressor at
``loc_8c0354c0`` (1ST_READ.BIN file offset 0x254c0): MSB-first flag bytes;
a CLEAR flag bit copies one literal byte, a SET bit takes one byte ``b``
and copies ``(b & 0x0F) + 2`` bytes from ``dst - (b >> 4) - 1``, with the
output buffer as its own window.

1ST_READ.BIN (sha256 862e43cd..., base 0x8c010000) references the disc file
names through a 401-entry pointer array at file offset 0x138688
(FAC/VOI/WIN/DAT/S_PL/stage files); the load-by-index stub is at
0x8c027390 and the load-by-name routine at 0x8c0272d8.
"""

from __future__ import annotations

import struct

# 1ST_READ addresses for this exact build (T1212N V1.001, sha256 862e43cd...)
EXE_BASE = 0x8C010000
DECODEA_VA = 0x8C0354C0      # file offset 0x254c0; GFX1 LZSS decompressor
NAME_TABLE_OFF = 0x138688    # 401 name pointers: FAC, VOI, WIN, DAT, S_PL, ...
LOAD_BY_INDEX_VA = 0x8C027390
LOAD_BY_NAME_VA = 0x8C0272D8

ARGB4444 = "ARGB4444"  # palette texel format
PAL_BANKS = 2048
PAL_COLORS = 16


def decodeA(src: bytes, dest_len: int) -> bytes:
    """GFX1 LZSS decode (port of 1ST_READ loc_8c0354c0)."""
    out = bytearray()
    sp = 0
    bc = 0
    flags = 0
    n = len(src)
    while len(out) < dest_len and sp < n:
        if bc == 0:
            flags = src[sp]
            sp += 1
            bc = 0x80
            if sp >= n:
                break
        if (flags & bc) == 0:  # literal
            out.append(src[sp])
            sp += 1
        else:  # back-ref: dist = b>>4, count = (b&0xF)+2, from dst-(dist+1)
            b = src[sp]
            sp += 1
            pos = len(out) - (b >> 4) - 1
            for _ in range((b & 0x0F) + 2):
                out.append(out[pos] if 0 <= pos < len(out) else 0)
                pos += 1
        bc >>= 1
    if len(out) < dest_len:
        out.extend(b"\x00" * (dest_len - len(out)))
    return bytes(out[:dest_len])


def _twiddle_slow(x: int, y: int, x_sz: int, y_sz: int) -> int:
    rv = 0
    sh = 0
    x_sz >>= 1
    y_sz >>= 1
    while x_sz != 0 or y_sz != 0:
        if y_sz != 0:
            rv |= (y & 1) << sh
            y_sz >>= 1
            y >>= 1
            sh += 1
        if x_sz != 0:
            rv |= (x & 1) << sh
            x_sz >>= 1
            x >>= 1
            sh += 1
    return rv


_DETW = [[[0] * 1024 for _ in range(11)] for _ in range(2)]
for _s in range(11):
    _ysz = 1 << _s
    for _i in range(1024):
        _DETW[0][_s][_i] = _twiddle_slow(_i, 0, 1024, _ysz)
        _DETW[1][_s][_i] = _twiddle_slow(0, _i, _ysz, 1024)

_PAL4_ORDER = [(0, 0), (0, 1), (1, 0), (1, 1), (0, 2), (0, 3), (1, 2), (1, 3),
               (2, 0), (2, 1), (3, 0), (3, 1), (2, 2), (2, 3), (3, 2), (3, 3)]


def detwiddle_pal4(data: bytes, w: int, h: int) -> bytes:
    """TWIDDLED 4bpp texels -> linear per-pixel indices (bottom-up storage order)."""
    if w > 1024 or h > 1024 or (w & (w - 1)) or (h & (h - 1)):
        raise ValueError(f"part {w}x{h} not a power-of-two <= 1024")
    bcx = w.bit_length() - 1
    bcy = h.bit_length() - 1
    idx = bytearray(w * h)
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            blk = (_DETW[0][bcy][x] + _DETW[1][bcx][y]) // 16
            base = blk * 8
            for i, (cx, cy) in enumerate(_PAL4_ORDER):
                b = data[base + (i >> 1)] if base + (i >> 1) < len(data) else 0
                nib = (b & 0xF) if (i & 1) == 0 else ((b >> 4) & 0xF)
                idx[(y + cy) * w + (x + cx)] = nib
    return bytes(idx)


def vflip(buf: bytes, w: int, h: int) -> bytes:
    """Bottom-up storage order -> top-down display order."""
    return b"".join(buf[y * w:(y + 1) * w] for y in range(h - 1, -1, -1))


def twiddle_pal4(idx: bytes, w: int, h: int) -> bytes:
    """Linear per-pixel 4bpp indices (bottom-up storage order) -> twiddled bytes (W*H/2)."""
    if w > 1024 or h > 1024 or (w & (w - 1)) or (h & (h - 1)):
        raise ValueError(f"part {w}x{h} not a power-of-two <= 1024")
    bcx = w.bit_length() - 1
    bcy = h.bit_length() - 1
    data = bytearray(w * h // 2)
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            blk = (_DETW[0][bcy][x] + _DETW[1][bcx][y]) // 16
            base = blk * 8
            for i, (cx, cy) in enumerate(_PAL4_ORDER):
                nib = idx[(y + cy) * w + (x + cx)] & 0xF
                bp = base + (i >> 1)
                if (i & 1) == 0:
                    data[bp] = (data[bp] & 0xF0) | nib
                else:
                    data[bp] = (data[bp] & 0x0F) | (nib << 4)
    return bytes(data)


def dat_sections(dat: bytes) -> list[int]:
    """The 16-slot section table as absolute offsets (0 = empty)."""
    if len(dat) < 0x40:
        raise ValueError("DAT too short for a section table")
    return list(struct.unpack_from("<16I", dat, 0))


def section_bounds(dat: bytes, slot: int) -> tuple[int, int]:
    """(start, end) of a slot; end is the next non-zero offset or EOF."""
    tab = dat_sections(dat)
    if not tab[slot]:
        raise ValueError(f"slot {slot} is empty")
    start = tab[slot]
    end = len(dat)
    for v in tab[slot + 1:]:
        if v:
            end = min(end, v)
            break
    return start, end


def part_count(dat: bytes) -> int:
    gfx1 = dat_sections(dat)[0]
    return struct.unpack_from("<I", dat, gfx1)[0] // 4


def part_geom(dat: bytes, sel: int) -> tuple[int, int, int, int]:
    """(gfx1_base, blob_start, blob_end, W, H) for part `sel`."""
    gfx1 = dat_sections(dat)[0]
    n = part_count(dat)
    if not (0 <= sel < n):
        raise IndexError(f"part {sel} out of range 0..{n - 1}")
    o0 = struct.unpack_from("<I", dat, gfx1 + sel * 4)[0]
    o1 = (struct.unpack_from("<I", dat, gfx1 + (sel + 1) * 4)[0]
          if sel + 1 < n else dat_sections(dat)[1] - gfx1)
    hdr = dat[gfx1 + o0:gfx1 + o0 + 4]
    return gfx1, gfx1 + o0, gfx1 + o1, hdr[2] * 8, hdr[3] * 8


def part_indices(dat: bytes, sel: int, display: bool = True) -> tuple[bytes, int, int]:
    """Decoded part -> (per-pixel 4bpp indices, W, H), display order by default."""
    gfx1, o0, o1, w, h = part_geom(dat, sel)
    raw = decodeA(dat[o0 + 4:o1], w * h // 2)
    lin = detwiddle_pal4(raw, w, h)
    return (vflip(lin, w, h) if display else lin), w, h


def palette_bank(dat: bytes, bank: int = 0) -> list[tuple[int, int, int, int]]:
    """16 RGBA colors of palette bank `bank` (ARGB4444 LE, idx 0 transparent)."""
    pal = dat_sections(dat)[2]
    base = pal + bank * 32
    out = []
    for i in range(PAL_COLORS):
        if base + i * 2 + 1 >= len(dat):
            out.append((0, 0, 0, 0))
            continue
        v = dat[base + i * 2] | (dat[base + i * 2 + 1] << 8)
        a = (v >> 12) & 0xF
        r = (v >> 8) & 0xF
        g = (v >> 4) & 0xF
        b = v & 0xF
        out.append((0, 0, 0, 0) if i == 0 else (r * 17, g * 17, b * 17, a * 17 if a else 255))
    return out


def sprite_records(dat: bytes, sprite_id: int) -> list[dict]:
    """GFX2 assembly of sprite `sprite_id`: {dx, dy, part, flip, flipy}."""
    gfx2 = dat_sections(dat)[1]
    n = struct.unpack_from("<I", dat, gfx2)[0] // 4
    if not (0 <= sprite_id < n):
        raise IndexError(f"sprite {sprite_id} out of range 0..{n - 1}")
    off = struct.unpack_from("<I", dat, gfx2 + sprite_id * 4)[0]
    (cnt,) = struct.unpack_from("<H", dat, gfx2 + off)
    if cnt > 256:
        raise ValueError(f"sprite {sprite_id}: implausible record count {cnt}")
    recs = []
    px = py = 0
    for i in range(cnt):
        p = gfx2 + off + 2 + i * 8
        dx, dy, flags, sel = struct.unpack_from("<hhHH", dat, p)
        px += dx
        py -= dy
        recs.append({"dx": px, "dy": py, "part": sel,
                     "flip": bool(flags & 0x4000), "flipy": bool(flags & 0x8000)})
    return recs


def animation_groups(dat: bytes, cid: int = 0) -> dict:
    """Parse the slot-5 animation tables into {group: {subanims: [[cells]]}}."""
    anim_base = dat_sections(dat)[5]
    sec_end = dat_sections(dat)[6]
    sec_len = sec_end - anim_base
    pre = 0x200 if cid == 0x34 else 0x100
    gt = anim_base + pre
    groups = {}
    for g in range(256):
        base = struct.unpack_from("<I", dat, gt + g * 4)[0]
        if not base or base >= sec_len:
            break
        subanims = []
        for si in range(256):
            cell_off = struct.unpack_from("<I", dat, anim_base + base + si * 4)[0]
            if not cell_off or cell_off >= sec_len:
                break
            cells = []
            pos = anim_base + cell_off
            for _ in range(512):
                if pos + 20 > len(dat):
                    break
                ender = dat[pos + 3]
                cells.append({
                    "sprite_id": struct.unpack_from("<H", dat, pos + 4)[0],
                    "duration": dat[pos + 2],
                    "render_extra": dat[pos + 0x11],
                    "hitbox_group": dat[pos + 0x12],
                })
                pos += 20
                if ender & 0x80:
                    break
            if cells:
                subanims.append(cells)
        if subanims:
            groups[g] = subanims
    return groups


def render_sprite(dat: bytes, sprite_id: int, bank: int = 0) -> tuple[int, int, bytes]:
    """Compose sprite `sprite_id` -> (W, H, RGBA rows) with bank `bank` colors."""
    pal = palette_bank(dat, bank)
    n_parts = part_count(dat)
    parts = {}
    min_x = min_y = 0
    max_x = max_y = 0
    for rec in sprite_records(dat, sprite_id):
        sel = rec["part"]
        if sel >= n_parts:
            continue
        if sel not in parts:
            idx, w, h = part_indices(dat, sel)
            parts[sel] = (idx, w, h)
        idx, w, h = parts[sel]
        x0 = rec["dx"]
        y0 = rec["dy"]
        min_x = min(min_x, x0)
        max_x = max(max_x, x0 + w)
        min_y = min(min_y, y0)
        max_y = max(max_y, y0 + h)
    W, H = max_x - min_x, max_y - min_y
    if W <= 0 or H <= 0:
        return 0, 0, b""
    rgba = bytearray(W * H * 4)
    for rec in sprite_records(dat, sprite_id):
        sel = rec["part"]
        if sel >= n_parts or sel not in parts:
            continue
        idx, w, h = parts[sel]
        ox, oy = rec["dx"] - min_x, rec["dy"] - min_y
        for y in range(h):
            for x in range(w):
                c = idx[y * w + x]
                if c == 0:
                    continue
                sx = (w - 1 - x) if rec["flip"] else x
                sy = (h - 1 - y) if rec["flipy"] else y
                c = idx[sy * w + sx]
                if c == 0:
                    continue
                r, g, b, a = pal[c]
                if a == 0:
                    continue
                p = ((oy + y) * W + (ox + x)) * 4
                rgba[p:p + 4] = bytes((r, g, b, 255))
    return W, H, bytes(rgba)


def render_cell(dat: bytes, cid: int = 0, group: int = 0, sub: int = 0,
                cell: int = 0, bank: int = 0) -> tuple[int, int, bytes]:
    """Render one animation cell of PL`cid` to RGBA."""
    anim = animation_groups(dat, cid)
    cells = anim[group][sub]
    sid = cells[cell]["sprite_id"] & 0x7FFF
    return render_sprite(dat, sid, bank)


def _png(rgba: bytes, w: int, h: int, path: str) -> None:
    """Write RGBA rows as a PNG (requires Pillow; optional helper)."""
    from PIL import Image  # noqa: PLC0415 - optional dependency
    Image.frombytes("RGBA", (w, h), rgba).save(path)


def main(argv=None) -> int:
    import argparse
    import hashlib
    import json
    import pathlib
    import sys

    ap = argparse.ArgumentParser(description="MVC2 DC PLxx_DAT.BIN inspector")
    ap.add_argument("dat", type=pathlib.Path)
    ap.add_argument("--json", action="store_true", help="dump a summary manifest")
    ap.add_argument("--png", type=pathlib.Path, help="render cell group/sub/cell to a PNG")
    ap.add_argument("--group", type=int, default=0)
    ap.add_argument("--sub", type=int, default=0)
    ap.add_argument("--cell", type=int, default=0)
    ap.add_argument("--cid", type=lambda s: int(s, 16), default=0)
    args = ap.parse_args(argv)

    dat = args.dat.read_bytes()
    tab = dat_sections(dat)
    n_parts = part_count(dat)
    n_sprites = struct.unpack_from("<I", dat, tab[1])[0] // 4
    anim = animation_groups(dat, args.cid)
    summary = {
        "sections": {i: v for i, v in enumerate(tab) if v},
        "n_parts": n_parts,
        "n_sprites": n_sprites,
        "n_anim_groups": len(anim),
        "palette_bank0": [f"{r:02x}{g:02x}{b:02x}{a:02x}"
                          for r, g, b, a in palette_bank(dat, 0)],
        "sha256": hashlib.sha256(dat).hexdigest(),
    }
    if args.png:
        w, h, rgba = render_cell(dat, args.cid, args.group, args.sub, args.cell)
        _png(rgba, w, h, str(args.png))
        summary["png"] = {"path": str(args.png), "w": w, "h": h}
    if args.json or args.png:
        json.dump(summary, sys.stdout, indent=2)
    else:
        print(f"parts={n_parts} sprites={n_sprites} anim_groups={len(anim)} "
              f"sha256={summary['sha256'][:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
