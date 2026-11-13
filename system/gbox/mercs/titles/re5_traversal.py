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
# Main-relative addresses from the pinned 674c8828 ELF. These cOmEvent objects
# occupy the same current-action slot, but +0x18 owns the scene object and
# +0x30 is not a second player pointer. See re5-traversal.md for the dispatch.
OBJECT_EVENTS = {
    'cOmWindowEvent_dive': (0x1C222E0, 0x1D700A0, 0x1D6FF18, 0x38, (0, 1), 'vault'),
    'cOmLadderEvent_climb': (0x1BDF3C0, 0x1D64C00, 0x1D64928, 0x28, (0, 1, 2, 3), 'ladder'),
    'cOmLadderEventV_climb': (0x1BDF350, 0x1D64C38, 0x1D64960, 0x28, (0, 1, 2, 3, 10), 'ladder'),
}
TRAVERSALS.update({name: spec[-1] for name, spec in OBJECT_EVENTS.items()})
GROUNDED = frozenset(PREFIX+name for name in (
    'wait', 'relax', 'walk', 'walk_l', 'walk_r', 'run', 'back', 'turn_l', 'turn_r', 'turn_180',
    'weapon_ready_begin', 'weapon_ready_loop', 'weapon_ready_end', 'weapon_fire'))
MAX_SAMPLE_S, MAX_GAP_S, MAX_EPISODE_S = .15, 1., 60.
LANDING_S, LANDING_DY_CM, MIN_TRAVEL_CM, EVENT_FRESH_S = .2, 15., 60., 5.


def _rtti(m, obj):
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
    if not R.ptr_ok(dti):
        return None
    raw = bytes(m.rd(R.u64(m, dti+R.DTI_NAME), 96))
    if b'\0' not in raw:
        return None
    name = raw.split(b'\0')[0].decode('ascii')
    return dti, name


def _scene(m, pointer, base, expected_dti):
    """Bounded native inheritance and unit-lifetime witness for a cOmEvent."""
    from . import re5_switch as R
    if not R.ptr_ok(pointer):
        return None
    vt, born = R.u64(m, pointer), R.u64(m, pointer+0x1A00)
    phase = struct.unpack('<I', m.rd(pointer+0x10, 4))[0] & 7
    rtti = _rtti(m, pointer)
    if rtti is None or phase not in (1, 2) or not 0 < born <= 0xFFFFFFFF:
        return None
    dti, name = rtti
    chain, current = [], dti
    for _ in range(8):
        if not R.ptr_ok(current) or current in chain:
            return None
        chain.append(current)
        if current == base+expected_dti:
            return {'ptr': pointer, 'generation': born, 'vtable': vt, 'dti': dti,
                    'name': name, 'phase': phase, 'dti_chain': chain}
        current = R.u64(m, current+0x20)
    return None


