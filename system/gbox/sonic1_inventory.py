"""Inventory of the player sprite set in Sonic 1 (Mega Drive) engine ROMs.

Sonic 1 and the hacks rebuilt from its disassembly draw the player
(object 01) from four tables:

* mappings (``Map_Sonic``): word offset table, then per frame a count byte
  and 5-byte pieces ``y:s8 size:u8 tile:u16 x:s8``;
* dynamic pattern load cues (``SonicDynPLC``): word offset table, then per
  frame a count byte and 2-byte entries ``(n-1)<<12 | first_tile``;
* uncompressed 4bpp art (``Art_Sonic``), streamed into VRAM ``$F000``
  (art tile ``$780``) each frame by the DPLC loader;
* the 16-colour line-0 palette entry of ``PalPointers`` (dest ``$FB00``).

The animation scripts (``Ani_Sonic``) index the mapping frames.  Hacks move
every table, so this module finds them through the code that references
them rather than through fixed addresses, decodes them, and renders a
sprite sheet as evidence that the offsets are right.

``python -m gbox.sonic1_inventory ROM --out manifest.json --sheet s.png``
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import zipfile
import zlib
from pathlib import Path

ROM_EXT = ('.bin', '.md', '.gen', '.smd')

# LoadSonicDynPLC, DMA-queue variant (used by most disassembly-based hacks):
#   lea (SonicDynPLC).l,a2 ; add.w d0,d0 ; adda.w (a2,d0.w),a2
#   moveq #0,d5 ; move.b (a2)+,d5 ; subq.w #1,d5 ; bmi.s ...
#   move.w #vram,d4 ; move.l #Art_Sonic,d6
DPLC_DMA = re.compile(
    rb'\x45\xf9(....)\xd0\x40\xd4\xf2\x00\x00\x7a\x00\x1a\x1a\x53\x45\x6b.'
    rb'\x38\x3c(..)\x2c\x3c(....)', re.S)
# Object init: move.l #Map_Sonic,obMap(a0) close to move.w #$780,obGfx(a0)
MAP_INIT = re.compile(rb'\x21\x7c(....)\x00\x04', re.S)
# Sonic_Animate: lea (Ani_Sonic).l,a1 ; moveq #0,d0 ; move.b obAnim(a0),d0
ANI = re.compile(rb'\x43\xf9(....)\x70\x00\x10\x28\x00\x1c', re.S)
# PalLoad: lea (PalPointers).l,a1 ; lsl.w #3,d0 ; adda.w d0,a1 ;
#          movea.l (a1)+,a2 ; movea.w (a1)+,a3 ; move.w (a1)+,d7
PALLOAD = re.compile(rb'\x43\xf9(....)\xe7\x48\xd2\xc0\x24\x59\x36\x59\x3e\x19', re.S)


class InventoryError(ValueError):
    pass


def deinterleave_smd(d: bytes) -> bytes:
    """Convert a 512-byte-header SMD dump to a flat big-endian image."""
    body = d[512:]
    out = bytearray(len(body))
    for b in range(0, len(body), 16384):
        blk = body[b:b + 16384]
        half = len(blk) // 2
        out[b + 1:b + len(blk):2] = blk[:half]
        out[b:b + len(blk):2] = blk[half:]
    return bytes(out)


def read_rom(path) -> tuple[bytes, dict]:
    """Return the flat ROM bytes and a description of the container."""
    p = Path(path)
    raw = p.read_bytes()
    info = {'container': str(p), 'container_sha256': hashlib.sha256(raw).hexdigest(),
            'container_size': len(raw), 'member': None, 'interleaved': False}
    if raw[:4] == b'PK\x03\x04':
        with zipfile.ZipFile(p) as z:
            names = [n for n in z.namelist() if n.lower().endswith(ROM_EXT)]
            if len(names) != 1:
                raise InventoryError(f'expected one ROM member, found {names}')
            info['member'] = names[0]
            d = z.read(names[0])
    else:
        d = raw
    if d[0x100:0x104] != b'SEGA' and len(d) % 16384 == 512:
        d = deinterleave_smd(d)
        info['interleaved'] = True
    if d[0x100:0x104] != b'SEGA':
        raise InventoryError('no SEGA header at 0x100; not a Mega Drive image')
    info['rom_sha256'] = hashlib.sha256(d).hexdigest()
    info['rom_md5'] = hashlib.md5(d).hexdigest()
    info['rom_size'] = len(d)
    return d, info


def header(d: bytes) -> dict:
    txt = lambda a, b: d[a:b].decode('latin-1').strip()
    stored = struct.unpack('>H', d[0x18e:0x190])[0]
    n = (len(d) - 0x200) // 2
    calc = sum(struct.unpack(f'>{n}H', d[0x200:0x200 + 2 * n])) & 0xFFFF
    start, end = struct.unpack('>II', d[0x1a0:0x1a8])
    return {'console': txt(0x100, 0x110), 'copyright': txt(0x110, 0x120),
            'title_domestic': txt(0x120, 0x150), 'title_overseas': txt(0x150, 0x180),
            'serial': txt(0x180, 0x18e), 'region': txt(0x1f0, 0x200),
            'checksum': f'{stored:04x}', 'checksum_calc': f'{calc:04x}',
            'checksum_ok': stored == calc, 'rom_end': f'{end:06x}',
            'sram': d[0x1b0:0x1b2] == b'RA'}


def _u32(d, a):
    return struct.unpack('>I', d[a:a + 4])[0]


def _u16(d, a):
    return struct.unpack('>H', d[a:a + 2])[0]


def locate(d: bytes) -> dict:
    """Find the player's tables through the code that references them."""
    out = {}
    hits = list(DPLC_DMA.finditer(d))
    if not hits:
        raise InventoryError('LoadSonicDynPLC (DMA-queue variant) not found')
    m = hits[0]
    out['dplc_loader'] = m.start()
    out['dplc'] = _u32(m.group(1), 0)
    out['vram'] = _u16(m.group(2), 0)
    out['art'] = _u32(m.group(3), 0)
    art_tile = out['vram'] // 32
    maps = {}
    for m in MAP_INIT.finditer(d):
        near = d[m.end():m.end() + 8]
        if b'\x31\x7c' + struct.pack('>H', art_tile) + b'\x00\x02' in near:
            maps.setdefault(_u32(m.group(1), 0), []).append(m.start())
    if not maps:
        raise InventoryError(f'no object init uses art tile {art_tile:#x}')
    out['mappings'] = max(maps, key=lambda k: len(maps[k]))
    out['mapping_refs'] = sorted(maps[out['mappings']])
    m = ANI.search(d)
    out['animations'] = _u32(m.group(1), 0) if m else None
    m = PALLOAD.search(d)
    out['pal_pointers'] = _u32(m.group(1), 0) if m else None
    out['palette'] = None
    if m:
        t = out['pal_pointers']
        for i in range(0x40):
            src, dst, ln = struct.unpack('>IHH', d[t + 8 * i:t + 8 * i + 8])
            if src >= len(d):
                break
            if dst == 0xFB00 and ln == 7:
                out['palette'], out['palette_index'] = src, i
                break
    return out


