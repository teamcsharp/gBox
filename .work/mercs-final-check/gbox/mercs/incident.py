"""Bounded, read-only witnesses for damage investigation, never emulator checkpoints."""
from __future__ import annotations

import base64
import hashlib
import html
import json
import math
import time
import zlib

CONTEXT_MAX = 512 * 1024
CONTEXT_FIELDS = ('snapshot', 'plan', 'logic', 'preceding_history', 'map_at_observation_svg')


def pack_context(event):
    """Losslessly fit normal verbose observations into the durable event budget.

    RAM witnesses are already compressed. Repetitive path/map/snapshot JSON is compressed together only when an
    event would otherwise exceed the wire limit; identity, HP and raw witnesses remain directly readable.
    """
    fields = {key: event[key] for key in CONTEXT_FIELDS if key in event}
    data = json.dumps(fields, allow_nan=False, sort_keys=True, separators=(',', ':')).encode()
    if not fields or len(data) > CONTEXT_MAX:
        return event
    packed = {'format': 'zlib+base64-json/1', 'fields': list(fields), 'uncompressed_bytes': len(data),
              'sha256': hashlib.sha256(data).hexdigest(),
              'data_b64': base64.b64encode(zlib.compress(data, 1)).decode('ascii')}
    if len(json.dumps(packed, separators=(',', ':')).encode()) >= len(data):
        return event
    return {key: value for key, value in event.items() if key not in fields} | {'packed_context': packed}


def unpack_context(event):
    """Verify and expand only the allowlisted context, with a strict decompression allocation limit."""
    packed = event.get('packed_context')
    if packed is None:
        return event
    try:
        if not isinstance(packed, dict) or packed.get('format') != 'zlib+base64-json/1':
            raise ValueError('unknown packed context format')
        size = packed.get('uncompressed_bytes')
        if type(size) is not int or not 0 < size <= CONTEXT_MAX:
            raise ValueError('packed context exceeds decompression budget')
        decoder = zlib.decompressobj()
        data = decoder.decompress(base64.b64decode(packed['data_b64'], validate=True), CONTEXT_MAX + 1)
        if len(data) != size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError('invalid packed context length or stream')
        if hashlib.sha256(data).hexdigest() != packed.get('sha256'):
            raise ValueError('packed context SHA256 mismatch')
        def invalid_number(value):
            raise ValueError('nonfinite packed context number')
        values = json.loads(data, parse_constant=invalid_number)
        if (not isinstance(values, dict) or not values or set(values) != set(packed.get('fields') or ())
                or set(values) - set(CONTEXT_FIELDS) or set(values) & set(event)):
            raise ValueError('invalid packed context fields')
        return event | values
    except (KeyError, TypeError, ValueError, zlib.error) as exc:
        raise ValueError('invalid damage packed context: ' + str(exc)[:200]) from exc


def ram_witness(memory, title, snap):
    if title != 'BLUS30491':
        return {'state': 'unsupported', 'title': title}
    from .titles import re5_ps3 as R
    from .titles import re5_combat as C
    started = time.time()
    out = {'state': 'done', 'atomic': False, 'started_at': started, 'spans': [],
           'native_save_state': 'not captured: RPCS3 checkpoint operation reloads the game',
           'format': 'zlib+base64; SHA256 covers uncompressed bytes',
           'scope': 'at most 48 KiB of current player/action, nearest four enemies, and observed mines; not full RAM'}
    try:
        player = snap['player']['ptr']
        owner = R.u32(memory, R.S_PLAYER)
        if not R.ptr_ok(owner) or R.u32(memory, owner+0x28) != player or not R.ptr_ok(player):
            raise ValueError('player identity changed before RAM witness')
        spans = [('player', player, 0x3000)]
        action = R.u32(memory, player+C.P_ACTION_OBJ)
        if R.ptr_ok(action):
            spans.append(('action', action, 0x40))
        enemies = sorted(snap.get('enemies', ()), key=lambda e: math.dist(e['pos'], snap['player']['pos']))
        spans += [('enemy', e['ptr'], 0x1500) for e in enemies[:4] if R.ptr_ok(e.get('ptr', 0))]
        mines = snap.get('ground_mines') or {}
        spans += [('mine', int(ptr), 0x1E00) for ptr in list(mines)[:4] if R.ptr_ok(int(ptr))]
        used = 0
        for kind, address, size in spans:
            if used+size > 48*1024:
                out['truncated_to_budget'] = True
                out.setdefault('omitted_spans', []).append({'kind': kind, 'address': hex(address), 'size': size})
                continue
            stamp = time.time()
            data = memory.rd(address, size)
            if len(data) != size:
                raise ValueError(f'short {kind} read')
            used += size
            out['spans'].append({'kind': kind, 'address': hex(address), 'size': size, 'at': stamp,
                                 'sha256': hashlib.sha256(data).hexdigest(),
                                 'data_b64': base64.b64encode(zlib.compress(data, 1)).decode('ascii')})
        if R.u32(memory, R.S_PLAYER) != owner or R.u32(memory, owner+0x28) != player:
            raise ValueError('player identity changed during RAM witness')
    except Exception as exc:
        out.update(state='partial' if out['spans'] else 'failed', error=str(exc)[:240])
    out['finished_at'] = time.time()
    return out


def map_svg(snap, history, plan):
    """Static local map of observations; geometry boundaries are labelled as evidence."""
    p = (snap.get('player') or {}).get('pos')
    if not p:
        return None
    radius, scale = 2200., 0.12
    def xy(q):
        return 300-(q[0]-p[0])*scale, 300-(q[2]-p[2])*scale
    def point(q, color, radius=3):
        x, y = xy(q)
        return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius}" fill="{color}"/>'
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 630">',
             '<rect width="600" height="630" fill="#111827"/>']
    nav = snap.get('nav')
    drawn = 0
    if nav is not None:
        for index, tri in enumerate(nav.tris):
            if drawn >= 600:
                break
            if math.dist(nav.centre[index], p) > radius:
                continue
            linked = {edge for _, edge, _ in nav.links[index]}
            for edge in range(3):
                if drawn >= 600:
                    break
                if edge in linked:
                    continue
                a, b = xy(nav.points[tri[edge]]), xy(nav.points[tri[(edge+1)%3]])
                parts.append(f'<path d="M{a[0]:.1f},{a[1]:.1f} L{b[0]:.1f},{b[1]:.1f}" stroke="#64748b"/>')
                drawn += 1
    route = [row['pos'] for row in history if row.get('pos')]
    for positions, color in ((route, '#38bdf8'), (plan.get('route') or [], '#a78bfa')):
        coords = ' '.join(f'{xy(q)[0]:.1f},{xy(q)[1]:.1f}' for q in positions)
        if coords:
            parts.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="2"/>')
    for enemy in snap.get('enemies', ()):
        if enemy.get('pos') and (enemy.get('hp') or 0)>0:
            parts.append(point(enemy['pos'], '#f87171'))
    for bonus in snap.get('bonuses', ()):
        if bonus.get('pos'):
            parts.append(point(bonus['pos'], '#fbbf24', 5))
    for mine in (snap.get('ground_mines') or {}).values():
        parts.append(point(mine['pos'], '#fb923c', 4))
    parts += [point(p, '#4ade80', 6), '<text x="8" y="615" fill="white" font-size="11">',
              html.escape('HP-loss observation: cyan past path; purple plan; red enemies; orange mines. Navigation boundaries are not verified walls.'), '</text></svg>']
    return ''.join(parts)
