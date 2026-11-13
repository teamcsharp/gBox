"""Observed Switch traversal completion requests an existing native hand ring.

Routine numbers are entries in the verified native movement dispatch table,
not animation-byte guesses. This module never writes game memory or pad input.
"""
from __future__ import annotations

import math
import struct
import time

DISPATCH, TABLE, TABLE_GOT = 0x30D430, 0xB067C0, 0xB27D68
DISPATCH_BYTES = bytes.fromhex('08305a39480000351f1c0d791f301a39c94000d00854443929b546f9217968f820001fd6')
HANDLERS = (0x30D540,0x30D6E0,0x30D920,0x30DA40,0x30DE80,0x30DF70,0x30E170,
            0x30E2C0,0x30E3F0,0x30E520,0x30E860,0x31FA30,0x30E870,0,
            0x30EE80,0x30F370,0x30F380,0x310680,0,0x310A00,0x310C40)
TRAVERSALS = {7:'ledge_up',8:'ledge_down',12:'fence_window',14:'fall',16:'ladder',19:'jump_fall'}
GROUNDED = frozenset(range(7))
ROUTINE = 0x114
MAX_SAMPLE_S, MAX_GAP_S, MAX_EPISODE_S = .15, 1., 60.
LANDING_S, LANDING_DY_MM, MIN_TRAVEL_MM, EVENT_FRESH_S = .2, 150., 600., 5.


def identity(snap, stats):
    p = snap.get('player') or {}
    return [stats.get('round_evidence_id'), p.get('ptr'), p.get('generation', p.get('id'))]


def read(m, snap):
    """Current owned native movement handler, bounded to 150ms, or None."""
    from . import re4_switch as R
    started = time.monotonic()
    try:
        p, base = snap['player'], snap['module_base']
        player, generation = p['ptr'], p.get('generation', p.get('id'))
        if not R.ptr_ok(player) or not R.ptr_ok(base) or generation is None:
            return None
        if bytes(m.rd(base+DISPATCH, len(DISPATCH_BYTES))) != DISPATCH_BYTES:
            return None
        if R.u64(m, base+TABLE_GOT) != base+TABLE:
            return None
        table = struct.unpack('<21Q', m.rd(base+TABLE, 21*8))
        if table != tuple(base+h if h else 0 for h in HANDLERS):
            return None
        current = R.player_unit(m, base)
        game = R.game_state(m, base)
        if (not current or current['ptr'] != player or current['id'] != generation
                or not game or game.get('phase') not in ('playing','held')):
            return None
        if any(game.get(k) != (snap.get('game') or {}).get(k) for k in ('stage','mode')):
            return None
        routine = tuple(m.rd(player+ROUTINE, 4))
        if len(routine) != 4 or routine[0] != 0 or routine[1] not in TRAVERSALS and routine[1] not in GROUNDED:
            return None
        hp, _ = R.player_life(m, base)
        pos = struct.unpack('<3f', m.rd(player+R.U_POS, 12))
        if hp is None or hp <= 0 or not all(math.isfinite(v) and abs(v)<1e6 for v in pos):
            return None
        final = R.player_unit(m, base)
        after = R.game_state(m, base)
        if (not final or (final['ptr'],final['id'],final['vtable']) != (player,generation,current['vtable'])
                or tuple(m.rd(player+ROUTINE,4)) != routine or not after
                or any(after.get(k) != game.get(k) for k in ('phase','stage','mode'))
                or not 0 <= time.monotonic()-started <= MAX_SAMPLE_S):
            return None
        return {'routine':routine, 'handler':HANDLERS[routine[1]], 'pos':pos,
                'kind':TRAVERSALS.get(routine[1]), 'phase':game['phase'],
                'stage':game.get('stage'), 'mode':game.get('mode')}
    except (KeyError,TypeError,ValueError,IndexError,OSError,OverflowError,struct.error):
        return None