def offset_table(d: bytes, base: int, limit: int = 1024) -> list[int]:
    """Absolute frame addresses of a word offset table (S1 style)."""
    offs, lo, i = [], None, 0
    while i < limit:
        if lo is not None and 2 * i >= lo:
            break
        o = _u16(d, base + 2 * i)
        # Frame data is byte-packed, so odd offsets are normal (0x105 ...).
        if base + o >= len(d):
            break
        if o >= 2 and (lo is None or o < lo):
            lo = o
        offs.append(base + o)
        i += 1
    return offs


def mapping_frames(d: bytes, base: int) -> list[list[dict]]:
    frames = []
    for a in offset_table(d, base):
        n = d[a]
        pieces = []
        for k in range(n):
            y, size, tile, x = struct.unpack('>bBHb', d[a + 1 + 5 * k:a + 6 + 5 * k])
            pieces.append({'x': x, 'y': y, 'w': ((size >> 2) & 3) + 1, 'h': (size & 3) + 1,
                           'tile': tile & 0x7FF, 'hflip': bool(tile & 0x800),
                           'vflip': bool(tile & 0x1000), 'pal': (tile >> 13) & 3,
                           'pri': bool(tile & 0x8000)})
        frames.append(pieces)
    return frames


def dplc_frames(d: bytes, base: int) -> list[list[tuple[int, int]]]:
    frames = []
    for a in offset_table(d, base):
        n = d[a]
        ents = []
        for k in range(n):
            w = _u16(d, a + 1 + 2 * k)
            ents.append((w & 0xFFF, (w >> 12) + 1))
        frames.append(ents)
    return frames


