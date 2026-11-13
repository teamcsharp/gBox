"""One post-landing mine event from RE5's named native traversal actions.

Observation only: no pad, weapon, memory mutation or placement here. Native
action registrations and landing predicates are recorded in re5-traversal.md.
"""
from __future__ import annotations

import math
import struct
import time

ACTION, ACTOR_OWNER, PLAYER_OWNER, STEP = 0x1B60, 0x10, 0x30, 0x28
COMPLETE, COMPLETE_MASK = 0x3F0C, 0x10000000
PREFIX = 'cPlAction_pl_act_'
TRAVERSALS = {PREFIX+name: kind for kind, names in {
    'drop': ('jump_down',),
    'jump': ('jump_broad_3m', 'jump_broad_4m', 'coop_jump_broad_6m_jump', 'coop_jump_up_4m_jump'),
    'vault': ('fence',),
    'ladder': ('ladder_v_climb',),
    'climb': ('climb_cliff', 'coop_climb_cliff', 'coop_climb_cliff_rescue'),
}.items() for name in names}
GROUNDED = frozenset(PREFIX+name for name in (
    'wait', 'relax', 'walk', 'walk_l', 'walk_r', 'run', 'back', 'turn_l', 'turn_r', 'turn_180',
    'weapon_ready_begin', 'weapon_ready_loop', 'weapon_ready_end', 'weapon_fire'))
MAX_SAMPLE_S, MAX_GAP_S, MAX_EPISODE_S = .15, 1., 60.
LANDING_S, LANDING_DY_CM, MIN_TRAVEL_CM, EVENT_FRESH_S = .2, 15., 60., 5.


def _name(m, obj):
    """Native MtDTI getter, including complete long action names (never a prefix)."""
    from . import re5_switch as R
    f = R.u64(m, R.u64(m, obj)+8*R.GET_DTI_SLOT)
    w0, w1, w2 = struct.unpack('<III', m.rd(f, 12))
    if (w0 & 0x9F00001F) != 0x90000000 or w2 != 0xD65F03C0:
        return None
    imm = ((w0 >> 29) & 3) | (((w0 >> 5) & 0x7FFFF) << 2)
    if imm & (1 << 20):
        imm -= 1 << 21
    page = (f & ~0xFFF)+(imm << 12)
    if (w1 & 0xFFC003FF) == 0x91000000:
        dti = page+((w1 >> 10) & 0xFFF)
    elif (w1 & 0xFFC003FF) == 0xF9400000:
        dti = R.u64(m, page+(((w1 >> 10) & 0xFFF) << 3))
    else:
        return None
    raw = bytes(m.rd(R.u64(m, dti+R.DTI_NAME), 96))
    if b'\0' not in raw:
        return None
    name = raw.split(b'\0')[0].decode('ascii')
    return name if name in TRAVERSALS or name in GROUNDED else None


def read(m, snap):
    """Fresh owned native action, or None; no motion IDs are interpreted."""
    from . import re5_switch as R
    started = time.monotonic()
    try:
        p = snap['player']; player, base = p['ptr'], snap['module_base']
        if not all(R.ptr_ok(v) for v in (player, base)):
            return None
        generation = R.u64(m, player+0x1A00)
        if generation != p.get('generation'):
            return None
        index = R.player_index(m)
        if index is None:
            return None
        sp, gs = R.u64(m, base+R.S_PLAYER), R.game_sys(m, base)
        coop = index != 0 or bool(getattr(m, 'mercs_coop', False))
        current = lambda: R.player_pointer(m, sp, index) if coop else R.u64(m, sp+R.P_FIRST)
        if not R.ptr_ok(gs) or current() != player \
                or struct.unpack('<i', m.rd(gs+R.GS_PHASE, 4))[0] != R.PHASE_PLAYING:
            return None
        a = R.u64(m, player+ACTION)
        if not R.ptr_ok(a):
            return None
        vt = R.u64(m, a)
        name = _name(m, a)
        if name is None or R.u64(m, a+ACTOR_OWNER) != player or R.u64(m, a+PLAYER_OWNER) != player:
            return None
        pos = struct.unpack('<3f', m.rd(player+R.P_POS, 12))
        hp = struct.unpack('<h', m.rd(player+R.P_HP, 2))[0]
        step = m.rd(a+STEP, 1)[0]
        complete = bool(struct.unpack('<I', m.rd(player+COMPLETE, 4))[0] & COMPLETE_MASK)
        if hp <= 0 or not all(math.isfinite(v) for v in pos):
            return None
        if (current() != player or R.u64(m, player+0x1A00) != generation
                or R.u64(m, base+R.S_PLAYER) != sp or R.game_sys(m, base) != gs
                or struct.unpack('<i', m.rd(gs+R.GS_PHASE, 4))[0] != R.PHASE_PLAYING
                or R.u64(m, player+ACTION) != a or R.u64(m, a) != vt
                or R.u64(m, a+ACTOR_OWNER) != player or R.u64(m, a+PLAYER_OWNER) != player
                or not 0 <= time.monotonic()-started <= MAX_SAMPLE_S):
            return None
        return {'name': name, 'action': a, 'step': step, 'complete': complete,
                'player': player, 'generation': generation, 'pos': pos}
    except (KeyError, TypeError, ValueError, IndexError, OSError, OverflowError, struct.error, UnicodeDecodeError):
        return None


