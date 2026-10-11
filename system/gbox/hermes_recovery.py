"""Bounded one-shot recovery using Hermes's durable conversation and workspace."""
from __future__ import annotations

import json
import re
import sqlite3
import time

from . import hermes_delivery, hermes_quota, hermes_task_mode, hermes_tasks

MAX_RESUMES = 3
WINDOW = 86400


def _path():
    return hermes_delivery.state_dir() / 'provider-recovery.json'


def _read():
    path = _path()
    return json.loads(path.read_text()) if path.exists() else {'schema_version': 1, 'jobs': {}}


def _save(data):
    # Readers must never observe a partial checkpoint after power loss/restart.
    path = _path()
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temporary.replace(path)


def checkpoint(run, job, session, requests, *, now):
    """Save identifiers, not message content or secrets; Hermes owns the transcript."""
    if (not job.get('id') or not job.get('name', '').startswith('gBox ')
            or job.get('no_agent') or (job.get('schedule') or {}).get('kind') != 'once'):
        return
    requests = sorted({r for r in requests if isinstance(r, str) and re.fullmatch(r'[0-9a-f]{16}', r)})
    if not requests:
        return  # A scheduler claim or discovery-only run must not claim a ticket.
    with hermes_delivery.locked('provider-recovery'):
        data = _read()
        old = data['jobs'].get(job['id'], {})
        if old.get('failed_run_id') == run['id']:
            return
        attempts = [x for x in old.get('resumes', []) if x.get('at', 0) >= now - WINDOW]
        data['jobs'][job['id']] = {
            'job_id': job['id'], 'failed_run_id': run['id'],
            'session_id': session['id'] if session else None,
            'request_ids': requests, 'checkpoint_at': now,
            'resumes': attempts, 'status': 'pending',
            'route': hermes_quota.route({'provider': session['billing_provider'] if session
                        and 'billing_provider' in session.keys() else job.get('provider'),
                        'model': session['model'] if session else job.get('model')}),
        }
        # Only recent recovery bookkeeping is retained; original runs stay in Hermes.
        data['jobs'] = {k: v for k, v in data['jobs'].items()
                        if v.get('checkpoint_at', 0) >= now - 7 * WINDOW}
        _save(data)


def _request_state(request_id):
    from .hermes_availability import _api
    return _api('/api/requests/' + request_id).get('status')


def _active_requests():
    """Read all active claims, rather than the Tasks panel's limited recent list."""
    home = hermes_task_mode._home()
    db, state = hermes_tasks._db(home / 'cron/executions.db'), hermes_tasks._db(home / 'state.db')
    try:
        if not db:
            return set()
        if not state:
            if db.execute("SELECT 1 FROM executions WHERE status IN ('claimed','running') LIMIT 1").fetchone():
                raise RuntimeError('Active request ownership is unavailable; recovery was deferred')
            return set()
        owned = set()
        for run in db.execute("SELECT job_id,started_at FROM executions WHERE status IN ('claimed','running')"):
            session = hermes_tasks._session(state, run['job_id'], hermes_tasks._stamp(run['started_at']))
            if session:
                owned.update(hermes_tasks._owned_requests(state, session['id']))
        return owned
    finally:
        if db:
            db.close()
        if state:
            state.close()


def _latest_run(job_id):
    db = hermes_tasks._db(hermes_task_mode._home() / 'cron/executions.db')
    try:
        if not db:
            return None
        row = db.execute('SELECT id FROM executions WHERE job_id=? AND started_at IS NOT NULL '
                         'ORDER BY started_at DESC LIMIT 1', (job_id,)).fetchone()
        return row['id'] if row else None
    finally:
        if db:
            db.close()


