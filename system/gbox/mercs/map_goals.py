"""Live operator collection goals. No memory writes or controller ownership.

The tactical publisher hands replies back on the engine thread. Every goal is
scoped to one native round and resolved against fresh actors, never coordinates
alone. Missing actors are not automatically credited as pickups.
"""
import math
import uuid

TERMINAL = {'cancelled', 'expired', 'unavailable', 'completed', 'observed_removed'}
# Operator 2026-11-09: "If I click on an enemy on the map, I want the bot to navigate to that enemy and dispatch
# [it]. Anywhere I double click on the map, I want the bot navigating to that area. And then if I just leave it,
# they just take control and just go back to whatever they were doing." 'enemy': the live enemy in that slot until
# he is down or another unit has the slot. 'point': the spot until he is within ARRIVE of it, POINT_S at most.
KINDS = ('bonus', 'item', 'enemy', 'point')
ARRIVE, POINT_S = 200., 120.


class Goals:
    def __init__(self):
        self.reset()

    def reset(self):
        self.round = uuid.uuid4().hex
        self.goal = None
        self.previous = None
        self.missing_at = None

    def receive(self, value, now=0.):
        if not isinstance(value, dict) or value.get('round') != self.round:
            return
        if self.goal and self.goal['id'] == value.get('id'):
            return
        if value.get('kind') not in KINDS or type(value.get('entity_id')) is not int:
            return
        pos = value.get('pos')
        if not isinstance(pos, (list, tuple)) or len(pos) != 3 \
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in pos):
            return
        self.goal = {k: value.get(k) for k in ('id', 'round', 'stage', 'kind', 'entity_id', 'pos', 'label')}
        self.goal.update(state='cancelled' if value.get('state') == 'cancelled' else 'queued', reason='')
        self.previous = None
        self.missing_at = None
        self.received_at = now

    def defer(self, reason):
        if self.goal and self.goal['state'] not in TERMINAL:
            self.goal.update(state='deferred', reason=reason)

    def resolve(self, snap, now):
        goal = self.goal
        if not goal or goal['state'] in TERMINAL:
            return None
        if now-self.received_at > 300.:
            goal.update(state='expired', reason='Map goal expired after five minutes; choose it again')
            return None
        if goal['kind'] == 'point':
            at = (snap.get('player') or {}).get('pos')
            if now-self.received_at > POINT_S:
                goal.update(state='expired', reason='The marked spot was not reached in two minutes')
                return None
            if at and math.hypot(at[0]-goal['pos'][0], at[2]-goal['pos'][2]) <= ARRIVE:
                goal.update(state='completed', reason='He is at the marked spot; back to his own play')
                return None
            goal.update(state='active', reason='On his way to the marked spot by the map')
            return {'kind': 'point', 'pos': tuple(goal['pos'])}
        if goal['kind'] == 'enemy':
            row = next((e for e in snap.get('enemies') or () if e.get('slot', e.get('id')) == goal['entity_id']), None)
            unit = row.get('ptr') if row else None
            if row is not None and goal.setdefault('unit', unit) != unit:
                row = None                                  # another unit has the slot: the marked one is gone
            if row is None or (row.get('hp') or 0) <= 0:
                goal.update(state='completed', reason='The marked enemy is down; back to his own play')
                return None
            goal.update(state='active', reason='Going for the marked enemy ahead of everything else')
            return row
        rows = snap.get('bonuses' if goal['kind'] == 'bonus' else 'health_items') or []
        row = next((r for r in rows if r.get('ptr') == goal['entity_id']), None)
        if row and math.dist(row['pos'], goal['pos']) > 60.:
            goal.update(state='unavailable', reason='Native actor identity or position changed; choose it again')
            return None
        p = snap.get('player') or {}
        if row:
            self.missing_at = None
            self.previous = {'at': now, 'distance': math.dist(p['pos'], row['pos']),
                             'timer': snap.get('timer'), 'kills': snap.get('kills'),
                             'combo': snap.get('combo_timer'), 'kind': row.get('kind'),
                             'count': sum(w.get('rounds', 0) for w in snap.get('inventory', []) if w.get('id') == row.get('id'))}
            goal.update(state='active',reason='Following the requested native item through the normal route planner')
            return row
        self.missing_at = now if self.missing_at is None else self.missing_at
        if now-self.missing_at < .3:
            self.defer('Waiting for a stable native actor observation')
            return None
        previous = self.previous or {}
        confirmed = False
        if previous.get('distance', math.inf) <= 250. and 0 <= now-previous.get('at', -math.inf) <= 3.:
            if goal['kind'] == 'bonus' and previous.get('kind') == 'time':
                a, b = previous.get('timer'), snap.get('timer')
                confirmed = type(a) in (int, float) and type(b) in (int, float) \
                    and b-a >= 25. and snap.get('kills') == previous.get('kills')
            # Other pickups remain uncredited without their native reward proof.
        goal.update(state='completed' if confirmed else 'observed_removed',
                    reason='Native disappearance, proximity and timer gain agree' if confirmed else
                           'Actor left the native list; collection reward is not verified')
        return None

    def public(self):
        if not self.goal:
            return None
        return {k: self.goal[k] for k in ('id', 'label', 'kind', 'entity_id', 'state', 'reason')}
