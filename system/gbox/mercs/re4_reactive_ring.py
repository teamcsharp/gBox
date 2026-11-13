"""RE4 damage/grab edges, separate from the periodic crowd-ring timer.

The caller supplies fresh RAM snapshots before health maintenance takes effect.
An event is consumed before the native request: a partial or uncertain ring is
never replayed. A held grab produces one event until gameplay resumes.
"""
from __future__ import annotations

import math


class Reactions:
    def __init__(self):
        self.identity = None
        self.hp = None
        self.grabbed = False

    def observe(self, snap: dict, stats: dict, now: float) -> dict | None:
        player = snap.get('player') or {}
        game = snap.get('game') or {}
        phase = game.get('phase')
        identity = (stats.get('round_evidence_id') or stats.get('rounds'),
                    player.get('ptr'), player.get('generation', player.get('id')))
        hp = player.get('hp')
        valid_hp = isinstance(hp, (int, float)) and not isinstance(hp, bool) and math.isfinite(hp)
        grabbed = phase == 'grabbed' or (game.get('flags') or {}).get('grabbed') is True
        previous_hp, previous_grab = self.hp, self.grabbed
        if identity != self.identity:
            previous_hp, previous_grab = None, False
        self.identity = identity
        self.hp = hp if valid_hp else None
        self.grabbed = grabbed
        if phase not in ('playing', 'grabbed') or not valid_hp or hp <= 0:
            return None
        if stats.get('operator_control') is True:
            return None
        if grabbed and not previous_grab:
            event = {'kind': 'flash', 'trigger': 'grab_qte', 'reason': 'grab/QTE started: flashbang ring'}
        elif previous_hp is not None and hp < previous_hp:
            event = {'kind': 'hand', 'trigger': 'damage', 'damage': previous_hp - hp,
                     'reason': f'health fell {previous_hp:g}->{hp:g}: grenade ring'}
        else:
            return None
        stats['reactive_ring_events'] = int(stats.get('reactive_ring_events', 0)) + 1
        stats['reactive_ring_event'] = {**event, 'at': now, 'player': player.get('ptr')}
        return event