def observe(m, snap, stats, now):
    """Publish a persistent lifetime-scoped event after native exit and landing.

    The consumer deduplicates id and admits only a fresh event for this owner.
    A completed native animation while still in its traversal action does not
    emit a mine. Death, grab/damage actions, lost reads and clock gaps cancel
    the episode instead of turning an interrupted jump into a landing.
    """
    from . import re5_switch as R
    p = snap.get('player') or {}
    owner = [stats.get('round_evidence_id'), p.get('ptr'), p.get('generation')]
    event = stats.get('traversal_mine_event')
    if event and (event.get('owner') != owner or not 0 <= now-event.get('at', -math.inf) <= EVENT_FRESH_S):
        stats.pop('traversal_mine_event', None)
    if (stats.get('operator_control') or (p.get('hp') or 0) <= 0
            or snap.get('mercenaries_phase') != R.PHASE_PLAYING
            or stats.get('screen') not in (None, 'playing') or stats.get('round_evidence_closed')
            or not owner[0] or owner[1] is None or owner[2] is None):
        stats.pop('_re5_traversal', None)
        stats.pop('traversal_mine_event', None)
        return None
    obs = read(m, snap)
    if obs is None:
        stats.pop('_re5_traversal', None)
        stats.pop('traversal_mine_event', None)
        stats['traversal_observation'] = {'state': 'unavailable'}
        return None
    stats['traversal_observation'] = {'state': 'native', 'name': obs['name'], 'step': obs['step'],
                                      'complete': obs['complete'], 'pos': list(obs['pos'])}
    state = stats.get('_re5_traversal')
    if state and (state.get('owner') != owner or not 0 <= now-state['seen'] <= MAX_GAP_S
                  or now-state['entered_at'] > MAX_EPISODE_S):
        state = None
        stats.pop('_re5_traversal', None)
    if obs['name'] in TRAVERSALS:
        # A pending placement belongs to the previous grounded exit. Entering
        # another traversal invalidates that request before native commitment.
        stats.pop('traversal_mine_event', None)
        if state is None or state.get('landing_at') is not None:
            state = {'owner': owner, 'entered_at': now, 'start': list(obs['pos']),
                     'name': obs['name'], 'kind': TRAVERSALS[obs['name']],
                     'action': obs['action'], 'complete_seen': False}
            stats['_re5_traversal'] = state
        state.update(seen=now, last=list(obs['pos']), complete_seen=state['complete_seen'] or obs['complete'])
        return stats.get('traversal_mine_event')
    if state is None:
        return stats.get('traversal_mine_event')
    # read() admits only explicit grounded action names here. The old native
    # action object must have relinquished ownership of this player's action.
    if obs['action'] == state['action']:
        stats.pop('_re5_traversal', None)
        return stats.get('traversal_mine_event')
    state['seen'] = now
    if state.get('landing_at') is None or abs(obs['pos'][1]-state['landing_pos'][1]) > LANDING_DY_CM:
        state.update(landing_at=now, landing_pos=list(obs['pos']), landing_samples=1)
        return stats.get('traversal_mine_event')
    state['landing_samples'] += 1
    if now-state['landing_at'] < LANDING_S or state['landing_samples'] < 2:
        return stats.get('traversal_mine_event')
    stats.pop('_re5_traversal', None)
    if math.dist(obs['pos'], state['start']) < MIN_TRAVEL_CM:
        stats['traversal_rejected'] = 'native exit without traversal displacement'
        return stats.get('traversal_mine_event')
    sequence = int(stats.get('traversal_completions', 0))+1
    stats['traversal_completions'] = sequence
    event = {'id': sequence, 'kind': 'traversal', 'at': now, 'owner': owner,
             'pos': list(obs['pos']), 'traversal': state['kind'], 'entered_at': state['entered_at'],
             'native_action': state['name'], 'completed_action': obs['name'],
             'completion_flag_seen': state['complete_seen'],
             'evidence': 'native traversal exited to owned grounded action; stable landing position'}
    stats['traversal_mine_event'] = event
    return event
