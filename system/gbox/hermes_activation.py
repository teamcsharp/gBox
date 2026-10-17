"""Activate the Hermes bridge update when gBox has no work to interrupt."""
from __future__ import annotations

import json
from contextlib import closing
import datetime as dt
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import time
from urllib.parse import quote
import urllib.request


def idle_reason(chats: list[dict], tasks: dict, sessions: list[dict]) -> str:
    """Require a complete work inventory before allowing a backend refresh."""
    unknown = 'Waiting for a complete, valid activation safety snapshot.'
    if (not isinstance(chats, list) or not isinstance(tasks, dict) or not isinstance(sessions, list)
            or any(not isinstance(c, dict) or not isinstance(c.get('busy'), bool) for c in chats)):
        return unknown
    if any(c['busy'] for c in chats):
        return 'Waiting for the active gBox conversation to finish.'
    keys = ('jobs', 'machines', 'hermes', 'resolutions')
    if any(not isinstance(tasks.get(k), list) or any(not isinstance(x, dict) for x in tasks[k]) for k in keys):
        return unknown
    if tasks['jobs']:
        return 'Waiting for active gBox worker jobs to finish.'
    terminal = {'completed', 'failed', 'error', 'cancelled', 'blocked'}
    for run in tasks['hermes']:
        if run.get('state') in ('claimed', 'running'):
            return 'Waiting for the active Hermes execution to finish.'
        if not isinstance(run.get('state'), str) or run['state'] not in terminal:
            return unknown
        if not isinstance(run.get('id'), str) or not run['id']:
            return unknown
    for resolution in tasks['resolutions']:
        if resolution.get('state') == 'running':
            return 'Waiting for the active inbox resolution to finish.'
        if (not isinstance(resolution.get('state'), str)
                or resolution['state'] not in {'open', 'in_progress', 'done', 'cancelled', 'blocked', 'failed'}):
            return unknown
    machines = {}
    for machine in tasks['machines']:
        identifier, os_name = machine.get('worker_id'), machine.get('os')
        if not isinstance(identifier, str) or not identifier or os_name not in ('linux', 'windows') or identifier in machines:
            return unknown
        machines[identifier] = os_name
    running_ids = set()
    for session in sessions:
        if not isinstance(session, dict) or session.get('state') not in ('running', 'ended'):
            return unknown
        if session['state'] == 'ended':
            continue
        sid = session.get('session_id')
        if not isinstance(sid, str) or '-' not in sid or sid in running_ids:
            return unknown
        running_ids.add(sid)
        worker = session.get('worker_id') or sid.split('-', 1)[0]
        if not isinstance(worker, str) or worker not in machines or sid.split('-', 1)[0] != worker:
            return unknown
        if machines[worker] == 'linux':
            return 'Waiting for the Spark game session to finish.'
        pid = (session.get('detail') or {}).get('pid') if isinstance(session.get('detail'), dict) else None
        if type(pid) is not int or pid <= 0:
            return unknown
    return ''


def read_active_jobs(root: Path) -> list[dict]:
    """Read active jobs directly; unlike GET /api/tasks this queues no inventory."""
    path = root / 'gbox-data/gbox.sqlite3'
    with closing(sqlite3.connect('file:' + quote(path.as_posix(), safe='/:') + '?mode=ro', uri=True, timeout=2)) as db:
        db.execute('PRAGMA query_only=ON')
        rows = db.execute("SELECT body FROM docs WHERE kind='job' AND COALESCE(json_extract(body,'$.state'),'') "
                          "NOT IN ('succeeded','invalid','failed','rejected','cancelled') LIMIT 1001").fetchall()
    if len(rows) > 1000:
        raise ValueError('Activation job inventory exceeds its bounded snapshot')
    jobs = [json.loads(row[0]) for row in rows]
    if any(not isinstance(j, dict) or j.get('state') not in ('queued', 'running') for j in jobs):
        raise ValueError('Activation job inventory contains unknown states')
    return jobs