def _object_state(m, a, name, player, base, vt):
    from . import re5_switch as R
    evt_vt, evt_dti, scene_dti, step_off, phases, _ = OBJECT_EVENTS[name]
    if vt != base+evt_vt or _rtti(m, a) != (base+evt_dti, name):
        return None
    scene_ptr = R.u64(m, a+0x18)
    if scene_ptr == player:
        return None
    scene = _scene(m, scene_ptr, base, scene_dti)
    status = struct.unpack('<I', m.rd(a+0x2C, 4))[0]
    actor_type = struct.unpack('<I', m.rd(a+0x34, 4))[0]
    step = struct.unpack('<I', m.rd(a+step_off, 4))[0] if step_off == 0x38 else m.rd(a+step_off, 1)[0]
    if (scene is None or status not in (0, 1, 2) or step not in phases
            or actor_type not in ((0, 1) if name == 'cOmWindowEvent_dive' else (0, 1, 2))):
        return None
    animation_end = bool(m.rd(player+0x8FA, 1)[0] & 4)
    complete = (step == 1 and animation_end if name == 'cOmWindowEvent_dive' else
                step == 3 and animation_end if name == 'cOmLadderEvent_climb' else
                step in (3, 10) or (step == 2 and animation_end))
    return {'scene': scene, 'step': step, 'status': status, 'complete': complete, 'actor_type': actor_type}


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
        rtti = _rtti(m, a)
        name = rtti[1] if rtti is not None else None
        if name not in TRAVERSALS and name not in GROUNDED:
            return None
        if R.u64(m, a+ACTOR_OWNER) != player:
            return None
        object_state = None
        if name in OBJECT_EVENTS:
            object_state = _object_state(m, a, name, player, base, vt)
            if object_state is None:
                return None
        elif R.u64(m, a+PLAYER_OWNER) != player:
            return None
        pos = struct.unpack('<3f', m.rd(player+R.P_POS, 12))
        hp = struct.unpack('<h', m.rd(player+R.P_HP, 2))[0]
        step = object_state['step'] if object_state else m.rd(a+STEP, 1)[0]
        complete = object_state['complete'] if object_state else bool(
            struct.unpack('<I', m.rd(player+COMPLETE, 4))[0] & COMPLETE_MASK)
        if hp <= 0 or not all(math.isfinite(v) for v in pos):
            return None
        if (current() != player or R.u64(m, player+0x1A00) != generation
                or R.u64(m, base+R.S_PLAYER) != sp or R.game_sys(m, base) != gs
                or struct.unpack('<i', m.rd(gs+R.GS_PHASE, 4))[0] != R.PHASE_PLAYING
                or R.u64(m, player+ACTION) != a or R.u64(m, a) != vt
                or R.u64(m, a+ACTOR_OWNER) != player or _rtti(m, a) != rtti
                or (object_state is None and R.u64(m, a+PLAYER_OWNER) != player)
                or (object_state is not None and _object_state(m, a, name, player, base, vt) != object_state)
                or not 0 <= time.monotonic()-started <= MAX_SAMPLE_S):
            return None
        return {'name': name, 'action': a, 'step': step, 'complete': complete,
                'player': player, 'generation': generation, 'pos': pos,
                'action_vtable': vt, 'sampled_at': started,
                'layout': 'om_event' if object_state else 'cpl_action',
                'scene': object_state['scene'] if object_state else None,
                'status': object_state['status'] if object_state else None}
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
        stats['traversal_observation'] = {'state': 'unavailable', 'active': False, 'at': now, 'owner': owner}
        return None
    obs = read(m, snap)
    if obs is None:
        stats.pop('_re5_traversal', None)
        stats.pop('traversal_mine_event', None)
        stats['traversal_observation'] = {'state': 'unavailable', 'active': False, 'at': now, 'owner': owner}
        return None
    stats['traversal_observation'] = {
        'state': 'native', 'active': obs['name'] in TRAVERSALS, 'owner': owner, 'at': now,
        'name': obs['name'], 'step': obs['step'], 'complete': obs['complete'], 'pos': list(obs['pos']),
        **{key: obs.get(key) for key in ('action', 'action_vtable', 'sampled_at', 'layout', 'scene', 'status')},
    }
    state = stats.get('_re5_traversal')
    if state and (state.get('owner') != owner or not 0 <= now-state['seen'] <= MAX_GAP_S
                  or now-state['entered_at'] > MAX_EPISODE_S):
        state = None
        stats.pop('_re5_traversal', None)
    if obs['name'] in TRAVERSALS:
        # A pending placement belongs to the previous grounded exit. Entering
        # another traversal invalidates that request before native commitment.
        stats.pop('traversal_mine_event', None)
        identity = (obs['action'], obs['name'], obs.get('scene'))
        if state is None or state.get('landing_at') is not None or state.get('identity') != identity:
            state = {'owner': owner, 'entered_at': now, 'start': list(obs['pos']),
                     'name': obs['name'], 'kind': TRAVERSALS[obs['name']],
                     'action': obs['action'], 'identity': identity, 'complete_seen': False,
                     'scene': obs.get('scene')}
            stats['_re5_traversal'] = state
        state.update(seen=now, last=list(obs['pos']), complete_seen=state['complete_seen'] or obs['complete'])
        return stats.get('traversal_mine_event')
    if state is None:
        return stats.get('traversal_mine_event')
    # cOmEvent completion is not the cPlAction completion bit. Require a
    # witnessed terminal native phase before interpreting its exit as success.
    if state['name'] in OBJECT_EVENTS and not state['complete_seen']:
        stats.pop('_re5_traversal', None)
        stats['traversal_rejected'] = 'object traversal exited without native completion witness'
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
             'scene': state.get('scene'),
             'completion_flag_seen': state['complete_seen'],
             'evidence': 'native traversal exited to owned grounded action; stable landing position'}
    stats['traversal_mine_event'] = event
    return event
