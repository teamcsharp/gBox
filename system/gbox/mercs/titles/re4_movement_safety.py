"""Final RE4 movement admission and measured wall-pressure recovery, in mm.

The outer bonus-goal decorator can bypass the combat tick's wall checks. This
gate sees the final tank-control command, including late recovery rewrites.
It never supplies a speculative backstep or turns a failed route into a line.
"""
from __future__ import annotations

import math

MOVE_S, MOVE_MM, BLOCK_S = 1.2, 180., 6.
PROBE_MM, NEAR_MM, TURN_TOL = 1200., 350., math.radians(14)
MOVE_KEYS = frozenset(('lup', 'ldown', 'b', 'lleft', 'lright'))


def _wrap(a):
    return (a+math.pi) % (2*math.pi)-math.pi


def _flat(a, b):
    return math.hypot(a[0]-b[0], a[2]-b[2])


def _floor_mesh(w):
    return (w.mesh is not None and callable(getattr(w.mesh, 'floor_y', None))
            and callable(getattr(w.mesh, 'floor_segment', None)))


def _native(w):
    """Only an owned, fresh observation of a verified native traversal."""
    from . import re4_traversal as T
    p, fact = w.p or {}, w.stats.get('traversal_observation') or {}
    if not isinstance(fact, dict):
        return False
    owner = T.identity(w.snap, w.stats)
    routine = fact.get('routine') or ()
    if (not all(v is not None for v in owner) or not isinstance(routine, (list, tuple))
            or not all(isinstance(v, int) for v in routine)
            or not isinstance(fact.get('at'), (int, float))):
        return False
    return (fact.get('state') == 'native' and fact.get('owner') == owner
            and len(routine) == 4 and routine[0] == 0 and routine[1] in T.TRAVERSALS
            and fact.get('kind') == T.TRAVERSALS[routine[1]]
            and fact.get('handler') == T.HANDLERS[routine[1]]
            and -.15 <= w.now-fact.get('at', -math.inf) <= .5
            and isinstance(fact.get('pos'), (list, tuple)) and len(fact['pos']) == 3
            and all(isinstance(v, (int, float)) and math.isfinite(v) for v in fact['pos'])
            and math.dist(p['pos'], fact['pos']) <= 600.)


def clear(w, pos, yaw, distance=PROBE_MM):
    """Actual held direction requires continuous floor and SAT body clearance."""
    from . import re4_room_map
    x, z = pos[0]+distance*math.sin(yaw), pos[2]+distance*math.cos(yaw)
    y = pos[1]
    if _floor_mesh(w):
        # Uphill stairs may rise more than find()'s usual 610mm tolerance
        # across the probe. Resolve the actual endpoint floor, then require
        # a continuous connected floor segment (never a jump to another deck).
        y = w.mesh.floor_y(x, z, pos[1], slack=1500.)
        if y is None or not w.mesh.floor_segment(pos, (x, y, z)):
            return False
    rm = re4_room_map.for_snap(w.snap)
    if rm is not None:
        if y is None or rm.walk_block(pos, (x, y, z), end_r=0.) is not None:
            return False
    return _floor_mesh(w) or rm is not None


