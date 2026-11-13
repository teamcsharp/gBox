"""RE5 hit/grab edges shared by the asynchronous flash and mine controllers.

The baseline and event are serializable round evidence. Two observers may read
the same snapshot without producing two events; neither owns controller input.
"""
from __future__ import annotations

import math

EVENT_MAX_AGE_S = 3.0


def identity(snap, stats):
    p = snap.get('player') or {}
    return [stats.get('round_evidence_id'), p.get('ptr'), p.get('generation')]


def observe_event(snap, stats, now):
    """Publish a new edge, then return the latest event for this live player."""
    from .titles import re5_switch as R, re5_switch_prompt as P
    p, prompt = snap.get('player') or {}, snap.get('prompt') or {}
    owner, hp = identity(snap, stats), p.get('hp')
    valid_hp = type(hp) in (int, float) and math.isfinite(hp)
    valid_owner = bool(owner[0]) and all(type(v) is int for v in owner[1:])
    grabbed = (p.get('motion') in R.MOTION_HELD or prompt.get('label') == P.LABEL_BREAK_FREE
               or prompt.get('kind') == P.KIND_ENEMY and prompt.get('mode') in (3, 4, 5, 6, 7, 8, 9))
    playing = (snap.get('mercenaries_phase') == R.PHASE_PLAYING
               and stats.get('screen') in (None, 'playing') and not stats.get('round_evidence_closed'))
    active = playing and valid_owner and valid_hp and hp > 0 and not stats.get('operator_control')
    previous = stats.get('_re5_reactive_observation') or {}
    same = previous.get('owner') == owner and previous.get('active') is True
    old_hp = previous.get('hp') if same else None
    old_grab = previous.get('grabbed') if same else grabbed
    # A known live grab at the first observation is still a real QTE event.
    if previous.get('owner') != owner and active:
        old_grab = False
    stats['_re5_reactive_observation'] = {'owner': owner, 'hp': hp if valid_hp else None,
        'grabbed': grabbed, 'active': active, 'at': now}
    if not active:
        return None
    damage = old_hp - hp if type(old_hp) in (int, float) and hp < old_hp else 0
    if grabbed and not old_grab or damage > 0:
        sequence = int(stats.get('re5_reaction_sequence') or 0) + 1
        event = {'id': sequence, 'owner': owner, 'kind': 'qte' if grabbed and not old_grab else 'hit',
                 'at': now, 'hp_before': old_hp, 'hp_after': hp, 'damage': damage,
                 'motion': p.get('motion'), 'prompt_label': prompt.get('label')}
        stats.update(re5_reaction_sequence=sequence, automine_event=event,
                     reactive_ring_events=sequence, reactive_ring_event=dict(event))
    event = stats.get('automine_event')
    return event if isinstance(event, dict) and event.get('owner') == owner else None


class Reactions:
    def __init__(self):
        self.consumed = None

    def observe(self, snap, stats, now):
        event = observe_event(snap, stats, now)
        if event is None or (tuple(event['owner']), event['id']) == self.consumed:
            return None
        if not 0 <= now - event['at'] <= EVENT_MAX_AGE_S:
            self.consume(event, stats, 'expired before native admission')
            return None
        return event

    def consume(self, event, stats, state):
        self.consumed = (tuple(event['owner']), event['id'])
        stats['reactive_ring_last_event'] = {**event, 'state': state}

    @staticmethod
    def decision(event):
        why = ('grab/QTE started' if event['kind'] == 'qte'
               else f"health fell {event['hp_before']:g}->{event['hp_after']:g}")
        return {'kind': 'flash', 'fire': True, 'flash_ok': True, 'reactive': True,
                'reactive_event': dict(event), 'ripple_ms': 0.0,
                'reason': why + ': native flashbang ring while combat continues'}
