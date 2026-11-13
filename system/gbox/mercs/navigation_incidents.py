"""Navigation failure episodes and durable triage reports; never inferred wall geometry."""
from collections import deque
from copy import deepcopy
import json
import math
from pathlib import Path
import threading

NAV_PHASES = frozenset({'walk', 'locate', 'relocate', 'explore', 'route', 'approach', 'escape',
                        'bonus_run', 'gather_time', 'break_for_time', 'roam', 'retreat'})
BUSY_PHASES = frozenset({'grabbed', 'held', 'case', 'dead', 'intro', 'results'})
_WRITE_LOCK = threading.Lock()


def guard_started(bot, source, player, now, *, anchor, effort_s, threshold_s,
                  progress_limit_cm, commands, goal=None, route=()):
    """Retain the title guard's measured stall before recovery erases its intent.

    This is final-pad displacement evidence, not native collision attribution.
    Short title recoveries often finish before the generic three-second monitor.
    """
    from .flight_recorder import safe
    old = bot.stats.get('navigation_obstruction_context') or {}
    points, prompt = [], False
    for point in list(route or ())[:12]:
        approach = getattr(point, 'approach', None)
        if approach is not None:
            points.append(list(approach))
            prompt = True
        points.append(list(point))
    bot.stats['navigation_obstruction_context'] = safe({
        'source': source, 'sequence': old.get('sequence', 0)+1,
        'round_id': bot.stats.get('round_evidence_id'),
        'player': player.get('ptr'), 'player_generation': player.get('generation', player.get('id')),
        'detected_at': now, 'from_t': now-effort_s, 'updated_at': now,
        'position_cm': player.get('pos'), 'anchor_cm': anchor,
        'effort_s': effort_s, 'threshold_s': threshold_s, 'progress_limit_cm': progress_limit_cm,
        'commands': list(commands), 'command_source': 'title_guard_final_pad_feedback',
        'goal': goal, 'route': points[:12], 'route_requires_prompt': prompt,
        'phase': getattr(bot, 'doing', None), 'reason': getattr(bot, 'why', None),
        'outcome': 'open', 'recovery_position_cm': player.get('pos')})


def guard_finished(bot, player, now, outcome):
    witness = bot.stats.get('navigation_obstruction_context')
    if isinstance(witness, dict) and witness.get('outcome') == 'open':
        witness.update(outcome=outcome, updated_at=now,
                       recovery_position_cm=list(player['pos']) if player and player.get('pos') else None)


def waypoint(row):
    route = [p for p in row.get('route') or () if p]
    if route:
        return route[0], 'active_waypoint_distance'
    goal = row.get('goal') or {}
    target = row.get('target') or {}
    pos = goal.get('pos') if isinstance(goal, dict) else None
    if not pos and isinstance(target, dict) and target.get('kind') in ('bonus', 'waypoint'):
        pos = target.get('pos')
    return pos, 'euclidean_goal_distance' if pos else 'unavailable'


def movement(row):
    controls = row.get('controls') or {}
    return set(controls.get('keys', controls.get('hold', ())) or ())


def final_goal(row):
    goal = row.get('goal') or {}
    if isinstance(goal, dict) and goal.get('id') is not None:
        # route is truncated in the recorder. Only its separately captured full
        # endpoint can substitute for a goal position.
        return goal.get('pos') or row.get('route_endpoint'), goal['id']
    target = row.get('target') or {}
    if isinstance(target, dict) and target.get('kind') in ('bonus', 'waypoint'):
        return target.get('pos'), target.get('id')
    return None, None


def waypoint_churn(rows):
    """Repeated A/B route heads toward one final goal, with no arrival evidence."""
    dest, key = final_goal(rows[-1])
    if dest is None or key is None:
        return None
    clusters, sequence = [], []
    owner = rows[-1].get('player'), rows[-1].get('player_generation')
    for r in rows:
        end, identity = final_goal(r)
        head, _ = waypoint(r)
        if (identity != key or end is None or math.dist(end, dest) > 50 or head is None
                or math.dist(r['pos'], head) < 75
                or (r.get('player'), r.get('player_generation')) != owner):
            return None
        index = next((i for i, p in enumerate(clusters) if math.dist(head, p) <= 50), None)
        if index is None:
            index = len(clusters)
            clusters.append(head)
        if not sequence or sequence[-1] != index:
            sequence.append(index)
    repeated = any(a == c and b == d and a != b for a,b,c,d in zip(
        sequence, sequence[1:], sequence[2:], sequence[3:]))
    # A stair ascent or a legitimate detour is movement, not a wall diagnosis.
    if not repeated or math.dist(rows[0]['pos'], rows[-1]['pos']) >= 75 \
            or max(r['pos'][1] for r in rows)-min(r['pos'][1] for r in rows) >= 30:
        return None
    return dest, len(sequence)-1, key


