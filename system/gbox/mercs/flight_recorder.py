"""Bounded decision evidence, independent of the run map's route sample limit.

Positions are normalized explicitly; missing observations remain unknown. A shot
counter is a bot command count, not proof that a projectile hit or cleared a wall.
"""
from collections import deque
import math


def safe(value, depth=0):
    if depth > 5:
        return None
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value[:240]
    if isinstance(value, dict):
        return {str(k)[:48]: safe(v, depth + 1) for k, v in list(value.items())[:32]}
    if isinstance(value, (list, tuple, set)):
        return [safe(v, depth + 1) for v in list(value)[:24]]
    return None


class FlightRecorder:
    def __init__(self, scale=1.0):
        self.scale = scale
        self.tail = deque(maxlen=302)
        self.timeline = []
        self.last = self.last_second = -math.inf
        self.timeline_dropped = 0
        self.first = None
        self.findings = []
        self._reported = {}

    def point(self, value):
        if not isinstance(value, (list, tuple)) or len(value) < 3:
            return None
        try:
            result = [round(float(x) * self.scale, 2) for x in value[:3]]
            return result if all(math.isfinite(x) for x in result) else None
        except (ValueError, TypeError):
            return None

    def observe(self, now, snap, plan, stats, *, force=False):
        if not force and now - self.last < .19:
            return
        p = snap.get('player') or {}
        plan = plan or {}
        target = plan.get('target') or {}
        row = {'t': round(now, 3), 'pos': self.point(p.get('pos')),
               'hp': safe(p.get('hp')), 'hp_max': safe(p.get('hp_max')),
               'player': safe(p.get('ptr')), 'heading': safe(p.get('rot', p.get('facing'))),
               'phase': safe(plan.get('phase', stats.get('phase'))), 'why': safe(plan.get('note')),
               'game_phase': safe((snap.get('game') or {}).get('phase')),
               'controls': safe(plan.get('controls')), 'goal': safe(plan.get('operator_goal')),
               'target': safe(target), 'route': [self.point(v) for v in (plan.get('route') or [])[:12]],
               'route_source': safe(plan.get('route_source')),
               'timer': safe(snap.get('timer')), 'kills': safe(snap.get('kills')),
               'weapon': safe(snap.get('equipped_id', snap.get('weapon_class'))),
               'aim': safe(snap.get('aim')), 'aim_plan': safe(plan.get('aim')),
               'diagnostics': {k: safe(stats[k]) for k in (
                   'aim_diag', 'aim_errdeg', 'laser_gate', 'sight_block_last', 'nav_status',
                   'shots', 'hits', 'aimbook_hits', 'aimbook_misses', 'heals', 'first_aid_last',
                   'bonuses_taken', 'bonus_approaches', 'bonus_unconfirmed', 'nav_stuck') if k in stats}}
        if isinstance(row['target'], dict) and 'pos' in row['target']:
            row['target']['pos'] = self.point(target.get('pos'))
        goal = plan.get('operator_goal')
        if isinstance(goal, dict) and isinstance(row['goal'], dict) and 'pos' in goal:
            row['goal']['pos'] = self.point(goal['pos'])
        enemies = [e for e in snap.get('enemies') or () if isinstance(e, dict)]
        if row['pos']:
            enemies = sorted(enemies, key=lambda e: math.dist(self.point(e.get('pos')) or [1e20]*3, row['pos']))
        row['nearby_enemies'] = [{'id': safe(e.get('ptr', e.get('slot'))), 'class': safe(e.get('class')),
                                 'hp': safe(e.get('hp')), 'pos': self.point(e.get('pos'))} for e in enemies[:8]]
        if self.first is None:
            self.first = row
        self.last = now
        if self.tail and self.tail[-1]['t'] == row['t']:
            self.tail[-1] = row
        else:
            self.tail.append(row)
        while self.tail and now - self.tail[0]['t'] > 60:
            self.tail.popleft()
        if now - self.last_second >= .99:
            self.last_second = now
            # Six hours is well beyond a Mercenaries attempt. Never silently
            # turn a bounded buffer into a claim of complete evidence.
            if len(self.timeline) < 21600:
                self.timeline.append(row)
            else:
                self.timeline_dropped += 1
                self.timeline[-1] = row
        self._diagnose(now)

    def _diagnose(self, now):
        rows = [r for r in self.tail if now - r['t'] <= 3.2]
        if len(rows) < 15 or rows[-1]['t'] - rows[0]['t'] < 2.8:
            return
        if any(b['t'] - a['t'] > .6 for a, b in zip(rows, rows[1:])):
            return
        nav = {'walk', 'locate', 'relocate', 'explore', 'route', 'approach', 'escape'}
        if any(r['pos'] is None or r['game_phase'] in ('grabbed', 'held', 'case', 'dead', 'intro')
               or r['phase'] not in nav for r in rows):
            return
        goal = rows[-1].get('goal') or {}
        destination = goal.get('pos') if isinstance(goal, dict) else None
        if not destination:
            destination = next((p for p in reversed(rows[-1]['route']) if p), None)
        if not destination:
            return
        if goal.get('id') and any((r.get('goal') or {}).get('id') != goal['id'] for r in rows):
            return
        distance = math.dist(rows[-1]['pos'], destination)
        travel = sum(math.dist(a['pos'], b['pos']) for a, b in zip(rows, rows[1:]))
        progress = math.dist(rows[0]['pos'], destination) - distance
        if distance < 75 or travel >= 30 or progress >= 20:
            return
        controls = [r.get('controls') or {} for r in rows]
        moving = sum(bool({'lup', 'ldown'} & set(c.get('keys') or [])) for c in controls)
        turning = [(-1 if 'lleft' in c.get('keys', []) else 1 if 'lright' in c.get('keys', []) else 0)
                   for c in controls]
        nonzero = [v for v in turning if v]
        reversals = sum(a != b for a, b in zip(nonzero, nonzero[1:]))
        kinds = []
        if moving >= .8 * len(rows):
            kinds.append('navigation_no_progress')
        if reversals >= 4:
            kinds.append('alternating_turn_commands_without_progress')
        for kind in kinds:
            if now - self._reported.get(kind, -math.inf) < 10 or len(self.findings) >= 4000:
                continue
            self._reported[kind] = now
            self.findings.append({'kind': kind, 'from_t': rows[0]['t'], 'to_t': rows[-1]['t'],
                                  'travel_cm': round(travel, 2), 'goal_progress_cm': round(progress, 2),
                                  'goal_distance_cm': round(distance, 2), 'turn_command_reversals': reversals,
                                  'goal': safe(goal), 'cause': 'unknown; inspect route, geometry and game state'})

    def snapshot(self):
        return {'format': 'gbox.flight/1', 'units': 'cm', 'source_position_scale_to_cm': self.scale,
                'coordinate_order': 'x,y,z', 'tail_window_s': 60, 'sample_s': .2,
                'first': self.first, 'tail': list(self.tail), 'timeline': list(self.timeline),
                'findings': list(self.findings), 'raw_aim_units': 'source reader; position fields alone normalized',
                'timeline_dropped': self.timeline_dropped,
                'attribution': 'nearby enemies are context; damage source and obstruction are unknown unless witnessed'}
