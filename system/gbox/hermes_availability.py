"""Use Z.AI's observed quota to wake a single, reusable Hermes work lane."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sqlite3
import time
import urllib.error
import urllib.request

from . import hermes_delivery, hermes_task_mode, hermes_quota

MODEL = 'glm-5.3'
BASE = 'https://api.z.ai/api/coding/paas/v4'


def _save(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temporary.replace(path)


def quota_status(data: dict, now: float) -> dict:
    """Credit windows gate inference; unrelated MCP/tool windows do not."""
    payload = data.get('data') if isinstance(data, dict) else None
    limits = payload.get('limits') if isinstance(payload, dict) else None
    windows = [x for x in limits if isinstance(x, dict) and x.get('type') in ('CREDIT_LIMIT', 'TOKENS_LIMIT')] if isinstance(limits, list) else []
    if not isinstance(data, dict) or data.get('success') is not True or not windows:
        return {'status': 'unknown', 'next_check_at': now + 300, 'windows': []}
    blocked = [x for x in windows if (hermes_quota.number(x.get('remaining')) is not None and
                                     hermes_quota.number(x['remaining']) <= 0) or
                                    (hermes_quota.number(x.get('percentage')) is not None and
                                     hermes_quota.number(x['percentage']) >= 100)]
    unknown = any(hermes_quota.number(x.get('remaining')) is None and
                  hermes_quota.number(x.get('percentage')) is None for x in windows)
    resets = [value / 1000 for x in blocked if (value := hermes_quota.number(x.get('nextResetTime')))
              is not None and now < value / 1000 <= now + 31 * 86400]
    return {'status': 'quota_wait' if blocked else 'unknown' if unknown else 'quota_available',
            'next_check_at': max(resets) + 10 if resets and len(resets) == len(blocked) else now + 300,
            'windows': [{k: x[k] for k in ('type', 'unit', 'number', 'usage', 'currentValue',
                                          'remaining', 'percentage', 'nextResetTime') if k in x and
                         (k == 'type' or hermes_quota.number(x[k]) is not None)} for x in windows],
            'quota_source': 'provider_account_endpoint', 'quota_observed_at': now,
            'quota_balance_known': bool(blocked) or not unknown}


def _credential():
    # Called by a script using Hermes's own bootstrap/runtime. Never copy or log keys.
    from hermes_cli.runtime_provider import resolve_runtime_provider
    previous = os.environ.get('GLM_BASE_URL')
    try:
        os.environ['GLM_BASE_URL'] = BASE
        runtime = resolve_runtime_provider(requested='zai', target_model=MODEL)
    finally:
        if previous is None:
            os.environ.pop('GLM_BASE_URL', None)
        else:
            os.environ['GLM_BASE_URL'] = previous
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
            payload = json.load(exc)
            detail = payload.get('error') if isinstance(payload, dict) else None
            code = detail.get('code') if isinstance(detail, dict) else None
        except (ValueError, AttributeError):
            code = None
        result = {'error_code': str(code) if isinstance(code, (str, int)) and
                  re.fullmatch(r'[0-9]{1,6}', str(code)) else None}
        retry = hermes_quota.retry_after(exc.headers.get('Retry-After') if exc.headers else None, time.time())
        if retry is not None:
            result['reset_at'] = retry
        return exc.code, result


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
        data.setdefault('cooldown_details', {}).pop('zai/' + MODEL, None)
        route = {'provider': 'zai', 'model': MODEL}
        if route not in data.setdefault('routes', []):
            data['routes'].append(route)
        data['zai_available_at'] = now
        _save(path, data)


def _waiting_route(until, *, source='provider_account_endpoint', quota_balance_known=True):
    path = hermes_delivery.state_dir() / 'feedback.json'
    with hermes_delivery.locked('feedback'):
        data = json.loads(path.read_text()) if path.exists() else {}
        data.setdefault('cooldowns', {})['zai/' + MODEL] = until
        data.setdefault('cooldown_details', {})['zai/' + MODEL] = {
            'until': until, 'source': source, 'quota_balance_known': quota_balance_known,
            'observed_at': time.time(), 'category': 'quota'}
        _save(path, data)


def _completed_usage(state):
    """Share verified, idempotent model-ledger accounting with every work lane."""
    from . import hermes_accounting
    records = hermes_accounting.reconcile_completed(api=_api, home=hermes_task_mode._home(), limit=10)
    fields = ('run_id', 'request_id', 'session_id', 'status', 'tokens_in_added', 'tokens_out_added', 'reason')
    results = [{key: record[key] for key in fields if key in record}
               for record in records[:10] if isinstance(record, dict)]
    state['usage_reconciliation'] = results
    for record in results:
        rid, session = record.get('request_id'), record.get('session_id')
        if (record.get('status') not in ('reconciled', 'already_recorded')
                or not isinstance(rid, str) or not re.fullmatch(r'[0-9a-f]{16}', rid)
                or not isinstance(session, str) or not session):
            continue
        state['request_ids'] = sorted(set(state.get('request_ids') or []) | {rid})
        state['last_usage_request'], state['last_usage_session'] = rid, session
    return results


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
        _save(path, state)
        supervision_only = state.get('supervision_only') is True
        job = next((j for j in hermes_task_mode._jobs() if j['id'] == state.get('work_job_id')), None)
        if job is None and not supervision_only:
            raise RuntimeError('Registered Z.AI work job is missing')
        work_active = not supervision_only and (job.get('enabled') or hermes_task_mode._active(job['id']))
        if work_active and now - state.get('checked_at', 0) < 300:
            return {'status': 'work_queued_or_running', 'job_id': job['id'], 'provider': 'zai', 'model': MODEL}
        if not supervision_only and _native_pending(state.get('request_ids') or []):
            return {'status': 'waiting_for_native_analysis', 'job_id': job['id']}
        next_quota_check = state.get('next_quota_check_at',
            min(state.get('next_check_at', 0), state.get('checked_at', 0) + 300))
        if now < next_quota_check and not work_active:
            return {k: state.get(k) for k in ('status', 'next_check_at', 'windows')}
        try:
            if state.get('probe_http') is not None:
                state['last_probe'] = {'http': state.get('probe_http'), 'usage': state.get('probe_usage'),
                                       'checked_at': state.get('probe_checked_at', state.get('dispatched_at'))}
            state.update(probe_http=None, probe_error_code=None, probe_usage={}, probe_checked_at=None)
            key = _credential()
            http, quota = _zai('quota', key)
            observed = quota_status(quota, now) if http == 200 else {
                'status': 'unknown', 'next_check_at': now + 300, 'windows': [], 'quota_balance_known': False}
            state.update(observed, checked_at=now, next_quota_check_at=min(observed['next_check_at'], now + 300))
            state.pop('error_type', None)
            if observed['status'] == 'quota_wait' and not supervision_only:
                _waiting_route(observed['next_check_at'])
            if work_active:
                _save(path, state)
                return {'status': 'work_queued_or_running', 'job_id': job['id'],
                        'provider': 'zai', 'model': MODEL, 'quota_status': observed['status'],
                        'windows': state.get('windows'), 'next_quota_check_at': state['next_quota_check_at']}
            if observed['status'] != 'quota_wait':
                http, result = _zai('probe', key, {'model': MODEL, 'stream': False, 'max_tokens': 1,
                    'thinking': {'type': 'disabled'}, 'messages': [{'role': 'user', 'content': 'Reply OK.'}]})
                state.update(probe_http=http, probe_error_code=result.get('error_code'), probe_checked_at=now)
                if http == 200 and isinstance(result.get('choices'), list) and result['choices']:
                    if not supervision_only:
                        _available_route(now)
                    # Re-arm a genuine one-shot; its pin prevents fallback attribution to Z.AI.
                    controller = hermes_task_mode._job() or {}
                    managed = controller.get('no_agent')
                    from . import hermes_provider_scope as scope
                    blocked = scope.admission(hermes_task_mode._config(), job if not supervision_only and any(job.get(k) for k in ('provider', 'model', 'base_url')) else
                                              {'provider': 'zai', 'model': MODEL})
                    if blocked:
                        state.update(status='waiting_provider_scope', scope_reason=blocked['reason'],
                                     next_check_at=now + 300, next_quota_check_at=now + 300,
                                     probe_usage=result.get('usage') or {})
                        _save(path, state)
                        return {k: state.get(k) for k in ('status', 'scope_reason', 'work_job_id',
                                                         'windows', 'probe_http', 'probe_checked_at')}
                    if not managed and not supervision_only:
                        hermes_task_mode._run('resume', job['id'], '--run-now')
                    state.update(status='available_to_supervisor' if supervision_only else 'available_to_work_queue' if managed else 'work_dispatched', dispatched_at=now,
                                 next_check_at=now + 120, next_quota_check_at=now + 120,
                                 probe_usage=result.get('usage') or {})
                else:
                    state.update(status='probe_wait', next_check_at=now + (900 if http in (401, 403) else 300))
                    if http == 429:
                        category = hermes_quota.provider_failure(json.dumps(result)) or 'rate_limit'
                        wait = hermes_quota.failure_wait(result, category, now)
                        state['next_check_at'] = wait['until']
                        if not supervision_only:
                            _waiting_route(wait['until'], source=wait['source'], quota_balance_known=False)
                    state['next_quota_check_at'] = state['next_check_at']
        except (OSError, ValueError, RuntimeError, TypeError, AttributeError) as exc:
            # Exception text can include authentication material. Emit only its class.
            state.update(status='monitor_error', error_type=type(exc).__name__, next_check_at=now + 300)
            state['next_quota_check_at'] = state['next_check_at']
        _save(path, state)
        return {k: state.get(k) for k in ('status', 'work_job_id', 'next_check_at', 'next_quota_check_at',
                                         'checked_at', 'windows', 'probe_checked_at',
                                         'probe_http', 'probe_error_code', 'probe_usage', 'error_type')}
