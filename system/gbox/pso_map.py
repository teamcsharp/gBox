"""PSO collision-surface extraction + operator map directives (pure, reloadable).

The party plays from RAM; this turns the verified native collision grid the
geometry provider already reads into a publishable 2D navigable surface (for the
Mercenaries Map viewer) and parses the operator's RTS map directives (GOTO /
PRESS / ATTACK / CLEAR). No vision, no memory access here - the controller feeds
state in and writes the files out. See system/docs/pso-map-directives.md.
"""
from __future__ import annotations

import math

from .pso_coop_nav import room_key, geometry_view

SWITCH_CLASSES = frozenset({'TLazerFenceSw', 'TObjDoorKey'})
GATE_CLASSES = frozenset({'TObjDoor', 'TObjLazerFenceNorm', 'TOBarrierEnergy01',
                          'TLazerFenceSw', 'TObjDoorKey'})


def _finite(*values):
    return all(type(v) in (int, float) and math.isfinite(v) for v in values)


def extract_surface(state, player, *, max_cells=20000):
    """A serializable 2D navigable surface for the player's CURRENT area, from the
    verified collision grid. None when geometry is not verified. Grid coords; a
    cell (cx,cz) is world ((cx+0.5)*size, (cz+0.5)*size)."""
    if state.get('geometry_verified') is not True or not _finite(player.get('x'), player.get('z')):
        return None
    # The walkable grid the player actually navigates is the Provider's per-player
    # projection (geometry_players[slot]); the top-level collision_grid is only set
    # by the optional campaign context reader. Prefer whichever is populated.
    grid = state.get('collision_grid') or geometry_view(state, player).get('collision_grid') or {}
    floor = grid.get('floor')
    size = grid.get('size')
    if not isinstance(floor, (list, tuple)) or not floor or type(size) not in (int, float) or size <= 0:
        return None
    cells = [[int(c[0]), int(c[1])] for c in floor[:max_cells]
             if isinstance(c, (list, tuple)) and len(c) == 2 and _finite(c[0], c[1])]
    if not cells:
        return None
    xs = [c[0] for c in cells]
    zs = [c[1] for c in cells]
    room = player.get('room')
    gates, warps = [], []
    for e in list(state.get('entities', ()))[:512]:
        cls = str(e.get('class', ''))
        if not _finite(e.get('x'), e.get('z')):
            continue
        if cls in GATE_CLASSES:
            gates.append({'class': cls, 'x': round(e['x'], 1), 'z': round(e['z'], 1),
                          'room': e.get('room'), 'kind': 'switch' if cls in SWITCH_CLASSES else 'gate',
                          'flag': (e.get('flag_index') if type(e.get('flag_index')) is int else None)})
        elif 'Warp' in cls or 'Teleport' in cls or 'GoalWarp' in cls:
            warps.append({'class': cls, 'x': round(e['x'], 1), 'z': round(e['z'], 1), 'room': e.get('room')})
    fingerprint, _ = room_key(state, player)
    players = {str(s): [round(p['x'], 1), round(p['z'], 1)]
               for s, p in state.get('players', {}).items() if _finite(p.get('x'), p.get('z'))}
    return {
        'version': 1, 'fingerprint': fingerprint,
        'episode': state.get('episode'), 'floor': state.get('floor'), 'room': room,
        'geometry_identity': state.get('geometry_identity'), 'size': float(size),
        'bounds': {'min_x': min(xs) * size, 'min_z': min(zs) * size,
                   'max_x': (max(xs) + 1) * size, 'max_z': (max(zs) + 1) * size},
        'cells': cells, 'cell_count': len(cells), 'gates': gates[:64], 'warps': warps[:16],
        'players': players,
    }


def surface_summary(surface):
    """A small record for the crystal/stats (not the full cell list)."""
    return {'fingerprint': surface['fingerprint'], 'episode': surface['episode'],
            'floor': surface['floor'], 'room': surface['room'], 'size': surface['size'],
            'cell_count': surface['cell_count'], 'bounds': surface['bounds'],
            'warps': len(surface['warps']), 'gates': len(surface['gates'])}


def parse_directive(raw):
    """Validate one operator map directive. Returns a normalized dict or None.

    A GOTO needs finite x,z. PRESS needs an int flag. ATTACK needs ptr or x,z.
    Optional episode/floor/room scope is carried for the controller to match
    against live state (a stale-scope directive must not act)."""
    if not isinstance(raw, dict):
        return None
    op = str(raw.get('op', '')).lower()
    if op not in ('goto', 'press', 'attack', 'clear'):
        return None
    out = {'op': op, 'id': str(raw.get('id', '')) or None}
    for k in ('episode', 'floor', 'room'):
        if type(raw.get(k)) is int:
            out[k] = raw[k]
    if op == 'goto':
        if not _finite(raw.get('x'), raw.get('z')):
            return None
        out['x'], out['z'] = float(raw['x']), float(raw['z'])
    elif op == 'press':
        if type(raw.get('flag')) is not int or not 0 <= raw['flag'] <= 255:
            return None
        out['flag'] = raw['flag']
    elif op == 'attack':
        if isinstance(raw.get('ptr'), str) and raw['ptr']:
            out['ptr'] = raw['ptr']
        elif _finite(raw.get('x'), raw.get('z')):
            out['x'], out['z'] = float(raw['x']), float(raw['z'])
        else:
            return None
    return out


def directive_in_scope(directive, state):
    """True when a parsed directive's episode/floor/room match live state (fields
    it omits are not constrained). A stale-area directive is thus ignored."""
    if not directive:
        return False
    for k, live in (('episode', state.get('episode')), ('floor', state.get('floor'))):
        if k in directive and directive[k] != live:
            return False
    if 'room' in directive:
        p1 = state.get('players', {}).get(1) or {}
        if directive['room'] != p1.get('room'):
            return False
    return True