def animation_scripts(d: bytes, base: int) -> list[dict]:
    scripts = []
    for a in offset_table(d, base, 128):
        dur, frames, end = d[a], [], None
        for k in range(1, 256):
            b = d[a + k]
            if b >= 0xFC:
                end = {0xFF: 'loop', 0xFE: 'back', 0xFD: 'goto', 0xFC: 'routine'}[b]
                break
            frames.append(b)
        scripts.append({'addr': a, 'duration': dur, 'frames': frames, 'end': end})
    return scripts


def palette(d: bytes, addr: int | None) -> list[tuple[int, int, int]]:
    if addr is None:
        return [(i * 17, i * 17, i * 17) for i in range(16)]
    cols = []
    for i in range(16):
        c = _u16(d, addr + 2 * i)
        cols.append(tuple(((c >> s) & 7) * 255 // 7 for s in (1, 5, 9)))
    return cols


def render_frame(art: bytes, pieces: list[dict], cues: list[tuple[int, int]], pal):
    """Return (left, top, width, height, rgba) for one frame, or None if empty."""
    buf = b''.join(art[t * 32:(t + n) * 32] for t, n in cues)
    if not pieces:
        return None
    x0 = min(p['x'] for p in pieces)
    y0 = min(p['y'] for p in pieces)
    x1 = max(p['x'] + 8 * p['w'] for p in pieces)
    y1 = max(p['y'] + 8 * p['h'] for p in pieces)
    w, h = x1 - x0, y1 - y0
    px = bytearray(w * h * 4)
    for p in reversed(pieces):            # first piece has highest priority
        for c in range(p['w']):
            for r in range(p['h']):
                t = p['tile'] + c * p['h'] + r
                tile = buf[t * 32:t * 32 + 32]
                if len(tile) < 32:
                    continue
                cc = p['w'] - 1 - c if p['hflip'] else c
                rr = p['h'] - 1 - r if p['vflip'] else r
                for ty in range(8):
                    for tx in range(8):
                        v = tile[ty * 4 + tx // 2]
                        v = v >> 4 if tx % 2 == 0 else v & 15
                        if not v:
                            continue
                        sx = 7 - tx if p['hflip'] else tx
                        sy = 7 - ty if p['vflip'] else ty
                        X = p['x'] - x0 + cc * 8 + sx
                        Y = p['y'] - y0 + rr * 8 + sy
                        o = (Y * w + X) * 4
                        px[o:o + 4] = bytes(pal[v]) + b'\xff'
    return x0, y0, w, h, bytes(px)


def png(w: int, h: int, rgba: bytes) -> bytes:
    def chunk(t, b):
        return struct.pack('>I', len(b)) + t + b + struct.pack('>I', zlib.crc32(t + b))
    rows = b''.join(b'\0' + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows, 9)) + chunk(b'IEND', b''))


def sprite_sheet(art, maps, cues, pal, cols=16, cell=64) -> bytes:
    n = len(maps)
    rows = (n + cols - 1) // cols
    W, H = cols * cell, rows * cell
    sheet = bytearray(W * H * 4)
    for i, (pieces, cue) in enumerate(zip(maps, cues)):
        r = render_frame(art, pieces, cue, pal)
        if not r:
            continue
        x0, y0, w, h, px = r
        ox = (i % cols) * cell + cell // 2 + x0
        oy = (i // cols) * cell + cell // 2 + y0
        for y in range(h):
            for x in range(w):
                X, Y = ox + x, oy + y
                if not (0 <= X < W and 0 <= Y < H) or px[(y * w + x) * 4 + 3] == 0:
                    continue
                sheet[(Y * W + X) * 4:(Y * W + X) * 4 + 4] = px[(y * w + x) * 4:(y * w + x) * 4 + 4]
    return png(W, H, bytes(sheet))


def inventory(path, sheet: str | None = None) -> dict:
    d, src = read_rom(path)
    hdr = header(d)
    loc = locate(d)
    maps = mapping_frames(d, loc['mappings'])
    cues = dplc_frames(d, loc['dplc'])
    if len(maps) != len(cues):
        raise InventoryError(f'{len(maps)} mapping frames but {len(cues)} DPLC frames')
    tiles = max((t + n for f in cues for t, n in f), default=0)
    art = d[loc['art']:loc['art'] + tiles * 32]
    if len(art) != tiles * 32:
        raise InventoryError('player art runs past the end of the ROM')
    bad = [i for i, (m, c) in enumerate(zip(maps, cues))
           if any(p['tile'] + p['w'] * p['h'] > sum(n for _, n in c) for p in m)]
    if bad:
        raise InventoryError(f'mapping pieces exceed their DPLC tiles in frames {bad[:8]}')
    scripts = animation_scripts(d, loc['animations']) if loc['animations'] else []
    used = sorted({f for s in scripts for f in s['frames'] if f < len(maps)})
    pal = palette(d, loc['palette'])
    title = hdr['title_overseas'] or hdr['title_domestic']
    name = 'Shadow' if 'SHADOW' in title.upper() else 'Sonic'
    frames = [{'id': i, 'pieces': len(m), 'tiles': sum(n for _, n in c),
               'max_tile_buffer': sum(n for _, n in c) * 32}
              for i, (m, c) in enumerate(zip(maps, cues))]
    hx = lambda v: None if v is None else f'0x{v:06x}'
    man = {
        'engine': 'sonic1-md', 'source': src, 'header': hdr,
        'launch': {'platform': 'genesis', 'core': 'genesis_plus_gx', 'bios': None,
                   'cartridge_bytes': len(d), 'sram': hdr['sram']},
        'player': {
            'name': name, 'object': '01 (player)', 'slot': 'sonic',
            'dplc_loader': hx(loc['dplc_loader']), 'mappings': hx(loc['mappings']),
            'mapping_refs': [hx(a) for a in loc['mapping_refs']],
            'dplc': hx(loc['dplc']), 'art': hx(loc['art']), 'art_tiles': tiles,
            'art_bytes': tiles * 32, 'art_sha256': hashlib.sha256(art).hexdigest(),
            'vram': f'0x{loc["vram"]:04x}', 'art_tile': f'0x{loc["vram"] // 32:03x}',
            'max_frame_tiles': max(f['tiles'] for f in frames),
            'palette': hx(loc['palette']), 'palette_index': loc.get('palette_index'),
            'palette_rgb': [list(c) for c in pal],
            'animations': hx(loc['animations']), 'animation_count': len(scripts),
            'frames': len(maps), 'frames_used_by_animations': len(used),
        },
        'frames': frames,
        'animations': [{'id': i, 'addr': hx(s['addr']), 'duration': s['duration'],
                        'frames': s['frames'], 'end': s['end']} for i, s in enumerate(scripts)],
        'roster': [{'slot': 'sonic', 'name': name, 'kind': '2d-sprite',
                    'frames': len(maps), 'animations': len(scripts)}],
    }
    if sheet:
        data = sprite_sheet(art, maps, cues, pal)
        Path(sheet).write_bytes(data)
        man['sheet'] = {'path': str(sheet), 'sha256': hashlib.sha256(data).hexdigest()}
    return man


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('rom')
    ap.add_argument('--out')
    ap.add_argument('--sheet')
    a = ap.parse_args(argv)
    man = inventory(a.rom, a.sheet)
    text = json.dumps(man, indent=1)
    if a.out:
        Path(a.out).write_text(text)
    p = man['player']
    print(json.dumps({k: p[k] for k in ('name', 'mappings', 'dplc', 'art', 'art_tiles',
                                        'frames', 'animation_count', 'palette')}))


if __name__ == '__main__':
    main()
