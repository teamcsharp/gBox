"""One RE6 bomb opportunity after an observed traversal and a grounded exit.

The native action names are present in build 061D2A06. Ladder transitions
were also observed in Requiem for War rounds e05026ba / 995e7303: the native
cSmVLadderEventCh_Climb ends in walk at the new floor height. A prompt,
button press, damage fall, or nearest-nav-triangle match is never evidence.
"""
from __future__ import annotations

import math

from .titles.re6_floor import floor_at

TRAVERSAL_ACTIONS = frozenset((
    'cSmVLadderEventCh_Climb',
    'cPlAction_pl_act_climb_action', 'cPlAction_pl_act_3m_front_jump',
    'cSmWindowEventPl_Dash', 'cSmWindowEventPl_Crack',
    'cSmCliffHangEventPl_Climb', 'cSmPlOnlyEventPl_Climb', 'cSmHoleEventPl_Fall',
))
GROUND_ACTIONS = frozenset('cPlAction_pl_act_' + name for name in (
    'wait', 'walk', 'walk_to_wait', 'run', 'dash', 'weapon_ready_begin',
    'weapon_ready_loop', 'weapon_ready_end', 'weapon_ready_move', 'weapon_fire'))
TRANSITION_ACTIONS = frozenset(('cPlAction_pl_act_land', 'cPlAction_pl_act_weapon_change'))
GROUND_ERROR_CM, LANDING_RADIUS_CM = 30., 200.
OBSERVATION_GAP_S, LANDING_TTL_S = 2., 1.5


def position(pos):
    return (isinstance(pos, (tuple, list)) and len(pos) == 3
            and all(isinstance(v, (int, float)) and math.isfinite(v) for v in pos))


def grounded(player, mesh):
    return (player.get('state') in (0, 2) and player.get('action') in GROUND_ACTIONS
            and type(player.get('equipped')) is int and 0 <= player['equipped'] < 7
            and floor_at(mesh, player.get('pos'), GROUND_ERROR_CM) is not None)


def at_landing(player, mesh, evidence):
    return (grounded(player, mesh) and position(evidence.get('landing_pos'))
            and math.dist(player['pos'], evidence['landing_pos']) <= LANDING_RADIUS_CM)


class Landing:
    """Track action entry/exit, then two distinct stable floor observations."""
    def __init__(self):
        self.owner, self.mesh, self.active, self.sample, self.pending = None, None, None, None, None
        self.last_seen, self.claimed = -math.inf, False

    def observe(self, owner, snap, stats, now, enabled):
        p, mesh = snap.get('player') or {}, snap.get('navmesh')
        valid = (enabled and bool(owner[0]) and all(type(v) is int for v in owner[1:])
                 and not stats.get('operator_control') and not stats.get('round_evidence_closed')
                 and stats.get('screen') in (None, 'playing') and (p.get('hp') or 0) > 0
                 and position(p.get('pos')) and mesh is not None)
        if (not valid or self.owner != owner or self.mesh is not mesh
                or not 0 <= now - self.last_seen <= OBSERVATION_GAP_S):
            self.__init__()
        self.owner, self.mesh, self.last_seen = owner, mesh, now
        if not valid:
            stats['mine_landing_ready'] = False
            return
        action = p.get('action')
        if action in TRAVERSAL_ACTIONS:
            if self.active is None:
                self.active = dict(entry_action=action, entry_at=now, entry_pos=list(p['pos']))
            self.active['last_traversal_at'] = now
            self.active.pop('first_exit_at', None)
            self.pending, self.sample, self.claimed = None, None, False
        elif self.active is not None:
            event = self.active
            event.setdefault('first_exit_at', now)
            if (now - event['entry_at'] > 30. or now - event['first_exit_at'] > OBSERVATION_GAP_S
                    or action not in GROUND_ACTIONS | TRANSITION_ACTIONS):
                self.active, self.sample = None, None
            elif grounded(p, mesh):
                distance = math.dist(event['entry_pos'], p['pos'])
                if not 50. <= distance <= 5000.:
                    self.sample = None
                elif self.sample is None or abs(p['pos'][1] - self.sample[1][1]) > 10.:
                    self.sample = now, tuple(p['pos']), snap
                elif now - self.sample[0] >= .1 and snap is not self.sample[2]:
                    self.pending = dict(event, landing_at=now, landing_pos=list(p['pos']),
                                        exit_action=action, displacement_cm=round(distance, 1))
                    self.active, self.sample, self.claimed = None, None, False
            else:
                self.sample = None
        if self.pending is not None and (not 0 <= now - self.pending['landing_at'] <= LANDING_TTL_S
                                         or not at_landing(p, mesh, self.pending)):
            self.pending = None
        stats['mine_landing_ready'] = self.pending is not None and not self.claimed
        if self.pending is not None:
            stats['mine_landing_evidence'] = self.pending

    def due(self):
        return self.pending is not None and not self.claimed

    def claim(self):
        self.claimed = True
