"""Writer constraints and a no-op re-encoder for the Sonic 1 (Mega Drive) player.

``gbox.sonic1_inventory`` finds the player's tables.  This module reads the
code that consumes them and turns it into rules a sprite writer must obey:

* ``dma_queue``: QueueDMATransfer slot layout and capacity, and the
  per-entry limits of the DMA-queue ``LoadSonicDynPLC`` (16 tiles per entry,
  12-bit tile index, even source, no 128 KiB bank crossing);
* ``vram_budget``: VDP register setup, every PLC list, direct Nemesis loads
  and VDP write commands, i.e. the first VRAM user above the player buffer;
* ``animation_rules``: Sonic_Animate end codes and the walk/run angle
  offsets, so every frame id the scripts can reach;
* ``palette_line0``: PalPointers entries that write palette line 0, and the
  other objects drawn with line 0;
* ``pointer_sites``: every absolute operand holding a table address;
* ``sonic_art_users``: other Sonic graphics (title, continue, signpost,
  lives icon, ending) that a full swap must also cover;
* ``encode_table``/``encode_frame_map``/``encode_frame_dplc``/``pack_tiles``
  and ``roundtrip``: the byte-identical re-encode a writer starts from.

Names follow the s1disasm PLC/palette numbering and are only applied when
the tables have the stock Sonic 1 entry counts.

``python -m gbox.sonic1_analysis ROM --out analysis.json [--stock ROM]``
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

from gbox import sonic1_inventory as inv

_u16, _u32 = inv._u16, inv._u32
BANK = 0x20000                      # VDP DMA source cannot cross 128 KiB

PLC_NAMES = ['Main', 'Main2', 'Explode', 'GameOver', 'GHZ', 'GHZ2', 'LZ', 'LZ2', 'MZ',
             'MZ2', 'SLZ', 'SLZ2', 'SYZ', 'SYZ2', 'SBZ', 'SBZ2', 'TitleCard', 'Boss',
             'Signpost', 'Warp', 'SpecialStage', 'GHZAnimals', 'LZAnimals', 'MZAnimals',
             'SLZAnimals', 'SYZAnimals', 'SBZAnimals', 'SSResult', 'Ending', 'TryAgain',
             'EggmanSBZ2', 'FZBoss']
# PLC lists that never run while the DPLC-driven player is on screen in a level.
NON_LEVEL_PLCS = {'SpecialStage', 'SSResult', 'TryAgain'}
PAL_NAMES = ['SegaBG', 'Title', 'LevelSel', 'Sonic', 'GHZ', 'LZ', 'MZ', 'SLZ', 'SYZ',
             'SBZ1', 'Special', 'LZWater', 'SBZ3', 'SBZ3Water', 'SBZ2', 'LZSonWater',
             'SBZ3SonWat', 'SSResult', 'Continue', 'Ending']
# (PLC name, VRAM) of Sonic graphics outside the DPLC set (s1disasm labels).
PLC_SONIC_ART = {('Main', 0xFA80): 'Nem_Lives (HUD lives icon)',
                 ('Signpost', 0xD000): 'Nem_SignPost (end-of-act signpost face)',
                 ('SSResult', 0xAA20): 'Nem_MiniSonic (special-stage results)',
                 ('Ending', 0x7C20): 'Nem_EndSonic (ending sequence Sonic)',
                 ('Ending', 0xB8A0): 'Nem_EndStH (ending SONIC THE HEDGEHOG logo)'}

ADDPLC = re.compile(rb'\x43\xf9(....)\xd0\x40\x30\x31\x00\x00\x43\xf1\x00\x00', re.S)
NEMLOAD = re.compile(rb'\x23\xfc(....)\x00\xc0\x00\x04\x41\xf9(....)(?:\x61\x00(..)|\x4e\xb9(....))',
                     re.S)
VDPCMD = re.compile(rb'(?=\x23\xfc(....)\x00\xc0\x00\x04|[\x2a\x2c]\xbc(....))', re.S)
CALLS = re.compile(rb'(?=(\x4e[\xb9\xf9]....|\x4e[\xb8\xf8\xba\xfa]..|[\x60\x61]\x00..))', re.S)
OBGFX = re.compile(rb'(?=[\x31\x33]\x7c(..)\x00\x02)', re.S)


class AnalysisError(ValueError):
    pass


def hx(v):
    return None if v is None else f'0x{v:06x}'


def _sha(b) -> str:
    return hashlib.sha256(bytes(b)).hexdigest()


def _s16(d, a):
    return struct.unpack('>h', d[a:a + 2])[0]


# --------------------------------------------------------------- encoders --

def encode_frame_map(pieces) -> bytes:
    """One S1 mapping frame: count byte, then 5-byte ``y size tile x`` pieces."""
    out = bytearray([len(pieces)])
    for p in pieces:
        if not (1 <= p['w'] <= 4 and 1 <= p['h'] <= 4 and 0 <= p['tile'] <= 0x7FF):
            raise AnalysisError(f'bad mapping piece {p}')
        tile = (p['tile'] | p['hflip'] << 11 | p['vflip'] << 12 | p['pal'] << 13
                | p['pri'] << 15)
        out += struct.pack('>bBHb', p['y'], (p['w'] - 1) << 2 | (p['h'] - 1), tile, p['x'])
    return bytes(out)


def encode_frame_dplc(cues) -> bytes:
    """One DPLC frame: count byte, then ``(n-1)<<12 | first_tile`` words."""
    out = bytearray([len(cues)])
    for t, n in cues:
        if not (1 <= n <= 16 and 0 <= t <= 0xFFF):
            raise AnalysisError(f'bad DPLC entry tile {t:#x} count {n}')
        out += struct.pack('>H', (n - 1) << 12 | t)
    return bytes(out)


def encode_table(blobs, share=None) -> bytes:
    """Word offset table followed by byte-packed frames (odd offsets allowed).

    ``share`` maps a frame index to an earlier index whose data it reuses."""
    share = share or {}
    offs, body = [], bytearray()
    for i, b in enumerate(blobs):
        if i in share:
            offs.append(offs[share[i]])
            continue
        offs.append(2 * len(blobs) + len(body))
        body += b
    if offs and max(offs) > 0xFFFF:
        raise AnalysisError('frame table exceeds the 64 KiB word-offset range')
    return struct.pack(f'>{len(offs)}H', *offs) + bytes(body)


def table_span(d: bytes, base: int, step: int) -> tuple[list[int], int, dict]:
    """Frame addresses, end address and shared-frame map of a frame table."""
    addrs = inv.offset_table(d, base)
    first = {}
    share = {}
    for i, a in enumerate(addrs):
        if a in first:
            share[i] = first[a]
        else:
            first[a] = i
    return addrs, max(a + 1 + step * d[a] for a in addrs), share


def unpack_tiles(art: bytes) -> list[bytes]:
    """4bpp tiles to 64 colour indices each."""
    out = []
    for t in range(len(art) // 32):
        px = bytearray(64)
        for i, b in enumerate(art[32 * t:32 * t + 32]):
            px[2 * i], px[2 * i + 1] = b >> 4, b & 15
        out.append(bytes(px))
    return out


def pack_tiles(tiles) -> bytes:
    out = bytearray()
    for px in tiles:
        if len(px) != 64 or max(px) > 15:
            raise AnalysisError('a tile needs 64 colour indices 0-15')
        out += bytes(px[2 * i] << 4 | px[2 * i + 1] for i in range(32))
    return bytes(out)


def checksum(d: bytes) -> int:
    """S1 boot checksum: word sum from $200 through the header ROM end."""
    end = min(_u32(d, 0x1A4), len(d) - 1) & ~1
    n = (end - 0x200) // 2 + 1
    return sum(struct.unpack(f'>{n}H', d[0x200:0x200 + 2 * n])) & 0xFFFF


def fix_checksum(rom: bytearray) -> int:
    c = checksum(rom)
    rom[0x18E:0x190] = struct.pack('>H', c)
    return c


def roundtrip(d: bytes, loc: dict) -> dict:
    """Decode Map/DPLC/Art, re-encode them in place and compare bytes."""
    rom = bytearray(d)
    res = {}
    for kind, base, step, parse, enc in (
            ('mappings', loc['mappings'], 5, inv.mapping_frames, encode_frame_map),
            ('dplc', loc['dplc'], 2, inv.dplc_frames, encode_frame_dplc)):
        addrs, end, share = table_span(d, base, step)
        blob = encode_table([enc(f) for f in parse(d, base)], share)
        orig = d[base:end]
        res[kind] = {'start': hx(base), 'end': hx(end), 'bytes': len(orig), 'frames': len(addrs),
                     'shared_frames': len(share), 'in_table_order': addrs == sorted(addrs),
                     'identical': blob == orig, 'sha256': _sha(orig)}
        rom[base:base + len(blob)] = blob
    cues = inv.dplc_frames(d, loc['dplc'])
    tiles = max(t + n for f in cues for t, n in f)
    art = d[loc['art']:loc['art'] + 32 * tiles]
    again = pack_tiles(unpack_tiles(art))
    res['art'] = {'start': hx(loc['art']), 'end': hx(loc['art'] + len(art)), 'tiles': tiles,
                  'identical': again == art, 'sha256': _sha(art)}
    rom[loc['art']:loc['art'] + len(again)] = again
    res['rom_identical'] = bytes(rom) == d
    res['rom_sha256'] = _sha(rom)
    res['checksum'] = f'{checksum(rom):04x}'
    res['checksum_header'] = f'{_u16(rom, 0x18E):04x}'
    return res


# ----------------------------------------------------------- code readers --

def call_map(d: bytes) -> dict[int, list[int]]:
    """target -> call/jump sites (jsr/jmp abs.l/abs.w/d16(pc), bsr.w/bra.w)."""
    out: dict[int, list[int]] = {}
    for m in CALLS.finditer(d):
        a = m.start()
        if a % 2:
            continue
        w = _u16(d, a)
        if w in (0x4EB9, 0x4EF9):
            t = _u32(d, a + 2)
        elif w in (0x4EB8, 0x4EF8):
            t = _s16(d, a + 2) & 0xFFFFFF
        elif w in (0x4EBA, 0x4EFA):
            t = a + 2 + _s16(d, a + 2)
        else:
            t = a + 2 + _s16(d, a + 2)
        out.setdefault(t, []).append(a)
    return out


def loader_start(d: bytes, loc: dict) -> tuple[int, int]:
    """Start of the DPLC routine and its last-frame RAM byte (v_sonframenum)."""
    a = loc['dplc_loader']
    i = d.rfind(b'\x70\x00\x10\x28\x00\x1a', a - 0x20, a)
    if i < 0 or _u16(d, i + 6) != 0xB038:
        raise AnalysisError('LoadSonicDynPLC prologue not found')
    return i, _u16(d, i + 8) | 0xFF0000


def _last_op(d: bytes, lo: int, hi: int, op: bytes) -> int | None:
    """Address of the last word-aligned ``op`` in [lo, hi)."""
    i = d.rfind(op, lo, hi)
    while i >= 0 and i % 2:
        i = d.rfind(op, lo, i)
    return i if i >= 0 else None


def dplc_frames_words(d: bytes, base: int) -> list[list[tuple[int, int]]]:
    """S2-style DPLC: word offset table, then per frame a word count + entries."""
    frames = []
    for a in inv.offset_table(d, base):
        ws = [_u16(d, a + 2 + 2 * k) for k in range(_u16(d, a))]
        frames.append([(w & 0xFFF, (w >> 12) + 1) for w in ws])
    return frames


def dma_users(d: bytes, q: int, calls: dict, skip=()) -> list[dict]:
    """Other DPLC-style loaders that queue DMA transfers (``lea DPLC,a2`` ...
    ``move.w #vram,d4`` or ``move.w d16(a0),d4`` ... ``move.l #art,d6`` or
    ``addi.l #art,d1``).  A VRAM taken from an object field is resolved to the
    ``move.w #imm,field(a0/a1)`` stores near the loader."""
    out = []
    for c in calls.get(q, []):
        if c in skip:
            continue
        lo = max(0, c - 0x60)
        lea, vr = _last_op(d, lo, c, b'\x45\xf9'), _last_op(d, lo, c, b'\x38\x3c')
        fld = _last_op(d, lo, c, b'\x38\x28')                 # move.w d16(a0),d4
        art = None
        for op in (b'\x2c\x3c', b'\x06\x81'):
            i = _last_op(d, lo, c, op)
            if i is not None:
                art = _u32(d, i + 2)
        words = lea is not None and d[lea + 12:lea + 14] == b'\x3a\x1a'   # move.w (a2)+,d5
        ent = {'site': c, 'dplc': _u32(d, lea + 2) if lea is not None else None,
               'vram': _u16(d, vr + 2) if vr is not None else None, 'art': art,
               'count_bytes': 2 if words else 1, 'frames': None, 'max_tiles': None,
               'vram_field': None, 'vram_candidates': []}
        if ent['vram'] is None and fld is not None:
            off = _u16(d, fld + 2)
            pat = re.compile(rb'(?=[\x31\x33]\x7c(..)' + re.escape(struct.pack('>H', off)) + b')',
                             re.S)
            ent['vram_field'] = off
            ent['vram_candidates'] = sorted({_u16(m.group(1), 0) for m in pat.finditer(
                d, max(0, c - 0x800), c + 0x800) if m.start() % 2 == 0})
        if ent['dplc'] is not None and ent['dplc'] < len(d):
            try:
                fr = (dplc_frames_words if words else inv.dplc_frames)(d, ent['dplc'])
                ent['frames'], ent['max_tiles'] = len(fr), max(sum(n for _, n in f) for f in fr)
            except (IndexError, struct.error, ValueError):
                pass
        out.append(ent)
    return out


def dma_queue(d: bytes, loc: dict, calls: dict) -> dict:
    a = loc['dplc_loader']
    seg = d[a:a + 0x60]
    m = re.search(rb'\x4e\xb9(....)\x51\xcd', seg, re.S)   # jsr (Queue).l ; dbf d5
    if not m:
        raise AnalysisError('DPLC loader does not call QueueDMATransfer')
    q = _u32(m.group(1), 0)
    m1 = re.match(rb'\x22\x78(..)\xb2\xfc(..)', d[q:q + 8], re.S)
    if not m1:
        raise AnalysisError(f'no DMA queue slot check at {q:#x}')
    slot, end = _u16(m1.group(1), 0) | 0xFF0000, _u16(m1.group(2), 0) | 0xFF0000
    upd = d.find(b'\x21\xc9' + m1.group(1), q, q + 0x80)          # move.l a1,(slot).w
    words = [_u16(d, i) for i in range(q, upd, 2)]
    size = 2 * words.count(0x32C0) + 4 * words.count(0x22C2)       # move.w d0/move.l d2,(a1)+
    m2 = re.search(rb'\x4b\xf9\x00\xc0\x00\x04\x43\xf8(..)', d, re.S)  # ProcessDMAQueue
    base = _u16(m2.group(1), 0) | 0xFF0000 if m2 else None
    loop = d[a:a + 0x50]
    cues = inv.dplc_frames(d, loc['dplc'])
    art_end = loc['art'] + 32 * max(t + n for f in cues for t, n in f)
    crossing = [i for i, f in enumerate(cues) for t, n in f
                if (loc['art'] + 32 * t) // BANK != (loc['art'] + 32 * (t + n) - 1) // BANK]
    others = dma_users(d, q, calls, skip={a + m.start()})
    return {
        'queue_routine': hx(q), 'process_routine': hx(m2.start()) if m2 else None,
        'other_users': [dict(o, site=hx(o['site']), dplc=hx(o['dplc']), art=hx(o['art']),
                             vram=None if o['vram'] is None else f"{o['vram']:04x}",
                             vram_candidates=[f'{v:04x}' for v in o['vram_candidates']])
                        for o in others],
        '_others': others,
        'buffer': hx(base), 'slot_pointer': hx(slot), 'buffer_end': hx(end),
        'entry_bytes': size, 'capacity': (end - base) // size if base and size else None,
        'callers': [hx(c) for c in calls.get(q, [])],
        'tiles_per_entry_max': 16 if b'\x02\x43\x00\xf0' in loop else None,
        'tile_index_bits': 12 if b'\x02\x41\x0f\xff' in loop else None,
        'max_entries_per_frame_now': max(len(f) for f in cues),
        'art_even': loc['art'] % 2 == 0,
        'art_banks': sorted({loc['art'] // BANK, (art_end - 1) // BANK}),
        'entries_crossing_128k': crossing,
    }


def vdp_setup(d: bytes) -> dict | None:
    for a in range(0, min(len(d), 0x10000) - 38, 2):
        if d[a] == 0x80 and all(d[a + 2 * i] == 0x80 + i for i in range(19)):
            r = [d[a + 2 * i + 1] for i in range(19)]
            return {'addr': hx(a), 'plane_a': (r[2] & 0x38) << 10, 'window': (r[3] & 0x3E) << 10,
                    'plane_b': (r[4] & 7) << 13, 'sprites': (r[5] & 0x7F) << 9,
                    'hscroll': (r[13] & 0x3F) << 10, 'h40': bool(r[12] & 0x81)}
    return None


def plc_lists(d: bytes) -> tuple[int | None, list[dict]]:
    m = ADDPLC.search(d)
    if not m:
        return None, []
    alc = _u32(m.group(1), 0)
    n = _u16(d, alc) // 2
    out = []
    for i in range(n):
        p = alc + _u16(d, alc + 2 * i)
        ents = []
        for k in range(_u16(d, p) + 1):
            art, vram = struct.unpack('>IH', d[p + 2 + 6 * k:p + 8 + 6 * k])
            ents.append({'art': art, 'vram': vram, 'tiles': _u16(d, art) & 0x7FFF})
        out.append({'id': i, 'name': PLC_NAMES[i] if n == len(PLC_NAMES) else None,
                    'addr': p, 'entries': ents})
    return alc, out


def nemesis_loads(d: bytes) -> tuple[int | None, list[dict]]:
    """Direct ``locVRAM x / lea (art).l,a0 / bsr NemDec`` loads."""
    hits = []
    for m in NEMLOAD.finditer(d):
        cmd = _u32(m.group(1), 0)
        if m.start() % 2 or cmd & 0xC000FFFC != 0x40000000:
            continue
        t = m.start() + 18 + _s16(m.group(3), 0) if m.group(3) else _u32(m.group(4), 0)
        hits.append({'site': m.start(), 'vram': (cmd >> 16) & 0x3FFF | (cmd & 3) << 14,
                     'art': _u32(m.group(2), 0), 'target': t})
    if not hits:
        return None, []
    targets = [h['target'] for h in hits]
    nemdec = max(set(targets), key=targets.count)
    out = [dict(h, tiles=_u16(d, h['art']) & 0x7FFF) for h in hits if h['target'] == nemdec]
    return nemdec, out


def vdp_writes(d: bytes, lo: int, hi: int) -> list[dict]:
    """VRAM write/DMA commands with an immediate address inside [lo, hi)."""
    out = []
    for m in VDPCMD.finditer(d):
        if m.start() % 2:
            continue
        cmd = _u32(m.group(1) or m.group(2), 0)
        if cmd >> 30 != 1 or cmd & 0x7C:
            continue
        addr = (cmd >> 16) & 0x3FFF | (cmd & 3) << 14
        if lo <= addr < hi:
            out.append({'site': hx(m.start()), 'vram': f'{addr:04x}', 'dma': bool(cmd & 0x80)})
    return out


def obgfx_values(d: bytes) -> dict[int, list[int]]:
    """``move.w #art_tile,obGfx(a0/a1)`` immediates -> sites."""
    out: dict[int, list[int]] = {}
    for m in OBGFX.finditer(d):
        if m.start() % 2 == 0:
            out.setdefault(_u16(m.group(1), 0), []).append(m.start())
    return out


def vram_budget(d, loc, vdp, plcs, loads, gfx, frame_tiles, dma_others=()) -> dict:
    buf = loc['vram']
    hard = vdp['sprites'] if vdp and vdp['sprites'] > buf else 0x10000
    users = []
    for o in dma_others:
        for lo in ([o['vram']] if o['vram'] is not None else o['vram_candidates']):
            hi = lo + 32 * (o['max_tiles'] or 0)
            if o['max_tiles'] and hi > buf and lo < hard:
                users.append({'dma': o['site'], 'vram': lo, 'end': hi, 'art': o['art'] or 0,
                              'tiles': o['max_tiles']})
    for L in plcs:
        for e in L['entries']:
            lo, hi = e['vram'], e['vram'] + 32 * e['tiles']
            if hi > buf and lo < hard:
                users.append({'plc': L['id'], 'plc_name': L['name'], 'vram': lo, 'end': hi,
                              'art': e['art'], 'tiles': e['tiles']})
    for h in loads:
        lo, hi = h['vram'], h['vram'] + 32 * h['tiles']
        if hi > buf and lo < hard:
            users.append({'direct': h['site'], 'vram': lo, 'end': hi, 'art': h['art'],
                          'tiles': h['tiles']})

    def limit(sel):
        c = [u['vram'] for u in users if sel(u)]
        return max(buf, min(c)) if c else hard
    lvl = limit(lambda u: 'direct' not in u and u.get('plc_name') not in NON_LEVEL_PLCS)
    ss = limit(lambda u: u.get('plc_name') == 'SpecialStage')
    tile0 = buf // 32
    shown = {f'{v:04x}': [hx(s) for s in sites] for v, sites in gfx.items()
             if tile0 < (v & 0x7FF) < hard // 32}
    fmt = lambda u: dict(u, vram=f"{u['vram']:04x}", end=f"{u['end']:04x}", art=hx(u['art']),
                         **{k: hx(u[k]) for k in ('direct', 'dma') if k in u})
    return {
        'buffer_vram': f'{buf:04x}', 'buffer_tile': f'{tile0:03x}',
        'sprite_table': f"{vdp['sprites']:04x}" if vdp else None,
        'hscroll': f"{vdp['hscroll']:04x}" if vdp else None,
        'plane_b': f"{vdp['plane_b']:04x}" if vdp else None,
        'hard_limit_tiles': (hard - buf) // 32,
        'level_limit_vram': f'{lvl:04x}', 'level_limit_tiles': (lvl - buf) // 32,
        'special_stage_limit_vram': f'{ss:04x}', 'special_stage_limit_tiles': (ss - buf) // 32,
        'users_above_buffer': [fmt(u) for u in sorted(users, key=lambda u: u['vram'])],
        'vdp_writes_in_buffer': vdp_writes(d, buf, hard),
        'obgfx_inside_buffer': shown,
        'max_frame_tiles_now': max(frame_tiles),
        'frames_over_level_limit': [i for i, t in enumerate(frame_tiles) if t > (lvl - buf) // 32],
    }


def _sim_offsets(d: bytes, start: int) -> list[int]:
    """Run the angle -> frame-offset arithmetic of one Sonic_Animate path."""
    offs = []
    for ang in (0, 2, 4, 6):
        r, pc = {0: ang, 1: 0}, start
        for _ in range(32):
            w = _u16(d, pc)
            if w == 0x1600:                       # move.b d0,d3: offset is ready
                break
            if w == 0x1200:
                r[1] = r[0]
            elif w == 0xE209:
                r[1] = (r[1] & 0xFF) >> 1
            elif w == 0xD001:
                r[0] = (r[0] + r[1]) & 0xFF
            elif w == 0xD000:
                r[0] = (r[0] * 2) & 0xFF
            elif w & 0xF100 == 0x7000:            # moveq
                r[(w >> 9) & 7] = w & 0xFF
            elif w == 0x6000:
                pc += 2 + _s16(d, pc + 2)
                continue
            elif w >> 8 == 0x60:
                pc += 2 + struct.unpack('b', bytes([w & 0xFF]))[0]
                continue
            elif w == 0x43F9:
                pc += 6
                continue
            else:
                raise AnalysisError(f'unexpected opcode {w:04x} at {pc:#x} in Sonic_Animate')
            pc += 2
        else:
            raise AnalysisError(f'no move.b d0,d3 after {start:#x}')
        offs.append(r[0])
    return offs


def scripts(d: bytes, base: int, max_frame: int) -> list[dict]:
    out = []
    for a in inv.offset_table(d, base, 128):
        frames, end, arg, k = [], None, None, 1
        while k < 256:
            b = d[a + k]
            if b > max_frame:
                end = {0xFF: 'loop', 0xFE: 'back', 0xFD: 'goto_anim'}.get(b, f'stop_{b:02x}')
                arg = d[a + k + 1] if b in (0xFE, 0xFD) else None
                break
            frames.append(b)
            k += 1
        out.append({'addr': a, 'duration': d[a], 'frames': frames, 'end': end, 'arg': arg})
    return out


def animation_rules(d: bytes, loc: dict, calls: dict, frame_tiles: list[int]) -> dict:
    m = inv.ANI.search(d)
    a = m.start()
    code = d[a:a + 0x200]
    max_frame, rule = 0x7F, 'bmi: frame ids $00-$7F (stock Sonic 1)'
    p = code.find(b'\x10\x31\x10\x01\x6b')                  # move.b 1(a1,d1.w),d0 ; bmi
    if p < 0:
        raise AnalysisError('Sonic_Animate frame read not found')
    t = p + 6 + struct.unpack('b', code[p + 5:p + 6])[0]
    if code[t:t + 3] == b'\x0c\x00\x00' and code[t + 4] == 0x6F:   # cmpi.b #x,d0 ; ble
        max_frame = code[t + 3]
        rule = f'bmi + cmpi.b #${max_frame:02X},d0/ble at {hx(a + t)}: frame ids $00-${max_frame:02X}'
    sc = scripts(d, loc['animations'], max_frame)
    by_addr = {s['addr']: i for i, s in enumerate(sc)}
    c = code.find(b'\x0c\x42\x06\x00')                      # cmpi.w #$600,d2
    leas = [(i, _u32(code, i + 2)) for i in range(0, len(code) - 6, 2) if _u16(code, i) == 0x43F9]
    run = [x for x in leas if x[0] < c][-1]
    walk = [x for x in leas if x[0] > c][0]
    bcc = c + 4
    run_start = a + bcc + 2 + struct.unpack('b', code[bcc + 1:bcc + 2])[0]
    walk_offs = _sim_offsets(d, a + walk[0] + 6)
    run_offs = _sim_offsets(d, run_start)
    wid, rid = by_addr.get(walk[1]), by_addr.get(run[1])
    reach = set()
    for i, s in enumerate(sc):
        offs = walk_offs if i == wid else run_offs if i == rid else [0]
        reach |= {f + o for f in s['frames'] for o in offs}
    n = len(frame_tiles)
    refs = []
    for r in loc['mapping_refs']:
        mm = re.search(rb'\x11\x7c\x00(.)\x00\x1c', d[r:r + 0x30], re.S)   # move.b #anim,obAnim
        anim = mm.group(1)[0] if mm else None
        fr = set(sc[anim]['frames']) if anim is not None and anim < len(sc) else set()
        if anim == wid:
            fr = {f + o for f in fr for o in walk_offs}
        elif anim == rid:
            fr = {f + o for f in fr for o in run_offs}
        refs.append({'site': hx(r), 'init_anim': anim,
                     'max_tiles': max((frame_tiles[f] for f in fr if f < n), default=None)})
    return {
        'routine': hx(a), 'callers': [hx(x) for x in calls.get(a, [])],
        'max_frame_id': max_frame, 'frame_rule': rule,
        'commands': {'ff': 'loop to frame 0', 'fe': 'back n frames', 'fd': 'goto anim n',
                     'other': f'${max_frame + 1:02X}-$FC stop (rts)'},
        'walk': {'anim': wid, 'script': hx(walk[1]), 'angle_offsets': walk_offs},
        'run': {'anim': rid, 'script': hx(run[1]), 'angle_offsets': run_offs,
                'speed_threshold': 0x600},
        'scripts': len(sc), 'frames': n,
        'reachable_frames': len(reach & set(range(n))),
        'unreachable_frames': sorted(set(range(n)) - reach),
        'out_of_range': sorted(f for f in reach if f >= n),
        'mapping_refs': refs,
        'script_list': [{'id': i, 'addr': hx(s['addr']), 'duration': s['duration'],
                         'frames': s['frames'], 'end': s['end'], 'arg': s['arg']}
                        for i, s in enumerate(sc)],
    }


def palette_line0(d: bytes, loc: dict, gfx: dict) -> dict:
    t = loc['pal_pointers']
    ref = d[loc['palette']:loc['palette'] + 32]
    ents = []
    for i in range(64):
        src, dst, ln = struct.unpack('>IHH', d[t + 8 * i:t + 8 * i + 8])
        if src >= len(d) or dst < 0xF000:
            break
        ents.append((i, src, dst, 4 * (ln + 1)))
    named = len(ents) == len(PAL_NAMES)
    out = []
    for i, src, dst, nbytes in ents:
        if not dst <= 0xFB00 < dst + nbytes:
            continue
        l0 = d[src + 0xFB00 - dst:src + 0xFB00 - dst + 32]
        diff = sum(l0[k:k + 2] != ref[k:k + 2] for k in range(0, 32, 2))
        out.append({'index': i, 'name': PAL_NAMES[i] if named else None, 'src': hx(src),
                    'dest': f'{dst:04x}', 'colours': nbytes // 2,
                    'line0_equals_pal_sonic': diff == 0, 'line0_colours_differing': diff})
    maps = inv.mapping_frames(d, loc['mappings'])
    line0 = sorted({v & 0x7FF for v in gfx if (v >> 13) & 3 == 0})
    return {'pal_pointers': hx(t), 'pal_sonic': hx(loc['palette']), 'entries': len(ents),
            'line0_writers': out,
            'player_piece_lines': sorted({p['pal'] for f in maps for p in f}),
            'other_line0_art_tiles': [f'{v:03x}' for v in line0 if v != loc['vram'] // 32]}


def pointer_sites(d: bytes, tables: dict) -> dict:
    out = {}
    for name, v in tables.items():
        pat, sites, i = struct.pack('>I', v), [], 0
        while (i := d.find(pat, i)) != -1:
            if i % 2 == 0:
                sites.append({'operand': hx(i), 'opcode': f'{_u16(d, i - 2):04x}'})
            i += 1
        out[name] = sites
    return out


def checksum_routine(d: bytes) -> int | None:
    a = d.find(bytes.fromhex('207c00000200'))          # movea.l #$200,a0
    while a != -1:
        if bytes.fromhex('227c000001a4') in d[a:a + 0x20]:  # movea.l #RomEndLoc,a1
            return a
        a = d.find(bytes.fromhex('207c00000200'), a + 2)
    return None


def free_tail(d: bytes) -> dict:
    i = len(d)
    while i > 0 and d[i - 1] == 0xFF:
        i -= 1
    i += i % 2
    return {'start': hx(i), 'bytes': len(d) - i,
            'banks': [hx(b) for b in range(i // BANK * BANK, len(d), BANK)]}


def sonic_art_users(d, plcs, loads, stock: bytes | None = None) -> list[dict]:
    """Sonic graphics outside the DPLC set; ``stock`` marks unchanged blobs."""
    out = _sonic_art(plcs, loads)
    ref = {}
    if stock is not None:
        ref = {u['key']: u for u in _sonic_art(plc_lists(stock)[1], nemesis_loads(stock)[1])}
    for u in out:
        s = ref.get(u.pop('key'))
        u['stock_art'] = hx(s['art']) if s else None
        u['stock_prefix_match'] = (None if s is None or stock is None else
                                   d[u['art']:u['art'] + 128] == stock[s['art']:s['art'] + 128])
        u['art'], u['vram'] = hx(u['art']), f"{u['vram']:04x}"
    return out


def _sonic_art(plcs, loads) -> list[dict]:
    out = []
    for L in plcs:
        for e in L['entries']:
            role = PLC_SONIC_ART.get((L['name'], e['vram']))
            if role:
                out.append({'role': role, 'via': f"PLC {L['id']:02x} {L['name']}", 'art': e['art'],
                            'vram': e['vram'], 'tiles': e['tiles'], 'key': ('plc', L['id'], e['vram'])})
    seq = sorted(loads, key=lambda h: h['site'])
    for k, h in enumerate(seq):
        prev = seq[k - 1] if k and h['site'] - seq[k - 1]['site'] <= 0x20 else None
        role = None
        if h['vram'] == 0x6000 and prev and prev['vram'] == 0x4000:
            role = 'Nem_TitleSonic (title screen Sonic)'
        elif h['vram'] == 0xA000 and prev and prev['vram'] == 0xB000:
            role = 'Nem_ContSonic (continue screen Sonic)'
        elif h['vram'] == 0xAA20:
            role = 'Nem_MiniSonic (continue screen counter)'
        if role:
            out.append({'role': role, 'via': f"direct NemDec at {hx(h['site'])}", 'art': h['art'],
                        'vram': h['vram'], 'tiles': h['tiles'], 'key': ('direct', role)})
    return out


# ---------------------------------------------------------------- driver --

def analyze(path, stock_path=None) -> dict:
    d, src = inv.read_rom(path)
    loc = inv.locate(d)
    cues = inv.dplc_frames(d, loc['dplc'])
    frame_tiles = [sum(n for _, n in f) for f in cues]
    calls = call_map(d)
    start, framevar = loader_start(d, loc)
    vdp = vdp_setup(d)
    alc, plcs = plc_lists(d)
    nemdec, loads = nemesis_loads(d)
    gfx = obgfx_values(d)
    stock = inv.read_rom(stock_path)[0] if stock_path else None
    rt = roundtrip(d, loc)
    dq = dma_queue(d, loc, calls)
    vb = vram_budget(d, loc, vdp, plcs, loads, gfx, frame_tiles, dq.pop('_others'))
    an = animation_rules(d, loc, calls, frame_tiles)
    pal = palette_line0(d, loc, gfx)
    ptr = pointer_sites(d, {'mappings': loc['mappings'], 'dplc': loc['dplc'], 'art': loc['art']})
    users = sonic_art_users(d, plcs, loads, stock)
    ck = checksum_routine(d)
    tail = free_tail(d)
    ss = [r for r in an['mapping_refs'] if r['max_tiles'] is not None
          and r['max_tiles'] <= vb['special_stage_limit_tiles']]
    rules = [
        f"DPLC buffer VRAM ${vb['buffer_vram']} (tile ${vb['buffer_tile']}): <= "
        f"{vb['level_limit_tiles']} tiles/frame in levels (first other user ${vb['level_limit_vram']}), "
        f"<= {vb['special_stage_limit_tiles']} for frames shown in the special stage "
        f"(PLC SpecialStage art at ${vb['special_stage_limit_vram']}), sprite table at "
        f"${vb['sprite_table']} is the hard stop ({vb['hard_limit_tiles']} tiles); now max "
        f"{vb['max_frame_tiles_now']}.",
        f"Each DPLC entry is one DMA-queue slot: <= {dq['tiles_per_entry_max']} tiles, "
        f"{dq['tile_index_bits']}-bit first tile (art <= 4096 tiles); queue {dq['buffer']} holds "
        f"{dq['capacity']} x {dq['entry_bytes']}-byte slots shared by {len(dq['callers'])} callers; "
        f"now max {dq['max_entries_per_frame_now']} entries/frame.",
        "Art must start on an even address and no DPLC entry may cross a 128 KiB bank "
        f"(now banks {dq['art_banks']}, crossings {len(dq['entries_crossing_128k'])}).",
        f"Frame ids: {an['frame_rule']}; $FF loop, $FE back n, $FD goto anim n. Keep all "
        f"{an['frames']} frame slots: walk script frames +{an['walk']['angle_offsets']} and run "
        f"+{an['run']['angle_offsets']} by slope angle.",
        f"Player pieces use palette line(s) {pal['player_piece_lines']}; line 0 is shared with "
        f"{len(pal['other_line0_art_tiles'])} other obGfx art bases (HUD, monitors, ...), so keep "
        "its colours or accept recolouring them. Line-0 copies of Pal_Sonic: "
        + ', '.join(e['name'] or str(e['index']) for e in pal['line0_writers'] if e['line0_equals_pal_sonic'])
        + '; separate line-0 variants: '
        + ', '.join(f"{e['name'] or e['index']}({e['line0_colours_differing']})"
                    for e in pal['line0_writers'] if not e['line0_equals_pal_sonic']) + '.',
        "Other DMA-queue users per frame: " + (', '.join(
            f"{o['site']} DPLC {o['dplc']} ({o['count_bytes']}-byte counts, {o['frames']} frames) "
            f"art {o['art']} VRAM "
            + (f"${o['vram']}" if o['vram'] else f"obj+${o['vram_field']:02X} = "
               + '/'.join('$' + v for v in o['vram_candidates']))
            + f" max {o['max_tiles']} tiles"
            for o in dq['other_users']) or 'none') + '.',
        "obGfx art tiles inside the buffer region: " + (', '.join(
            f"${k} at {v}" for k, v in vb['obgfx_inside_buffer'].items()) or 'none') + '.',
        "Relocation patch sites: " + ', '.join(f"{k} {len(v)}" for k, v in ptr.items()) + '.',
        f"Recompute the header checksum at $18E (boot check at {hx(ck)}).",
        f"Free space {tail['start']}-end ({tail['bytes']} bytes of $FF).",
        "A full swap must also cover: " + '; '.join(f"{u['role']} {u['art']} ({u['tiles']} tiles)"
                                                   for u in users) + '.',
    ]
    return {
        'engine': 'sonic1-md', 'rom_sha256': src['rom_sha256'], 'source': src,
        'tables': {k: hx(v) if isinstance(v, int) else v for k, v in loc.items()
                   if k != 'mapping_refs'},
        'roundtrip': rt,
        'functions': {'LoadSonicDynPLC': hx(start), 'v_sonframenum': hx(framevar),
                      'LoadSonicDynPLC_callers': [hx(x) for x in calls.get(start, [])],
                      'QueueDMATransfer': dq['queue_routine'], 'ProcessDMAQueue': dq['process_routine'],
                      'Sonic_Animate': an['routine'], 'NemDec': hx(nemdec), 'ArtLoadCues': hx(alc),
                      'VDPSetupArray': vdp['addr'] if vdp else None, 'ChecksumCheck': hx(ck)},
        'dma_queue': dq, 'vram': vb, 'animation': an, 'palette': pal,
        'pointer_sites': ptr, 'sonic_art_users': users,
        'special_stage_safe_refs': [r['site'] for r in ss],
        'checksum_ok': rt['checksum'] == rt['checksum_header'], 'free_space': tail,
        'plc_lists': [{'id': L['id'], 'name': L['name'], 'addr': hx(L['addr']),
                       'entries': [{'art': hx(e['art']), 'vram': f"{e['vram']:04x}", 'tiles': e['tiles']}
                                   for e in L['entries']]} for L in plcs],
        'nemesis_loads': [{'site': hx(h['site']), 'vram': f"{h['vram']:04x}", 'art': hx(h['art']),
                           'tiles': h['tiles']} for h in loads],
        'writer_rules': rules,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('rom')
    ap.add_argument('--out')
    ap.add_argument('--stock')
    a = ap.parse_args(argv)
    res = analyze(a.rom, a.stock)
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1))
    print(json.dumps({'roundtrip': {k: v['identical'] if isinstance(v, dict) else v
                                    for k, v in res['roundtrip'].items()},
                      'rules': res['writer_rules']}, indent=1))


if __name__ == '__main__':
    main()