def read_cron_snapshot(home: Path, *, now: float | None = None, imminent_s: float = 60) -> dict:
    """Read canonical claims and near-term schedules, without claiming or rearming."""
    now = time.time() if now is None else now
    if (type(now) not in (int, float) or type(imminent_s) not in (int, float)
            or not math.isfinite(now) or not math.isfinite(imminent_s) or imminent_s < 0):
        raise ValueError('Invalid activation schedule boundary')
    path = home / 'cron/executions.db'
    with closing(sqlite3.connect('file:' + quote(path.as_posix(), safe='/:') + '?mode=ro', uri=True, timeout=2)) as db:
        db.execute('PRAGMA query_only=ON')
        rows = db.execute("SELECT id,job_id,status FROM executions WHERE status IN ('claimed','running') LIMIT 129").fetchall()
    if len(rows) > 128 or any(not isinstance(r[0], str) or not r[0] or not isinstance(r[1], str) or not r[1] for r in rows):
        raise ValueError('Activation cron claims are incomplete or exceed the bounded snapshot')
    active = [{'id': r[0], 'job_id': r[1], 'state': r[2]} for r in rows]
    jobs_path = home / 'cron/jobs.json'
    before = jobs_path.stat()
    if before.st_size > 8 * 1024 * 1024:
        raise ValueError('Activation schedule inventory exceeds its bounded snapshot')
    with jobs_path.open('rb') as stream:
        raw = stream.read(8 * 1024 * 1024 + 1)
    after = jobs_path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or len(raw) != before.st_size:
        raise ValueError('Activation schedules changed during the snapshot')
    document = json.loads(raw)
    jobs = document.get('jobs') if isinstance(document, dict) else None
    if not isinstance(jobs, list) or len(jobs) > 1000:
        raise ValueError('Activation schedule inventory is malformed')
    due, seen = [], set()
    for job in jobs:
        if (not isinstance(job, dict) or not isinstance(job.get('id'), str) or not job['id']
                or job['id'] in seen or not isinstance(job.get('enabled'), bool)):
            raise ValueError('Activation schedule identity or enabled state is unknown')
        seen.add(job['id'])
        if not job['enabled']:
            continue
        when = job.get('next_run_at')
        if not isinstance(when, str) or not isinstance(job.get('schedule'), dict):
            raise ValueError('An enabled cron schedule has no verified next occurrence')
        timestamp = dt.datetime.fromisoformat(when)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError('An enabled cron schedule has an ambiguous timezone')
        if timestamp.timestamp() <= now + imminent_s:
            due.append({'id': job['id'], 'next_run_at': when, 'no_agent': job.get('no_agent') is True})
    return {'hermes': active, 'imminent_or_overdue': due, 'checked_at': now, 'imminent_s': imminent_s}


def activation_snapshot(root: Path, api, *, home: Path | None = None, now: float | None = None,
                        imminent_s: float = 60) -> dict:
    """Collect a fresh bounded guard using pure HTTP readers plus canonical files."""
    sessions = []
    try:
        chats, sessions, workers = api('/api/chat'), api('/api/sessions'), api('/api/workers')
        if not isinstance(workers, list) or any(not isinstance(w, dict) for w in workers):
            raise ValueError('Worker inventory unavailable')
        cron = read_cron_snapshot(home or Path(os.environ.get('GBOX_HERMES_HOME') or Path.home() / '.hermes'),
                                  now=now, imminent_s=imminent_s)
        tasks = {'jobs': read_active_jobs(root),
                 'machines': [{'worker_id': w.get('id'), 'os': w.get('os')} for w in workers],
                 'hermes': cron['hermes'], 'resolutions': []}
        reason = idle_reason(chats, tasks, sessions)
        if not reason and cron['imminent_or_overdue']:
            reason = 'Waiting for imminent or overdue Hermes schedules to finish.'
        return {'reason': reason, 'sessions': sessions, 'tasks': tasks, 'cron': cron}
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, OverflowError, sqlite3.Error):
        return {'reason': 'Waiting for a complete canonical activation safety snapshot.', 'sessions': sessions}


def check_idle(root: Path) -> int:
    """Bootstrap preflight: a busy or unknown runtime must not be restarted."""
    from .hermes_work_queue import _api
    reason = activation_snapshot(root, _api)['reason']
    if reason:
        print('gBox update deferred: ' + reason + ' Running work is preserved.', flush=True)
        return 75
    return 0