class Monitor:
    """One report per episode, including a second episode soon after recovery."""
    def __init__(self):
        self.window = deque(maxlen=80)
        self.active = None
        self.changes = []
        self.sequence = 0
        self.last_emit = -math.inf
        self.recovery_since = None
        self.guard_seen = None

    def _guard(self, row):
        witness = row.get('navigation_obstruction')
        if not isinstance(witness, dict) or witness.get('source') not in ('re5_wall_guard', 're6_wall_guard'):
            return False
        if (witness.get('player'), witness.get('player_generation')) != \
                (row.get('player'), row.get('player_generation')):
            return False
        key = tuple(witness.get(k) for k in ('source', 'player', 'player_generation', 'round_id', 'sequence', 'detected_at'))
        if key != self.guard_seen:
            pos, anchor = witness.get('position_cm'), witness.get('anchor_cm')
            effort, threshold = witness.get('effort_s'), witness.get('threshold_s')
            limit, at = witness.get('progress_limit_cm'), witness.get('detected_at')
            numbers = (effort, threshold, limit, at, witness.get('from_t'))
            if (not all(type(v) in (int, float) and math.isfinite(v) for v in numbers)
                    or not 0 < threshold <= effort <= 3 or not 0 <= row['t']-at <= 2
                    or not pos or not anchor or len(pos) != 3 or len(anchor) != 3
                    or not all(type(v) in (int, float) and math.isfinite(v) for v in pos+anchor)
                    or not 0 < limit <= 100 or math.hypot(pos[0]-anchor[0], pos[2]-anchor[2]) >= limit
                    or not set(witness.get('commands') or ()) & {'lup', 'ldown', 'lleft', 'lright'}):
                return False
            before = list(self.window)
            self.close(row['t'], 'title_guard_recovery_started')
            self.guard_seen = key
            self.sequence += 1
            route, goal = witness.get('route') or [], witness.get('goal')
            dest = route[0] if route else goal.get('pos') if isinstance(goal, dict) else None
            self.active = {
                'id': self.sequence, 'state': 'open', 'outcome': 'unresolved',
                'kinds': ['navigation_guard_no_progress'], 'from_t': witness['from_t'],
                'to_t': row['t'], 'detected_at': at, 'player': row.get('player'),
                'player_generation': row.get('player_generation'), 'position_cm': pos,
                'waypoint': dest, 'goal': goal, 'distance_metric': 'active_waypoint_distance' if route
                    else 'euclidean_goal_distance' if dest else 'unavailable',
                'distance_at_open_cm': math.dist(pos, dest) if dest else None,
                'goal_progress_cm': math.dist(anchor, dest)-math.dist(pos, dest) if dest else None,
                'travel_cm': None, 'net_displacement_cm': round(math.dist(anchor, pos), 2),
                'movement_command_coverage': None, 'turn_command_reversals': None,
                'before': before+[row], 'collision_confirmed': None,
                'cause': 'unknown; title guard observed commanded movement without sufficient displacement',
                'analysis_state': 'needs_triage', 'learning_applied': False,
                'driver_witness': deepcopy(witness), 'evidence_warnings': []}
            self.window.append(row)
            self.emit(row['t'])
        elif not self.active or 'driver_witness' not in self.active:
            return False
        else:
            self.window.append(row)
            self.active['driver_witness'] = deepcopy(witness)
        if witness.get('outcome') != 'open':
            self.close(row['t'], witness.get('outcome') or 'guard_ended')
        elif row['t']-self.last_emit >= 1:
            self.emit(row['t'])
        return True

    def emit(self, now):
        if self.active:
            self.active['to_t'] = now
            self.active['duration_s'] = round(now-self.active['from_t'], 3)
            self.active['after'] = list(self.window)[-30:]
            self.changes.append(deepcopy(self.active))
            self.last_emit = now

    def close(self, now, outcome):
        if self.active:
            self.active['state'] = 'closed'
            self.active['outcome'] = outcome
            self.emit(now)
            self.active = None
        self.recovery_since = None
        self.window.clear()

    def observe(self, row):
        now = row['t']
        if self._guard(row):
            return
        previous = self.window[-1] if self.window else None
        if previous and not 0 < now-previous['t'] <= .6:
            self.close(now, 'telemetry_gap')
        if (row.get('pos') is None or row.get('game_phase') in BUSY_PHASES
                or row.get('phase') not in NAV_PHASES or row.get('in_control') is False):
            self.close(now, 'navigation_interrupted')
            return
        dest, metric = waypoint(row)
        if self.active and self.active.get('waypoint_switches'):
            dest, key = final_goal(row)
            if key != self.active.get('final_goal_id'):
                self.close(now, 'goal_or_player_changed')
        if self.active:
            old = self.active['waypoint']
            changed = (dest is None) != (old is None) or (dest is not None and old is not None and math.dist(dest, old) > 50)
            if changed or (row.get('player'), row.get('player_generation')) != \
                    (self.active['player'], self.active['player_generation']):
                self.close(now, 'goal_or_player_changed')
        self.window.append(row)
        if self.active:
            distance = math.dist(row['pos'], dest) if dest is not None else None
            progress = self.active['distance_at_open_cm']-distance if distance is not None else None
            restored = (distance < 75 or progress >= 100) if distance is not None else \
                math.dist(row['pos'], self.active['position_cm']) >= 100
            if restored:
                if self.recovery_since is None:
                    self.recovery_since = now
                if now-self.recovery_since >= .8:
                    self.close(now, 'movement_restored_goal_unknown' if distance is None else
                               'goal_reached' if distance < 75 else 'progress_restored')
                    return
            else:
                self.recovery_since = None
            self.active['latest_progress_cm'] = round(progress, 2) if progress is not None else None
            if now-self.last_emit >= 5:
                self.emit(now)
            return
        rows = [r for r in self.window if now-r['t'] <= 3.2]
        if len(rows) < 5 or rows[-1]['t']-rows[0]['t'] < 2.8:
            return
        # A real detour can move away from the final goal. Measure the active
        # waypoint, and reject a window spanning a changed route/goal.
        churn = None
        if any((waypoint(r)[0] is None) != (dest is None) or
               (dest is not None and math.dist(waypoint(r)[0], dest) > 50) for r in rows):
            churn = waypoint_churn(rows)
            if churn is None:
                return
            dest, switches, final_id = churn
            metric = 'stable_final_goal_distance'
        duration = rows[-1]['t']-rows[0]['t']
        coverage = sum((b['t']-a['t']) for a,b in zip(rows, rows[1:])
                       if movement(a) & {'lup', 'ldown', 'lleft', 'lright'}) / duration
        distance = math.dist(rows[-1]['pos'], dest) if dest is not None else None
        progress = math.dist(rows[0]['pos'], dest)-distance if dest is not None else None
        travel = sum(math.dist(a['pos'], b['pos']) for a,b in zip(rows, rows[1:]))
        net = math.dist(rows[0]['pos'], rows[-1]['pos'])
        turns = [(-1 if 'lleft' in movement(r) else 1 if 'lright' in movement(r) else 0) for r in rows]
        turns = [t for t in turns if t]
        reversals = sum(a != b for a,b in zip(turns, turns[1:]))
        if (distance is not None and (distance < 75 or progress >= 20)) or coverage < .8:
            return
        kinds = []
        if churn:
            kinds.append('navigation_waypoint_churn_without_progress')
        elif travel < 30:
            kinds.append('navigation_no_progress')
            if reversals >= 4:
                kinds.append('alternating_turn_commands_without_progress')
        elif metric == 'active_waypoint_distance' and travel >= 100 and net < 75:
            kinds.append('navigation_motion_without_progress')
        elif metric == 'active_waypoint_distance' and travel >= 100:
            long = [r for r in self.window if now-r['t'] <= 6.2]
            if (now-long[0]['t'] >= 5.8
                    and all(waypoint(r)[0] is not None and math.dist(waypoint(r)[0], dest) <= 50 for r in long)
                    and math.dist(long[0]['pos'], dest)-distance < 20):
                kinds.append('navigation_path_progress_stalled')
        if not kinds:
            return
        self.sequence += 1
        timers = [r.get('timer') for r in rows]
        timer_span = (max(timers)-min(timers)) if all(
            type(v) in (int, float) and math.isfinite(v) for v in timers) else None
        self.active = {'id': self.sequence, 'state': 'open', 'outcome': 'unresolved', 'kinds': kinds,
                       'from_t': rows[0]['t'], 'to_t': now, 'detected_at': now,
                       'player': row.get('player'), 'position_cm': row['pos'], 'waypoint': dest,
                       'player_generation': row.get('player_generation'),
                       'goal': row.get('goal'), 'distance_metric': metric,
                       'waypoint_switches': switches if churn else 0,
                       'final_goal_id': final_id if churn else None,
                       'distance_at_open_cm': round(distance, 2) if distance is not None else None,
                       'goal_progress_cm': round(progress, 2) if progress is not None else None,
                       'travel_cm': round(travel, 2), 'net_displacement_cm': round(net, 2),
                       'movement_command_coverage': round(coverage, 3), 'turn_command_reversals': reversals,
                       'max_sample_gap_s': max(b['t']-a['t'] for a,b in zip(rows,rows[1:])),
                       'before': list(self.window), 'collision_confirmed': None,
                       'game_timer_span_s': timer_span,
                       'evidence_warnings': ['game timer unchanged; paused or stalled simulation remains possible']
                           if timer_span is not None and timer_span < .01 else [],
                       'cause': 'unknown; inspect route, geometry, interactions and applied inputs',
                       'analysis_state': 'needs_triage', 'learning_applied': False}
        self.emit(now)


