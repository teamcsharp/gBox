"""Learn from durable executions without mistaking model usage for delivery."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import sqlite3
import subprocess
import time

from . import hermes_delivery, hermes_task_mode


ADVICE = {
    'quota': 'Use an available connected provider; preserve the patch and wait for the exhausted model cooldown.',
    'rate_limit': 'Back off this model and use another connected route; do not repeat the same throttled request.',
    'vision_history': 'Use auxiliary vision returning text. Do not append native image/model history to the failing route.',
    'worker_timeout': 'Check worker health once. Use start_job/get_job and keep the same job ID; continue Git source work while the worker is unavailable.',
    'permission': 'Use the fixed gBox prepare_task_workspace and publish_task_changes tools. Do not retry a denied shell deployment or push.',
    'scheduler_claim': 'Use a finite genuine one-shot dispatched by the gateway. Preserve the prior execution; do not run the same occurrence from two launchers.',
    'turn_budget': 'Resume the saved patch at validation/publication. Use high reasoning, focused tests and a 45-tool-call work budget, reserving the final 10 calls for handoff.',
    'no_publication': 'Use a tracked task workspace, validate its patch and publish a draft PR. A canonical-share edit alone is not GitHub delivery.',
    'other': 'Read the prior failure and saved patch; change the failed step before retrying and report an observable result.',
}


def classify(error: str) -> str:
    text = error.lower()
    if 'usage limit' in text or 'quota' in text or 'insufficient credits' in text:
        return 'quota'
    if '429' in text or 'rate limit' in text:
        return 'rate_limit'
    if 'model turn' in text or 'http 400' in text:
        return 'vision_history'
    if 'claim ownership' in text or 'restart-safe cron worker' in text:
        return 'scheduler_claim'
    if 'timed out' in text or 'worker is unavailable' in text or 'worker is saturated' in text:
        return 'worker_timeout'
    if 'denied' in text or 'blocked without approvals' in text or 'permission' in text:
        return 'permission'
    return 'other'


def _stamp(text):
    try:
        return dt.datetime.fromisoformat(text).timestamp()
    except (ValueError, TypeError):
        return 0


def tool_error(content: str) -> str:
    """Extract failures, not quotations inside successful inbox/source reads."""
    if content.startswith('<untrusted_tool_result'):
        content = content.split('\n\n', 1)[-1]
    try:
        result, _ = json.JSONDecoder().raw_decode(content.lstrip())
    except (ValueError, TypeError):
        return ''
    if not isinstance(result, dict):
        return ''
    if isinstance(result.get('error'), str):
        return result['error']
    if result.get('isError'):
        return ' '.join(c.get('text', '') for c in result.get('content', []) if isinstance(c, dict))
    return ''


def scan(*, home: Path | None = None, now: float | None = None) -> dict:
    home, now = home or hermes_task_mode._home(), time.time() if now is None else now
    target = hermes_delivery.state_dir() / 'feedback.json'
    with hermes_delivery.locked('feedback'):
        data = json.loads(target.read_text()) if target.exists() else {'processed': [], 'lessons': [], 'cooldowns': {}}
        if data.get('schema_version') != 3:
            # Recompute derived lessons after fixing quoted-error detection.
            data.update(schema_version=3, processed=[], lessons=[], cooldowns={})
        path = home / 'cron/executions.db'
        if not path.exists():
            return data
        db = sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True); db.row_factory = sqlite3.Row
        runs = db.execute("SELECT id,job_id,status,started_at,finished_at,error FROM executions "
                          "WHERE status IN ('completed','failed','unknown') ORDER BY started_at DESC LIMIT 100").fetchall()
        state_path = home / 'state.db'
        state = sqlite3.connect(f'file:{state_path.as_posix()}?mode=ro', uri=True) if state_path.exists() else None
        if state:
            state.row_factory = sqlite3.Row
        jobs_path = home / 'cron/jobs.json'
        jobs = {j['id']: j for j in json.loads(jobs_path.read_text()).get('jobs', [])} if jobs_path.exists() else {}
        added = []
        for run in reversed(runs):
            if run['id'] in data['processed']:
                continue
            data['processed'].append(run['id'])
            job, session = jobs.get(run['job_id'], {}), None
            if state and run['started_at']:
                session = hermes_task_mode_session(state, run['job_id'], _stamp(run['started_at']))
            error = run['error'] or ''
            provider = (session['billing_provider'] if session and 'billing_provider' in session.keys() else None) or job.get('provider')
            model = (session['model'] if session else None) or job.get('model')
            category = classify(error) if run['status'] != 'completed' else None
            if session:
                messages = state.execute("SELECT content,tool_name FROM messages WHERE session_id=? AND role='tool'", (session['id'],)).fetchall()
                failures = [kind for m in messages if (error := tool_error(m['content'] or ''))
                            and (kind := classify(error)) != 'other']
                if failures and category in (None, 'other'):
                    category = max(set(failures), key=failures.count)
                if (session['output_tokens'] or 0) > 50000 or (session['api_call_count'] or 0) >= 140:
                    category = category or 'turn_budget'
                wrote_code = any(m['tool_name'] in ('patch', 'write_file') for m in messages)
                published = any((m['tool_name'] or '').endswith('publish_task_changes') and
                                'github.com/' in (m['content'] or '') for m in messages)
                if not category and wrote_code and not published:
                    category = 'no_publication'
            if session:
                data['rotation_pending'] = True
            if not category:
                continue  # successful script-only maintenance consumes no inference
            lesson = {'run_id': run['id'], 'job_id': run['job_id'], 'provider': provider, 'model': model,
                      'category': category, 'advice': ADVICE[category], 'observed_at': _stamp(run['finished_at']) or now}
            data['lessons'].append(lesson); added.append(lesson)
            if provider and model and category in ('quota', 'rate_limit'):
                until = lesson['observed_at'] + (5 * 3600 if category == 'quota' else 15 * 60)
                key = provider + '/' + model
                data['cooldowns'][key] = max(data['cooldowns'].get(key, 0), until)
        db.close()
        if state:
            state.close()
        data['processed'] = data['processed'][-512:]
        data['lessons'] = data['lessons'][-100:]
        data['cooldowns'] = {k: v for k, v in data['cooldowns'].items() if v > now}
        data['updated_at'] = now
        data['new_lessons'] = len(added)
        target.write_text(json.dumps(data, indent=2))
        return data


def hermes_task_mode_session(state, job_id, started):
    from .hermes_tasks import _session
    return _session(state, job_id, started)


def brief() -> str:
    path = hermes_delivery.state_dir() / 'feedback.json'
    if not path.exists():
        return ''
    data = json.loads(path.read_text())
    categories = {x['category'] for x in data.get('lessons', [])[-20:]}
    return '\nLessons from actual previous runs: ' + ' '.join(ADVICE[c] for c in sorted(categories))


def adjust_routes() -> dict:
    data, config = scan(), hermes_task_mode._config()
    cron = config.get('cron') or {}
    routes = data.get('routes') or [{'provider': x.get('provider'), 'model': x.get('model')}
                                  for x in config.get('fallback_providers', []) if x.get('provider') and x.get('model')]
    primary = {'provider': cron.get('model_provider'), 'model': cron.get('model')}
    if primary not in routes and all(primary.values()):
        routes.insert(0, primary)
    eligible = [r for r in routes if r['provider'] + '/' + r['model'] not in data['cooldowns']]
    if not eligible:
        return {'changed': False, 'reason': 'All connected routes are cooling down', 'lessons': data['new_lessons']}
    # Rotation is done only between agent runs. Never mutate an in-flight route.
    busy = any(hermes_task_mode._active(j['id']) and not j.get('no_agent') for j in hermes_task_mode._jobs())
    chosen = primary
    if primary not in eligible or (data.get('rotation_pending') and not busy):
        index = eligible.index(primary) if primary in eligible else -1
        chosen = eligible[(index + 1) % len(eligible)]
    cli = str(hermes_task_mode._cli())
    changes = {'cron.model_provider': chosen['provider'], 'cron.model': chosen['model'],
               'fallback_providers': [r for r in eligible if r != chosen]}
    for key, value in changes.items():
        old = config.get(key) if key == 'fallback_providers' else cron.get(key.split('.')[1])
        if old != value:
            result = subprocess.run([cli, 'config', 'set', key, json.dumps(value) if isinstance(value, list) else value],
                                    capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise RuntimeError('Hermes route update failed: ' + key)
    path = hermes_delivery.state_dir() / 'feedback.json'
    with hermes_delivery.locked('feedback'):
        saved = json.loads(path.read_text())
        saved.update(routes=routes, current_route=chosen)
        if chosen != primary or not busy:
            saved['rotation_pending'] = False
        path.write_text(json.dumps(saved, indent=2))
    return {'route': chosen, 'cooldowns': data['cooldowns'], 'new_lessons': data['new_lessons'], 'agent_busy': busy}
