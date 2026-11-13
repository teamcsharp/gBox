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
        from .navigation_incidents import Monitor
        self.navigation = Monitor()
        self._nav_seen = set()
        self.inputs = deque(maxlen=4096)
        self.input_batches = self.input_events = self.input_tail_dropped = 0

    def input(self, now, events, receipt):
        """Every emitted input transition, independently of the snapshot sampling rate.

        Transport acceptance is not proof that the engine fired a shot or moved.
        A legacy sender's None result remains an unavailable acknowledgment.
        """
        while self.inputs and now - self.inputs[0]['t'] > 60:
            self.inputs.popleft()
        if len(self.inputs) == self.inputs.maxlen:
            self.input_tail_dropped += 1
        self.input_batches += 1
        self.input_events += len(events)
        refused = receipt is False or isinstance(receipt, dict) and (
            receipt.get('stopped') or receipt.get('held') or receipt.get('skipped') or receipt.get('sent') != len(events))
        state = 'refused_or_partial' if refused else 'accepted' if receipt is True or isinstance(receipt, dict) else 'no_receipt'
        self.inputs.append({'t': round(now, 3), 'events': safe(events), 'transport': state,
                            'receipt': {k: safe(receipt[k]) for k in ('sent', 'held', 'stopped', 'skipped') if k in receipt}
                            if isinstance(receipt, dict) else None})

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
        held_weapon = next((i.get('item') for i in snap.get('inventory') or () if i.get('hand')), None)
        row = {'t': round(now, 3), 'pos': self.point(p.get('pos')),
               'hp': safe(p.get('hp')), 'hp_max': safe(p.get('hp_max')),
               'player': safe(p.get('ptr')), 'heading': safe(p.get('rot', p.get('facing'))),
               'phase': safe(plan.get('phase', stats.get('phase'))), 'why': safe(plan.get('note')),
               'game_phase': safe((snap.get('game') or {}).get('phase', snap.get('mercenaries_phase'))),
               'in_control': safe((snap.get('game') or {}).get('in_control')),
               'prompt': safe(snap.get('prompt')), 'navigation': safe(plan.get('navigation')),
               'route_requires_prompt': safe(plan.get('route_requires_prompt')),
               'controls': safe(plan.get('controls')), 'goal': safe(plan.get('operator_goal')),
               'target': safe(target), 'route': [self.point(v) for v in (plan.get('route') or [])[:12]],
               'route_source': safe(plan.get('route_source')),
               'timer': safe(snap.get('timer')), 'kills': safe(snap.get('kills')),
               'weapon': safe(snap.get('equipped_id', snap.get('weapon_class', p.get('weapon_id', held_weapon)))),
               'aim': safe(snap.get('aim')), 'aim_plan': safe(plan.get('aim')),
               'laser': safe(snap.get('laser')), 'camera': safe(snap.get('camera', snap.get('aim_cam'))),
               'native_action': safe(p.get('action', p.get('motion'))), 'fire_cooldown_s': safe(p.get('fire_cooldown_s')),
               'throwables': safe(snap.get('throwables')),
               'diagnostics': {k: safe(stats[k]) for k in (
                   'aim_diag', 'aim_errdeg', 'laser_gate', 'sight_block_last', 'nav_status',
                   'target_feedback_target', 'target_feedback_yaw_deg', 'target_feedback_pitch_deg',
                   'target_feedback_gate', 'target_feedback_ram', 'target_feedback_block_why',
                   'target_feedback_writes', 'target_feedback_write_failures',
                   'shots', 'hits', 'aimbook_hits', 'aimbook_misses', 'heals', 'first_aid_last',
                   'bonuses_taken', 'bonus_approaches', 'bonus_unconfirmed', 'nav_stuck',
                   'fire_burst_goal', 'fire_burst_remaining', 'fire_burst_state', 'fire_burst_requests',
                   'native_fire_rearms_observed', 'fire_contact_verified', 'fire_while_correcting',
                   'throw_aim_last', 'throw_aim_observed', 'throw_aim_unresolved') if k in stats}}
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
        self.navigation.observe(row)
        for incident in self.navigation.changes:
            if incident['id'] in self._nav_seen:
                continue
            self._nav_seen.add(incident['id'])
            for kind in incident['kinds']:
                self.findings.append({'kind': kind, 'incident_id': incident['id'],
                                      **{k: incident[k] for k in ('from_t', 'to_t', 'travel_cm', 'goal_progress_cm',
                                          'turn_command_reversals', 'goal', 'cause')}})

    def snapshot(self):
        tail = list(self.tail)
        if tail:
            while self.inputs and tail[-1]['t'] - self.inputs[0]['t'] > 60:
                self.inputs.popleft()
        gaps = [b['t'] - a['t'] for a, b in zip(tail, tail[1:])]
        fields = ('pos', 'hp', 'controls', 'weapon', 'aim', 'aim_plan', 'route', 'camera', 'laser', 'native_action')
        present = {field: sum(r.get(field) is not None and r.get(field) != [] for r in tail) for field in fields}
        quality = {'tail_samples': len(tail), 'tail_observed_s': round(tail[-1]['t']-tail[0]['t'], 3) if tail else 0,
                   'tail_max_gap_s': round(max(gaps), 3) if gaps else None,
                   'tail_gaps_over_1s': sum(g > 1 for g in gaps), 'tail_field_samples': present,
                   'shooting_analysis': 'commands and observations only; projectile hits and obstruction need native witnesses',
                   'warnings': (['no input evidence'] if tail and not present['controls'] else []) +
                               (['sampling gaps exceed one second'] if any(g > 1 for g in gaps) else []) +
                               (['no samples'] if not tail else [])}
        return {'format': 'gbox.flight/1', 'units': 'cm', 'source_position_scale_to_cm': self.scale,
                'coordinate_order': 'x,y,z', 'tail_window_s': 60, 'sample_s': .2,
                'first': self.first, 'tail': tail, 'timeline': list(self.timeline), 'signal_quality': quality,
                'findings': list(self.findings), 'raw_aim_units': 'source reader; position fields alone normalized',
                'navigation_incidents': self.navigation.sequence,
                'navigation_active_incident': self.navigation.active['id'] if self.navigation.active else None,
                'timeline_dropped': self.timeline_dropped,
                'inputs': list(self.inputs), 'input_batches': self.input_batches, 'input_events': self.input_events,
                'input_tail_dropped': self.input_tail_dropped,
                'input_evidence': 'emitted transport commands; no claim of game-confirmed movement, shots or hits',
                'attribution': 'nearby enemies are context; damage source and obstruction are unknown unless witnessed'}
