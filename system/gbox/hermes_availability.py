"""Use Z.AI's observed quota to wake a single, reusable Hermes work lane."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sqlite3
from collections import Counter
from contextlib import closing
import time
import urllib.error
import urllib.request

from . import hermes_delivery, hermes_task_mode

MODEL = 'glm-5.3'
BASE = 'https://api.z.ai/api/coding/paas/v4'


def quota_status(data: dict, now: float) -> dict:
    """Credit windows gate inference; unrelated MCP/tool windows do not."""
    limits = (data.get('data') or {}).get('limits') or []
    windows = [x for x in limits if x.get('type') in ('CREDIT_LIMIT', 'TOKENS_LIMIT')]
    if data.get('success') is not True or not windows:
        return {'status': 'unknown', 'next_check_at': now + 300, 'windows': []}
    blocked = [x for x in windows if x.get('remaining', 1) <= 0 or x.get('percentage', 0) >= 100]
    resets = [x['nextResetTime'] / 1000 for x in blocked
              if isinstance(x.get('nextResetTime'), (int, float)) and x['nextResetTime'] / 1000 > now]
    return {'status': 'quota_wait' if blocked else 'quota_available',
            'next_check_at': max(resets) + 10 if resets and len(resets) == len(blocked) else now + 300,
            'windows': [{k: x[k] for k in ('type', 'unit', 'number', 'usage', 'currentValue',
                                          'remaining', 'percentage', 'nextResetTime') if k in x} for x in windows]}


def _credential():
    # Called by a script using Hermes's own bootstrap/runtime. Never copy or log keys.
    from hermes_cli.runtime_provider import resolve_runtime_provider
    os.environ['GLM_BASE_URL'] = BASE
    runtime = resolve_runtime_provider(requested='zai', target_model=MODEL)
    if runtime.get('provider') != 'zai' or runtime.get('base_url') != BASE or not runtime.get('api_key'):
        raise RuntimeError('Configured Z.AI credential is unavailable')
    return runtime['api_key']


def _zai(path, key, body=None):
    url = 'https://api.z.ai/api/monitor/usage/quota/limit' if path == 'quota' else BASE + '/chat/completions'
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                 headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        # Retain only a numeric error code; provider messages can contain sensitive input.
        try:
            code = (json.load(exc).get('error') or {}).get('code')
        except (ValueError, AttributeError):
            code = None
        return exc.code, {'error_code': code}


def _api(path, body=None):
    root = Path(__file__).resolve().parents[1]
    key = (root / 'gbox-data/api_token').read_text().strip()
    req = urllib.request.Request('http://127.0.0.1:8765' + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)


def _native_pending(request_ids):
    return any(j.get('parent_request_id') in request_ids and j.get('tool') in
               ('analyze_binary', 'ghidra_script', 'characters')
               for j in _api('/api/jobs?state=queued,running&limit=100'))


def _available_route(now):
    # Actual success supersedes the former guessed five-hour cooldown.
    path = hermes_delivery.state_dir() / 'feedback.json'
    with hermes_delivery.locked('feedback'):
        data = json.loads(path.read_text()) if path.exists() else {}
        data.setdefault('cooldowns', {}).pop('zai/' + MODEL, None)
        route = {'provider': 'zai', 'model': MODEL}
        if route not in data.setdefault('routes', []):
            data['routes'].append(route)
        data['zai_available_at'] = now
        path.write_text(json.dumps(data, indent=2))


def _waiting_route(until):
    path = hermes_delivery.state_dir() / 'feedback.json'
    with hermes_delivery.locked('feedback'):
        data = json.loads(path.read_text()) if path.exists() else {}
        data.setdefault('cooldowns', {})['zai/' + MODEL] = until
        path.write_text(json.dumps(data, indent=2))


def _completed_usage(state):
    """Record measured completed sessions once and retain their actual task ownership."""
    from . import hermes_tasks
    home = hermes_task_mode._home()
    if not (home / 'cron/executions.db').exists() or not (home / 'state.db').exists():
        return
    with closing(sqlite3.connect(f'file:{(home / "cron/executions.db").as_posix()}?mode=ro', uri=True)) as cron:
        cron.row_factory = sqlite3.Row
        runs = cron.execute('SELECT started_at FROM executions WHERE job_id=? '
                            "AND status IN ('completed','failed') ORDER BY started_at DESC LIMIT 10",
                            (state['work_job_id'],)).fetchall()
    with closing(sqlite3.connect(f'file:{(home / "state.db").as_posix()}?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        for run in reversed(runs):
            session = hermes_tasks._session(db, state['work_job_id'], hermes_tasks._stamp(run['started_at']))
            if not session or not session['ended_at']:
                continue
            owners = hermes_tasks._owned_requests(db, session['id'])
            state['request_ids'] = sorted(set(state.get('request_ids') or []) | set(owners))
            rid = state.get('usage_request_id') or next((x for x in state.get('request_ids') or []
                                                       if re.fullmatch(r'[0-9a-f]{16}', x)), None)
            reported_in = reported_out = reported_turns = 0
            reported_tools = Counter()
            primary = None
            for row in db.execute("SELECT tool_calls FROM messages WHERE session_id=? AND role='assistant'",
                                  (session['id'],)):
                for call in hermes_tasks._structured_calls(row['tool_calls']):
                    args = call['input']
                    if not isinstance(args, dict):
                        continue
                    if (primary is None and call['action'].endswith('set_request_status')
                            and args.get('status') == 'in_progress'):
                        primary = args.get('request_id')
            if isinstance(primary, str) and re.fullmatch(r'[0-9a-f]{16}', primary):
                rid = primary
            if rid is None:
                continue
            for row in db.execute("SELECT tool_calls FROM messages WHERE session_id=? AND role='assistant'",
                                  (session['id'],)):
                for call in hermes_tasks._structured_calls(row['tool_calls']):
                    args = call['input']
                    if (call['action'].endswith('record_request_metrics') and isinstance(args, dict)
                            and args.get('request_id') == rid):
                        metrics = args.get('metrics') or args
                        reported_in += metrics.get('tokens_in') or 0
                        reported_out += metrics.get('tokens_out') or 0
                        reported_turns += metrics.get('turns') or 1
                        reported_tools.update(metrics.get('tools') or {})
            marker = 'hermes_session_' + session['id'] + '_recorded'
            request = _api('/api/requests/' + rid)
            if request.get('metrics', {}).get('tokens_detail', {}).get(marker):
                continue
            usage = hermes_tasks._usage(session)
            detail = {k: v for k, v in usage['tokens_detail'].items() if isinstance(v, int)} | {marker: 1}
            tools = Counter(row['tool_name'] or 'tool' for row in db.execute(
                "SELECT tool_name FROM messages WHERE session_id=? AND role='tool'", (session['id'],)))
            _api('/api/requests/' + rid + '/metrics', {
                'provider': session['billing_provider'] or 'zai', 'model': session['model'], 'system': 'Hermes',
                'tokens_in': max(0, usage['tokens_in'] - reported_in),
                'tokens_out': max(0, usage['tokens_out'] - reported_out), 'tokens_detail': detail,
                'turns': max(1, detail['api_call_count'] - reported_turns), 'tools': dict(tools - reported_tools),
                'duration_s': round(session['ended_at'] - session['started_at'], 1)})
            state['last_usage_session'] = session['id']
            state['last_usage_request'] = rid


def tick(now=None):
    """Cheap quota monitoring; one actual model probe before dispatch, never a quota loop."""
    now = time.time() if now is None else now
    path = hermes_delivery.state_dir() / 'zai-availability.json'
    with hermes_delivery.locked('zai-availability'):
        state = json.loads(path.read_text())
        try:
            _completed_usage(state)
        except (OSError, ValueError, sqlite3.Error) as exc:
            state['usage_error_type'] = type(exc).__name__
        path.write_text(json.dumps(state, indent=2))
        job = next((j for j in hermes_task_mode._jobs() if j['id'] == state['work_job_id']), None)
        if job is None:
            raise RuntimeError('Registered Z.AI work job is missing')
        if job.get('enabled') or hermes_task_mode._active(job['id']):
            return {'status': 'work_queued_or_running', 'job_id': job['id'], 'provider': 'zai', 'model': MODEL}
        if _native_pending(state.get('request_ids') or []):
            return {'status': 'waiting_for_native_analysis', 'job_id': job['id']}
        if now < state.get('next_check_at', 0):
            return {k: state.get(k) for k in ('status', 'next_check_at', 'windows')}
        try:
            key = _credential()
            http, quota = _zai('quota', key)
            observed = quota_status(quota, now) if http == 200 else {'status': 'unknown', 'next_check_at': now + 300}
            state.update(observed, checked_at=now)
            if observed['status'] == 'quota_wait':
                _waiting_route(observed['next_check_at'])
            if observed['status'] != 'quota_wait':
                http, result = _zai('probe', key, {'model': MODEL, 'stream': False, 'max_tokens': 1,
                    'thinking': {'type': 'disabled'}, 'messages': [{'role': 'user', 'content': 'Reply OK.'}]})
                state.update(probe_http=http, probe_error_code=result.get('error_code'))
                if http == 200 and isinstance(result.get('choices'), list) and result['choices']:
                    _available_route(now)
                    # Re-arm a genuine one-shot; its pin prevents fallback attribution to Z.AI.
                    hermes_task_mode._run('resume', job['id'], '--run-now')
                    state.update(status='work_dispatched', dispatched_at=now,
                                 next_check_at=now + 120, probe_usage=result.get('usage') or {})
                else:
                    state.update(status='probe_wait', next_check_at=now + (900 if http in (401, 403) else 300))
        except (OSError, ValueError, RuntimeError) as exc:
            # Exception text can include authentication material. Emit only its class.
            state.update(status='monitor_error', error_type=type(exc).__name__, next_check_at=now + 300)
        path.write_text(json.dumps(state, indent=2))
        return {k: state.get(k) for k in ('status', 'work_job_id', 'next_check_at', 'windows',
                                         'probe_http', 'probe_error_code', 'probe_usage', 'error_type')}