def recover(feedback, *, now=None):
    """Re-arm at most one failed occurrence per tick; never repin benchmark jobs."""
    now = time.time() if now is None else now
    jobs = {j['id']: j for j in hermes_task_mode._jobs() if j.get('id')}
    config = hermes_task_mode._config()
    routes = hermes_quota.routes(config, feedback.get('routes') or [])
    eligible = [r for r in routes if feedback.get('cooldowns', {}).get(r['provider'] + '/' + r['model'], 0) <= now]
    if not _path().exists():
        return {'status': 'no_pending_recovery'}
    with hermes_delivery.locked('provider-recovery'):
        data = _read()
        try:
            active_requests = _active_requests()
        except (OSError, RuntimeError, sqlite3.Error):
            return {'status': 'active_ownership_unknown'}
        outcome = {'status': 'no_pending_recovery'}
        for item in sorted(data['jobs'].values(), key=lambda x: x['checkpoint_at']):
            if item['status'] in ('resumed', 'resolved', 'superseded', 'dispatch_uncertain'):
                continue
            job = jobs.get(item['job_id'])
            if not job:
                item['status'] = 'job_missing'
                continue
            if job.get('enabled') or hermes_task_mode._active(job['id']):
                item['status'] = 'resumed'
                item['resume_source'] = 'already_queued_or_running'
                continue
            latest = _latest_run(job['id'])
            if latest and latest != item['failed_run_id']:
                item['status'] = 'superseded'
                continue  # A later occurrence already continued this old checkpoint.
            # An operator may have paused task mode after this failed activation.
            if job.get('name', '').startswith(hermes_task_mode.NAME + ' activation '):
                inbox = hermes_task_mode._job() or {}
                if not inbox.get('enabled'):
                    item['status'] = 'task_mode_disabled'
                    continue
            if any(job.get(k) for k in ('model', 'provider', 'base_url')):
                item['status'] = 'waiting_pinned_provider'
                outcome = {'status': item['status'], 'job_id': job['id']}
                continue
            if not eligible:
                item['status'] = 'waiting_provider'
                outcome = {'status': item['status']}
                continue
            if set(item['request_ids']) & active_requests:
                item['status'] = 'request_owned_by_active_run'
                continue
            attempts = [x for x in item['resumes'] if x['at'] >= now - WINDOW]
            if len(attempts) >= MAX_RESUMES:
                item['status'] = 'recovery_budget_exhausted'
                outcome = {'status': item['status'], 'job_id': job['id']}
                continue
            try:
                remaining = [rid for rid in item['request_ids'] if _request_state(rid) in ('open', 'in_progress')]
            except (OSError, ValueError, RuntimeError):
                item['status'] = 'request_verification_deferred'
                continue  # Never reopen a ticket just because its API could not be read.
            if not remaining:
                item['status'] = 'resolved'
                continue
            # Save the launch intent first. A timeout/crash may have launched work;
            # do not repeat an uncertain occurrence automatically on restart.
            item.update(status='dispatch_uncertain', resume_request_ids=remaining)
            item['resumes'] = attempts + [{'at': now, 'failed_run_id': item['failed_run_id']}]
            _save(data)
            try:
                hermes_task_mode._run('edit', job['id'], '--continuity')
                hermes_task_mode._run('resume', job['id'], '--run-now')
            except (OSError, RuntimeError):
                outcome = {'status': 'dispatch_uncertain', 'job_id': job['id']}
            else:
                item.update(status='resumed', resumed_at=now)
                outcome = {'status': 'resumed_checkpoint', 'job_id': job['id'], 'request_ids': remaining}
            break
        _save(data)
        return outcome


def status():
    if not _path().exists():
        return []
    try:
        with hermes_delivery.locked('provider-recovery'):
            return [{k: item.get(k) for k in ('job_id', 'request_ids', 'status', 'checkpoint_at', 'session_id')}
                    | {'resume_count': len(item.get('resumes', []))} for item in _read()['jobs'].values()]
    except (OSError, ValueError):
        return [{'status': 'checkpoint_temporarily_unavailable'}]