def guard(w, act):
    """Return the final action with only unsafe movement replaced or removed."""
    if not isinstance(act, dict):
        return act
    pos, p, hold = w._pos(), w.p or {}, set(act.get('hold') or ())
    if pos is None or not all(math.isfinite(v) for v in pos):
        return act
    game = w.snap.get('game') or {}
    owner = (w.stats.get('round_evidence_id'), p.get('ptr'), p.get('generation', p.get('id')),
             getattr(w.mesh, 'sig', None))
    st = getattr(w, '_final_walk', None)
    if (not st or st['owner'] != owner or not 0 <= w.now-st['at'] <= 1.):
        st = w._final_walk = {'owner': owner, 'at': w.now, 'last': None, 'press': None,
                              'blocked': None, 'recovery': None}
    st['at'] = w.now
    # In RE4 the gun changes the stick's meaning. QTE/menu/native traversal
    # controls also belong to their native sequence, not ordinary floor walking.
    if ('zl' in hold or 'l' in hold or (game and not game.get('in_control'))
            or w.stats.get('operator_control') or (p.get('hp') or 0) <= 0 or _native(w)):
        st.update(last=None, press=None, recovery=None)
        return act
    yaw = p.get('rot', p.get('facing'))
    if not isinstance(yaw, (int, float)) or not math.isfinite(yaw):
        return dict(act, hold=hold-{'lup', 'ldown', 'b'}) if hold & {'lup', 'ldown'} else act
    old = st['last']
    if old is not None and old['moving']:
        press = st['press']
        if (press is None or _flat(pos, press['pos']) >= MOVE_MM
                or abs(_wrap(old['heading']-press['heading'])) > math.radians(30)):
            st['press'] = {'pos': pos, 'at': w.now, 'heading': old['heading']}
        elif w.now-press['at'] >= MOVE_S:
            st['blocked'] = {'pos': pos, 'heading': press['heading'], 'until': w.now+BLOCK_S}
            st.update(press=None, recovery=None)
            w.stats['walk_stalled_headings'] = w.stats.get('walk_stalled_headings', 0)+1
            w.stats['walk_failure'] = {'reason': 'sent movement without actual progress', 'units': 'mm',
                'owner': list(owner), 'at': w.now, 'from': list(press['pos']), 'pos': list(pos),
                'net_mm': round(_flat(pos, press['pos']), 1), 'seconds': round(w.now-press['at'], 2),
                'heading': press['heading'], 'held': old['held'], 'nav_status': w.stats.get('nav_status'),
                'route_point': list(w.wp[:2]) if w.wp else None}
    else:
        st['press'] = None
    block = st['blocked']
    if block and (w.now >= block['until'] or _flat(pos, block['pos']) > 800.):
        st['blocked'] = block = None

    def supported(h, distance=PROBE_MM):
        return (not block or abs(_wrap(h-block['heading'])) > math.radians(40)) and clear(w, pos, h, distance)

    move = 'lup' in hold or 'ldown' in hold
    backward = 'ldown' in hold and 'lup' not in hold
    travel_yaw = _wrap(yaw+math.pi) if backward else yaw
    recovery = st['recovery']
    if recovery and (w.now > recovery['until'] or _flat(pos, recovery['from']) > 600.):
        st['recovery'] = recovery = None
    if not move and (act.get('tap') or hold & {'y', 'a', 'zr', 'r'}):
        # A pickup, door pulse or combat action owns this tick. A previous
        # recovery must not add walking to a deliberately stationary action.
        st.update(last=None, press=None, recovery=None)
        return act
    # A route point can shorten the probe, but cannot override a failed test of
    # the direction actually held. The next tick rechecks from the new feet.
    probe = PROBE_MM
    if w.wp is not None and w.wp[2] == w.now and not backward:
        probe = min(probe, max(NEAR_MM, math.hypot(w.wp[0]-pos[0], w.wp[1]-pos[2])))
    from . import re4_room_map
    unmapped = not _floor_mesh(w) and re4_room_map.for_snap(w.snap) is None
    if (recovery is None and move and not ('lup' in hold and 'ldown' in hold)
            and ((unmapped and block is None) or supported(travel_yaw, probe))):
        st['last'] = {'moving': True, 'heading': travel_yaw, 'held': sorted(hold)}
        return act
    if not move and recovery is None:
        st['last'] = {'moving': False}
        return act
    if recovery is None:
        # Choose once, then turn in place until the observed body heading is
        # aligned. Holding forward during a 45-degree correction still hits
        # the original wall; a blind 180/backstep can step off a platform.
        angles = (45, -45, 90, -90, 135, -135, 180)
        for degrees in angles:
            h = _wrap(yaw+math.radians(degrees))
            if supported(h):
                recovery = st['recovery'] = {'heading': h, 'until': w.now+3., 'from': pos}
                break
        w.stats['walk_final_vetoes'] = w.stats.get('walk_final_vetoes', 0)+1
    out = hold-MOVE_KEYS
    if recovery is not None:
        err = _wrap(recovery['heading']-yaw)
        if abs(err) > TURN_TOL:
            out.add(w.turn_pos if err > 0 else w.turn_neg)
        elif supported(yaw):
            out.add('lup')
        else:
            st['recovery'] = None
    moving = 'lup' in out
    st['last'] = {'moving': moving, 'heading': yaw, 'held': sorted(out)}
    w.stats['walk_final_guard'] = 'turning toward proved floor' if recovery and not moving else (
        'moving onto proved floor' if moving else 'translation refused; no proved escape')
    return dict(act, hold=out)
