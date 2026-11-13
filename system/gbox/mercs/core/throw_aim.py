"""Moving-target throw plans and conservatively attributed landing feedback.

Only one newly observed, owned native projectile can acknowledge a request.
Ambiguous rings and disappearing units never become successful throws or hits.
"""
import json
import math
from pathlib import Path


def point(value):
    return (tuple(float(v) for v in value) if isinstance(value, (tuple, list)) and len(value) == 3
            and all(isinstance(v, (int, float)) and math.isfinite(v) for v in value) else None)


def identity(row):
    return row.get('unit', row.get('ptr')), row.get('generation')


class ThrowAim:
    def __init__(self, stats, directory=None):
        self.stats, self.motion, self.pending, self.cells = stats, {}, [], {}
        self.key = None
        self.path = Path(directory) / 'throw_aim.json' if directory else None
        if self.path:
            try:
                data = json.loads(self.path.read_text(encoding='utf-8'))
                if data.get('version') == 1 and isinstance(data.get('cells'), dict):
                    self.cells = data['cells']
            except (OSError, ValueError, TypeError):
                pass

    @staticmethod
    def cell(kind, origin, target):
        dist = math.hypot(target[0] - origin[0], target[2] - origin[2])
        return f'{kind}:{int(dist // 500)}:{int(round((target[1] - origin[1]) / 100))}'

    def observe(self, snap, now):
        p = snap.get('player') or {}
        key = (self.stats.get('round_evidence_id'), p.get('ptr'), p.get('generation'))
        if self.key != key:
            self.key, self.motion, self.pending = key, {}, []
        for e in snap.get('enemies') or ():
            pos = point(e.get('pos'))
            if pos is None or (e.get('hp') or 0) <= 0:
                continue
            ident = identity(e)
            old = self.motion.get(ident)
            velocity = (0., 0., 0.)
            if old and .01 <= now - old[0] <= .5:
                dt = now - old[0]
                raw = tuple((pos[k] - old[1][k]) / dt for k in range(3))
                if math.hypot(raw[0], raw[2]) <= 600 and abs(raw[1]) <= 150:
                    velocity = raw
            self.motion[ident] = (now, pos, velocity)
        self.motion = {k: v for k, v in self.motion.items() if now - v[0] < 2}
        units = snap.get('throwables')
        # Freeze ambiguity for this observation. Removing the first pending
        # request must not make the second request's attribution look unique.
        unbound = {}
        for rec in self.pending:
            if rec['unit'] is None and now - rec['at'] <= 6:
                unbound[rec['kind']] = unbound.get(rec['kind'], 0) + 1
        for rec in list(self.pending):
            if now - rec['at'] > 6:
                self._finish(rec, 'unresolved')
                continue
            if units is None:
                continue
            if rec['unit'] is None:
                candidates = [u for u in units if u.get('kind') == rec['kind'] and identity(u) not in rec['existing']
                              and point(u.get('pos')) and math.dist(u['pos'], rec['origin']) < 400]
                peers = unbound.get(rec['kind'], 0)
                if len(candidates) > 1 or peers > 1:
                    self._finish(rec, 'ambiguous_projectiles')
                    continue
                if len(candidates) == 1 and now - rec['at'] <= 1.2:
                    rec['unit'] = identity(candidates[0])
                    self.stats['throw_aim_observed'] = self.stats.get('throw_aim_observed', 0) + 1
            unit = next((u for u in units if identity(u) == rec['unit']), None)
            if not unit or not point(unit.get('pos')):
                continue
            if unit.get('action') not in ('cWpAction_wp_act_setting', 'cWpAction_wp_act_bomb'):
                continue
            actual = tuple(unit['pos'])
            rec['actual'] = actual
            rec['landing_error_cm'] = round(math.hypot(actual[0] - rec['target'][0], actual[2] - rec['target'][2]), 1)
            rec['flight_s'] = round(now - rec['at'], 3)
            # Unrelated shots can hurt these same enemies; never label this a hit.
            live = [e for e in snap.get('enemies') or () if (e.get('hp') or 0) > 0 and point(e.get('pos'))]
            rec['nearest_enemy_cm'] = round(min((math.dist(actual, e['pos']) for e in live), default=1e9), 1)
            if rec['aligned'] and unit.get('action') == 'cWpAction_wp_act_setting':
                dx, dz = rec['target'][0] - rec['origin'][0], rec['target'][2] - rec['origin'][2]
                dist = max(1, math.hypot(dx, dz))
                ex, ez = rec['target'][0] - actual[0], rec['target'][2] - actual[2]
                cell = self.cells.setdefault(rec['cell'], {'n': 0, 'forward': 0., 'side': 0., 'lead': .35})
                cell['n'] += 1
                for name, error in (('forward', (ex * dx + ez * dz) / dist), ('side', (ex * dz - ez * dx) / dist)):
                    cell[name] = max(-100., min(100., float(cell.get(name, 0)) + .15 * error))
                cell['lead'] = max(.1, min(1.2, .8 * float(cell.get('lead', .35)) + .2 * (now - rec['at'])))
                rec['learned'] = True
                self.save()
            self._finish(rec, 'settled' if unit.get('action') == 'cWpAction_wp_act_setting' else 'blast_observed')

    def plan(self, kind, origin, enemies, now):
        rows = [e for e in enemies if point(e.get('pos')) and (e.get('hp') or 0) > 0]
        if not rows:
            return None
        centre = tuple(sum(e['pos'][k] for e in rows) / len(rows) for k in range(3))
        key = self.cell(kind, origin, centre)
        cell = self.cells.get(key) or {}
        try:
            lead = max(.1, min(1.2, float(cell.get('lead', .35))))
            forward = max(-100., min(100., float(cell.get('forward', 0))))
            side = max(-100., min(100., float(cell.get('side', 0))))
        except (ValueError, TypeError):
            lead, forward, side = .35, 0., 0.
        predicted = []
        for e in rows:
            sample = self.motion.get(identity(e))
            velocity = sample[2] if sample and now - sample[0] <= .3 else (0., 0., 0.)
            predicted.append(tuple(e['pos'][k] + max(-200., min(200., velocity[k] * lead)) if k != 1 else e['pos'][1]
                                   for k in range(3)))
        target = tuple(sum(pos[k] for pos in predicted) / len(predicted) for k in range(3))
        dx, dz = target[0] - origin[0], target[2] - origin[2]
        dist = max(1, math.hypot(dx, dz))
        aim = (target[0] + (forward * dx + side * dz) / dist, target[1],
               target[2] + (forward * dz - side * dx) / dist)
        return {'target': target, 'aim': aim, 'cell': key, 'targets': [identity(e) for e in rows]}

    def request(self, kind, origin, plan, now, units=(), aligned=False):
        self.pending.append({'kind': kind, 'origin': tuple(origin), 'target': tuple(plan['target']),
                             'aim': tuple(plan['aim']), 'cell': plan['cell'], 'targets': plan['targets'],
                             'at': now, 'existing': {identity(u) for u in units or ()}, 'unit': None,
                             'aligned': bool(aligned), 'learned': False})
        if len(self.pending) > 16:
            self._finish(self.pending[0], 'queue_limit')

    def _finish(self, rec, state):
        self.pending.remove(rec)
        report = {k: v for k, v in rec.items() if k != 'existing'} | {'state': state, 'damage_attribution': 'unknown'}
        self.stats['throw_aim_last'] = report
        history = self.stats.setdefault('throw_aim_history', [])
        history.append(report)
        del history[:-64]
        if state not in ('settled', 'blast_observed'):
            self.stats['throw_aim_unresolved'] = self.stats.get('throw_aim_unresolved', 0) + 1

    def save(self):
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps({'version': 1, 'cells': self.cells}), encoding='utf-8')
            tmp.replace(self.path)
        except OSError as exc:
            self.stats['throw_aim_save_error'] = str(exc)[:160]
