"""Cited level plans, grounded instructions and progress receipts.

Guide text is evidence, never executable input. A plan cannot supply coordinates,
memory addresses or buttons. Game adapters bind semantic actions to their own
observed targets; unimplemented actions remain explicit blockers.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import math
import os
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1] / 'gbox-data' / 'level-strategy'
ACTIONS = {'defeat_enemies', 'defeat_boss', 'follow_markers', 'destroy_barrels',
           'navigate', 'interact', 'collect_time', 'verify_result'}
IDENTITY = ('game_id', 'build', 'mod', 'level')
_LOCK = threading.RLock()
_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix='level-strategy')


def scope(context):
    if not isinstance(context, dict):
        raise ValueError('Level context must be an object')
    out = {key: str(context.get(key) or '')[:200] for key in IDENTITY}
    if not all(out[key] for key in ('game_id', 'build', 'level')):
        raise ValueError('A game, observed build and current level are required')
    return out


def key(context):
    return hashlib.sha256(json.dumps(scope(context), sort_keys=True).encode()).hexdigest()


def validate_plan(proposal, context, sources):
    """Reject model-invented citations and control payloads; keep unsupported steps."""
    if not isinstance(proposal, dict) or set(proposal) - {'summary', 'objectives', 'route', 'uncertainties'}:
        raise ValueError('Unexpected plan fields')
    available = {row['id']: row for row in sources if row.get('access') == 'fetched' and row.get('sha256')}
    objectives = proposal.get('objectives')
    if not isinstance(objectives, list) or not 1 <= len(objectives) <= 12:
        raise ValueError('Plan needs 1..12 objectives')
    steps = []
    for index, row in enumerate(objectives):
        if not isinstance(row, dict) or set(row) - {'action', 'target', 'reason', 'source_ids'}:
            raise ValueError('Objectives contain semantic actions only')
        action = row.get('action')
        if action not in ACTIONS:
            raise ValueError('Unsupported strategy action vocabulary')
        ids = row.get('source_ids')
        if not isinstance(ids, list) or not ids or any(s not in available for s in ids):
            raise ValueError('Every objective needs a fetched source citation')
        target = str(row.get('target') or '')[:160]
        supported = action in context.get('actions', ())
        grounded = action in ('defeat_enemies', 'verify_result') or target in context.get('targets', {})
        steps.append({'id': index, 'action': action, 'target': target,
                      'reason': str(row.get('reason') or '')[:400], 'source_ids': list(dict.fromkeys(ids)),
                      'executable': supported and grounded,
                      'blocker': '' if supported and grounded else
                          'No verified adapter for this action' if not supported else 'Target is not observed in the game'})
    required = context.get('required_action')
    if required and steps[0]['action'] != required:
        raise ValueError('Plan contradicts the observed mission objective')
    if steps[-1]['action'] != 'verify_result':
        raise ValueError('Plan must end with native result verification')
    route = proposal.get('route') or []
    unknown = proposal.get('uncertainties') or []
    if not isinstance(route, list) or not isinstance(unknown, list):
        raise ValueError('Route and uncertainties must be lists')
    # Strings are labels for later grounding, never world-space waypoints.
    if any(not isinstance(x, str) for x in route + unknown):
        raise ValueError('Route names cannot contain coordinates or input payloads')
    return {'schema': 1, 'scope': scope(context), 'summary': str(proposal.get('summary') or '')[:800],
            'objectives': steps, 'route': route[:20], 'uncertainties': unknown[:12],
            'sources': [{k: row.get(k) for k in ('id', 'url', 'title', 'access', 'sha256', 'retrieved_at', 'kind')}
                        for row in sources], 'created': time.time(), 'validation': 'schema_and_source_provenance',
            'completion_verified': False,
            'execution_limit': 'Only the first semantic objective is consumed; later steps and routes need title-specific completion evidence.',
            'execution': 'adapter-grounded steps only; research is not a gameplay-completion receipt'}


class Store:
    def __init__(self, root=ROOT):
        self.root = Path(root)

    def _read(self, name):
        try:
            return json.loads((self.root / name).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None

    def _write(self, name, value):
        data = json.dumps(value, allow_nan=False, ensure_ascii=True, indent=1).encode()
        if len(data) > 200000:
            raise ValueError('Strategy record exceeds bounded storage size')
        with _LOCK:
            self.root.mkdir(parents=True, exist_ok=True)
            path = self.root / name
            temp = path.with_name(path.name + f'.{os.getpid()}.{threading.get_ident()}.tmp')
            try:
                temp.write_bytes(data)
                os.replace(temp, path)
            finally:
                temp.unlink(missing_ok=True)

    def plan(self, context):
        row = self._read(key(context) + '.json')
        return row if isinstance(row, dict) and row.get('scope') == scope(context) else None

    def save(self, context, plan):
        if plan.get('schema') != 1 or plan.get('scope') != scope(context):
            raise ValueError('Strategy identity changed before publication')
        self._write(key(context) + '.json', plan)

    def settings(self, game_id):
        return self._read('settings-' + hashlib.sha256(str(game_id).encode()).hexdigest() + '.json') or {}

    def configure(self, game_id, enabled, config):
        # No credential or arbitrary command is persisted.
        for name in ('llm_url', 'searx_url'):
            url = config.get(name)
            if url:
                parts = urlsplit(str(url))
                if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
                    raise ValueError('Research endpoints cannot persist credentials or query tokens')
        row = {'enabled': bool(enabled), 'agent': {k: config.get(k) for k in ('llm_url', 'model', 'searx_url')},
               'updated': time.time()}
        self._write('settings-' + hashlib.sha256(str(game_id).encode()).hexdigest() + '.json', row)
        return row

    def progress(self, context, receipt):
        self._write(key(context) + '.progress.json', {'scope': scope(context), **receipt})


class Progress:
    """Only observed objective changes count. Remaining alive is not progress."""
    def __init__(self, clock=time.monotonic, stall_seconds=20):
        self.clock, self.stall_seconds = clock, stall_seconds
        self.identity = None
        self.last_progress = self.clock()
        self.previous = {}
        self.stalls = 0
        self.last_replan = -1e9

    def observe(self, context, observation):
        now = self.clock()
        identity = scope(context)
        if self.identity != identity:
            self.identity, self.previous = identity, {}
            self.last_progress, self.last_replan, self.stalls = now, -1e9, 0
        before = self.previous
        elapsed = observation.get('elapsed')
        if isinstance(elapsed, (int, float)) and isinstance(before.get('elapsed'), (int, float)) \
                and elapsed < before['elapsed'] - 1:
            before = {}
            self.last_progress = now
        enemies = {str(e['ptr']): float(e['hp']) for e in observation.get('enemies', ())
                   if isinstance(e, dict) and e.get('ptr') is not None and isinstance(e.get('hp'), (int, float))
                   and math.isfinite(e['hp'])}
        score = observation.get('score')
        damage = any(ptr in before.get('enemies', {}) and hp < before['enemies'][ptr]
                     for ptr, hp in enemies.items())
        scored = isinstance(score, (int, float)) and isinstance(before.get('score'), (int, float)) and score > before['score']
        counter = observation.get('objective_counter')
        counted = type(counter) is int and type(before.get('counter')) is int and counter > before['counter']
        objective_end = observation.get('native_objective_end') is True
        failed = observation.get('native_failed') is True
        if damage or scored or counted or objective_end:
            self.last_progress = now
        stalled = not objective_end and (failed or now - self.last_progress >= self.stall_seconds)
        replan = stalled and now - self.last_replan >= 60
        if replan:
            self.stalls += 1
            self.last_replan = now
        self.previous = {'enemies': enemies, 'score': score, 'counter': counter, 'elapsed': elapsed}
        return {'stalled': stalled, 'replan': replan, 'stalls': self.stalls,
                'no_progress_seconds': round(max(0, now - self.last_progress), 2),
                'progress_evidence': 'native_objective_end' if objective_end else 'target_hp_decrease' if damage else
                    'score_increase' if scored else 'objective_counter' if counted else None,
                'objective_ended': objective_end, 'failed': failed,
                'mission_cleared': observation.get('native_clear_verified') is True,
                'unlock_verified': observation.get('native_unlock_growth') is True,
                'completion_verified': observation.get('native_clear_verified') is True,
                'note': 'Objective end, result rank and new-level unlock are separate evidence'}


class Runtime:
    """Nonblocking per-bot consumer; one bounded research request at a time."""
    def __init__(self, context_factory, store=None, research=None, clock=time.monotonic, network_allowed=lambda: False):
        self.context_factory, self.store = context_factory, store or Store()
        self.research, self.clock = research, clock
        self.monitor = Progress(clock)
        self.pending = None
        self.last_poll = -1e9
        self.plan = None
        self.current_key = None
        self.receipt = {}
        self.last_request = -1e9
        self.settings = {}
        self.last_error = None
        self.network_allowed = network_allowed

    def observe(self, observation):
        context = self.context_factory(observation)
        if not context:
            self.plan, self.current_key, self.last_poll = None, None, -1e9
            if self.pending:
                self.pending = (None, self.pending[1])
            self.receipt = {'context_available': False, 'plan_available': False,
                            'research_pending': self.pending is not None,
                            'completion_verified': False, 'reason': 'Current native level context is unavailable'}
            return None
        token = key(context)
        now = self.clock()
        if token != self.current_key:
            self.current_key, self.plan, self.last_poll = token, None, -1e9
        receipt = self.monitor.observe(context, observation)
        if now - self.last_poll >= 2:
            self.last_poll, self.plan = now, self.store.plan(context)
            self.settings = self.store.settings(context['game_id'])
            self.store.progress(context, receipt | {'at': time.time()})
        settings = self.settings
        if self.pending and self.pending[1].done():
            bound, future = self.pending
            self.pending = None
            try:
                result = future.result()
                if bound == token and settings.get('enabled') and self.network_allowed():
                    self.store.save(context, result)
                    self.plan = result
                    self.last_error = None
            except Exception as error:
                self.last_error = str(error)[:300]
        if settings.get('enabled') and self.network_allowed() and not self.pending and now - self.last_request >= 60 \
                and (self.plan is None or receipt['replan']):
            from .level_strategy_web import research
            fn = self.research or research
            previous = {'progress': receipt, 'plan': self.plan}
            kwargs = {'network_allowed': self.network_allowed} if self.research is None else {}
            self.pending = (token, _POOL.submit(fn, context, settings.get('agent') or {}, previous, **kwargs))
            self.last_request = now
        receipt['research_pending'] = self.pending is not None
        receipt['plan_available'] = self.plan is not None
        receipt['enabled'] = bool(settings.get('enabled'))
        receipt['network_allowed'] = bool(self.network_allowed())
        receipt['research_error'] = self.last_error
        self.receipt = receipt
        return self.plan if settings.get('enabled') else None

    def instruction(self, observation):
        plan = self.observe(observation)
        if not plan:
            return None
        context = self.context_factory(observation)
        if not context or scope(context) != plan.get('scope'):
            return None
        self.receipt['execution_limit'] = plan.get('execution_limit')
        if self.receipt.get('objective_ended') or self.receipt.get('failed'):
            return None
        for step in plan.get('objectives', ()):
            action, target = step['action'], step.get('target')
            # Re-ground on every tick: saved coordinates and stale pointers never act.
            executable = action in context.get('actions', ()) and (
                action in ('defeat_enemies', 'verify_result') or target in context.get('targets', {}))
            if action != 'verify_result':
                return dict(step, executable=executable, binding=context.get('targets', {}).get(target),
                            source_urls=[row['url'] for row in plan['sources'] if row['id'] in step['source_ids']])
        return None