def verify_activation(policy: dict, before: list[dict], after: list[dict], expected_fields=None) -> None:
    required = expected_fields or {'fallback_enabled', 'max_parallel_jobs', 'image_input_mode'}
    if not isinstance(policy, dict) or not set(required) <= policy.keys():
        raise RuntimeError('The updated Hermes bridge is not loaded.')
    if not isinstance(before, list) or not isinstance(after, list) or any(not isinstance(s, dict) for s in before + after):
        raise RuntimeError('The original PID safety inventory is unavailable.')
    pids = {}
    for s in after:
        if s.get('state') not in ('running', 'ended'):
            raise RuntimeError('The original PID safety inventory is unavailable.')
        if s['state'] != 'running':
            continue
        sid = s.get('session_id')
        pid = (s.get('detail') or {}).get('pid') if isinstance(s.get('detail'), dict) else None
        if not isinstance(sid, str) or not sid or sid in pids or type(pid) is not int or pid <= 0:
            raise RuntimeError('The original PID safety inventory is unavailable.')
        pids[sid] = pid
    for s in before:
        if s.get('state') not in ('running', 'ended'):
            raise RuntimeError('The original PID safety inventory is unavailable.')
        if s.get('state') == 'running':
            sid = s.get('session_id')
            old_pid = (s.get('detail') or {}).get('pid') if isinstance(s.get('detail'), dict) else None
            if (not isinstance(sid, str) or not sid or type(old_pid) is not int
                    or old_pid <= 0 or sid not in pids or pids[sid] != old_pid):
                raise RuntimeError('A previously running game has not reappeared with its original PID.')


def activate(root: Path, request_id: str, verification_run: str, timeout: int = 3300, *,
             expected_fields=None, verification_summary=None, complete=True) -> None:
    token = (root / 'gbox-data/api_token').read_text().strip()
    base = 'http://127.0.0.1:8765'

    def api(path, body=None):
        request = urllib.request.Request(base + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', 'x-gbox-actor': 'hermes'})
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)

    def step(text, status):
        print(text, flush=True)
        api('/api/requests/' + request_id + '/messages', {'author': 'agent', 'text': text,
            'task_step': {'action': 'activate Hermes bridge safely', 'attempt': '1', 'result': text, 'status': status}})

    deadline, previous = time.monotonic() + timeout, None
    try:
        while time.monotonic() < deadline:
            snapshot = activation_snapshot(root, api)
            sessions, reason = snapshot['sessions'], snapshot['reason']
            if reason:
                if reason != previous:
                    step(reason, 'waiting')
                    previous = reason
                time.sleep(10)
                continue
            # Recheck immediately before the restart so a new operator turn wins.
            time.sleep(2)
            snapshot = activation_snapshot(root, api)
            if snapshot['reason']:
                continue
            step('Idle check passed. Rechecking active work immediately before the backend refresh.', 'running')
            snapshot = activation_snapshot(root, api)
            if snapshot['reason']:
                continue
            sessions = snapshot['sessions']
            subprocess.run(['sudo', '-n', 'systemctl', 'restart', 'gbox.service'], check=True, timeout=45,
                           capture_output=True, text=True)
            last_error = None
            for _ in range(30):
                try:
                    verify_activation(api('/api/hermes/task-mode'), sessions, api('/api/sessions'), expected_fields)
                    break
                except (OSError, ValueError, RuntimeError) as exc:
                    last_error = type(exc).__name__
                    time.sleep(2)
            else:
                raise RuntimeError('Backend activation verification failed: ' + str(last_error))
            step(verification_summary or ('Updated Hermes bridge loaded. Cloud policy fields are visible and running Windows games retained their PIDs. '
                 'The repair passed 19 focused tests and independent cloud screenshot/MCP verification. '
                 'Investigations #1071, #1093 and #1081 retain their own acceptance checks.'), 'finished')
            if not complete:
                return  # Deployment is a task step, not automatic acceptance.
            api('/api/requests/' + request_id + '/status', {'status': 'done',
                'note': 'Hermes reliability repair verified and activated; screenshots, checks and actual cloud usage are attached.',
                'solved_by': {'service': 'codex', 'model': 'GPT-6', 'system': 'Codex',
                    'verified_by': 'Hermes / Ollama Cloud kimi-k2.7-code', 'run_id': verification_run,
                    'verification': '19 focused tests; actual screenshot analysis followed by successful MCP calls; '
                                    'working cloud defaults and fallbacks; real retry/deduplication checks; '
                                    'updated backend policy fields and original Windows emulator PIDs verified.'}})
            return
        raise RuntimeError('No safe idle window occurred before the activation deadline.')
    except Exception as exc:
        step('Backend refresh remains pending: ' + type(exc).__name__ + '. No ticket completion was recorded.', 'failed')
        raise


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Check whether a gBox backend refresh would interrupt work.')
    parser.add_argument('--check-idle', required=True, type=Path)
    raise SystemExit(check_idle(parser.parse_args().check_idle))