def observe(m, snap, stats, now):
    """Publish once after traversal exits to stable ordinary movement, in mm."""
    p, game = snap.get('player') or {}, snap.get('game') or {}
    owner = identity(snap,stats)
    old = stats.get('traversal_ring_event')
    if old and (old.get('owner') != owner or not 0 <= now-old.get('at',-math.inf) <= EVENT_FRESH_S):
        stats.pop('traversal_ring_event',None)
    if (not owner[0] or owner[1] is None or owner[2] is None or stats.get('operator_control')
            or stats.get('round_evidence_closed') or (p.get('hp') or 0)<=0
            or game.get('phase') not in ('playing','held')):
        stats.pop('_re4_traversal',None);stats.pop('traversal_ring_event',None)
        return None
    obs = read(m,snap)
    if obs is None:
        stats.pop('_re4_traversal',None)
        stats.pop('traversal_ring_event',None)
        stats['traversal_observation'] = {'state':'unavailable'}
        return None
    stats['traversal_observation'] = {'state':'native','routine':list(obs['routine']),
        'handler':obs['handler'],'kind':obs['kind'],'pos':list(obs['pos']),'units':'mm',
        'owner':owner,'at':now}
    state = stats.get('_re4_traversal')
    if state and (state['owner'] != owner or not 0 <= now-state['seen'] <= MAX_GAP_S
                  or now-state['entered_at'] > MAX_EPISODE_S
                  or state['stage'] != obs['stage'] or state['mode'] != obs['mode']):
        state = None;stats.pop('_re4_traversal',None)
    if obs['kind'] is not None:
        stats.pop('traversal_ring_event',None)
        if state is None or state.get('landing_at') is not None:
            state = {'owner':owner,'entered_at':now,'start':list(obs['pos']),'kind':obs['kind'],
                'routine':list(obs['routine']),'handler':obs['handler'],'stage':obs['stage'],'mode':obs['mode']}
            stats['_re4_traversal'] = state
        state['seen'] = now
        return None
    if state is None:
        return None
    if obs['phase'] != 'playing':
        stats.pop('_re4_traversal',None)
        return None
    state['seen'] = now
    if state.get('landing_at') is None or abs(obs['pos'][1]-state['landing_pos'][1]) > LANDING_DY_MM:
        state.update(landing_at=now,landing_pos=list(obs['pos']))
        return None
    if now-state['landing_at'] < LANDING_S:
        return None
    stats.pop('_re4_traversal',None)
    if math.dist(obs['pos'],state['start']) < MIN_TRAVEL_MM:
        stats['traversal_rejected'] = 'native exit without traversal displacement'
        return None
    sequence = int(stats.get('traversal_completions',0))+1
    event = {'id':sequence,'kind':'hand','trigger':'traversal','owner':owner,'at':now,
        'pos':list(obs['pos']),'units':'mm','traversal':state['kind'],
        'native_routine':state['routine'],'native_handler':state['handler'],
        'completed_routine':list(obs['routine']),'entered_at':state['entered_at'],
        'reason':'native '+state['kind']+' completed: hand-grenade defensive ring'}
    stats.update(traversal_completions=sequence,traversal_ring_event=event)
    return event


def claim_ring(snap, stats, now):
    """Consume before native submission: uncertain/partial rings never replay."""
    event = stats.get('traversal_ring_event')
    observation = stats.get('traversal_observation') or {}
    if (not isinstance(event,dict) or event.get('owner') != identity(snap,stats)
            or not 0 <= now-event.get('at',-math.inf) <= EVENT_FRESH_S
            or (snap.get('game') or {}).get('phase') != 'playing'
            or ((snap.get('player') or {}).get('hp') or 0)<=0
            or stats.get('operator_control') or stats.get('round_evidence_closed')
            or observation.get('state') != 'native' or observation.get('owner') != event['owner']
            or observation.get('kind') is not None
            # Engine tick time precedes its snapshot; allow that bounded lead.
            or not -MAX_SAMPLE_S <= now-observation.get('at',-math.inf) <= .5):
        return None
    key = [event['owner'],event['id']]
    if stats.get('_re4_traversal_ring_claim') == key:
        return None
    stats['_re4_traversal_ring_claim'] = key
    stats['traversal_ring_requested'] = int(stats.get('traversal_ring_requested',0))+1
    stats['traversal_ring_last_event'] = dict(event)
    return {'kind':'hand','fire':True,'count':5,'ripple_ms':0.,'traversal':True,
            'traversal_event':dict(event),'reason':event['reason']}