class ReportWriter:
    """Coalesce updates per episode and write off the gameplay thread."""
    def __init__(self, root, context, status, threaded=True):
        self.root, self.context, self.status = Path(root), context, status
        self.threaded = threaded
        self.pending = {}
        self.lock = threading.Lock()
        self.thread = None

    def submit(self, report, stage, inputs, geometry=None):
        row = dict(report, format='gbox.navigation_incident/1', units='cm',
                   coordinate_order='x,y,z', **self.context)
        row.update(stage=stage, input_events=deepcopy(inputs), geometry=geometry)
        with self.lock:
            self.pending[report['id']] = row
            if self.threaded:
                if self.thread is None or not self.thread.is_alive():
                    self.thread = threading.Thread(target=self._drain, daemon=True, name='mercs-nav-report')
                    self.thread.start()
                return
        self._drain()

    def _drain(self):
        while True:
            with self.lock:
                if not self.pending:
                    self.thread = None
                    return
                key = next(iter(self.pending)); row = self.pending.pop(key)
            try:
                from .run_capture import slug, _atomic
                title, stage = slug(row['title']), slug(row['stage'])
                path = self.root/title/stage/'navigation_incidents'/f"{slug(row['round_id'])}-{key:04d}.json"
                with _WRITE_LOCK:
                    new = not path.exists()
                    path.parent.mkdir(parents=True, exist_ok=True)
                    _atomic(path, json.dumps(row, separators=(',', ':'), allow_nan=False))
                    if new:
                        # Same local lessons stream as the run reviewer. The
                        # report is actionable immediately, before round end.
                        index = self.root.parent/'lessons'/f'{title}.jsonl'
                        index.parent.mkdir(parents=True, exist_ok=True)
                        note = {'kind': 'report', 'ts': row['detected_at'], 'source': 'navigation_monitor',
                                'text': ', '.join(row['kinds'])+'; automatic navigation incident needs triage',
                                'round_id': row['round_id'], 'session_id': row.get('session_id'),
                                'incident_file': str(path), 'analysis_state': 'needs_triage'}
                        with index.open('a', encoding='utf-8') as f:
                            f.write(json.dumps(note, separators=(',', ':'))+'\n')
                self.status['navigation_report_file'] = str(path)
                self.status['navigation_reports_written'] = self.status.get('navigation_reports_written', 0)+int(new)
                self.status.pop('navigation_report_error', None)
            except Exception as exc:
                self.status['navigation_report_error'] = f'{type(exc).__name__}: {exc}'[:200]
                with self.lock:
                    self.pending.setdefault(key, row)  # retry on next submit; never spin on failed storage
                    self.thread = None
                return


def geometry_context(snap, scale):
    mesh = snap.get('nav') or snap.get('navmesh')
    pos = (snap.get('player') or {}).get('pos')
    if mesh is None or not pos:
        return {'state': 'unavailable', 'collision_confirmed': None}
    out = {'state': 'available', 'source': getattr(mesh, 'geometry_source', 'unspecified'),
           'collision_confirmed': None, 'units': 'cm'}
    try:
        cell = mesh.member(pos); out['player_cell'] = cell
        vertices = getattr(mesh, 'points', None) or getattr(mesh, 'V', ())
        triangles = getattr(mesh, 'tris', None) or getattr(mesh, 'T', ())
        links = getattr(mesh, 'links', {})
        neighbors = links.get(cell, ()) if isinstance(links, dict) else links[cell] if cell is not None else ()
        cells = [cell]+[v[0] if isinstance(v, (list, tuple)) else v for v in list(neighbors)[:16]]
        out['local_triangles'] = [[[round(float(x)*scale, 2) for x in vertices[v]] for v in triangles[c]]
                                  for c in cells if isinstance(c, int) and 0 <= c < len(triangles)]
    except Exception as exc:
        out['read_error'] = f'{type(exc).__name__}: {exc}'[:160]
    return out
