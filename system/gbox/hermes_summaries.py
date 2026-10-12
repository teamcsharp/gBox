"""Post what each ended Hermes run concluded on the tickets it worked on.

A run's final response only reaches the cron delivery target, so a ticket
never said what a run culminated in or why it stopped (#1300). This pass reads
ended runs from Hermes's own databases, takes the tickets the run confirmed
work on (`hermes_tasks.confirmed_request_ids`) and posts one reply per run and
ticket. The reply prefix on the ticket is the duplicate guard.
"""
from __future__ import annotations

import json
import re
import time

from . import hermes_delivery, hermes_tasks

MARKER = re.compile(r'^Hermes run ([0-9a-f]{12}) ended', re.M)
BACKFILL = 6 * 3600   # runs that ended this long before the first pass are history
BODY_LIMIT = 1800
ROWS = 500   # maintenance scripts run every few minutes and outnumber agent runs


def _response(home, job_id, finished, state, session_id):
    """The run's final response: its cron output file, else the last assistant text."""
    text = hermes_tasks._script_output(home, job_id, finished)
    if '## Response' in text:
        return text.split('## Response', 1)[1].strip()
    row = state.execute("SELECT content FROM messages WHERE session_id=? AND role='assistant' "
                        "AND content IS NOT NULL AND content != '' ORDER BY id DESC LIMIT 1",
                        (session_id,)).fetchone()
    return (row['content'] or '').strip() if row else ''


def _session_at(state, job_id, started):
    """The run's conversation. hermes_tasks._session only looks at a job's 10 newest."""
    rows = state.execute("SELECT * FROM sessions WHERE source='cron' AND id LIKE ? "
                         "AND started_at BETWEEN ? AND ?", (f'cron_{job_id}_%', started - 120, started + 120)).fetchall()
    return min(rows, key=lambda s: abs(s['started_at'] - started)) if rows else None


def _outcome(response, error):
    for line in response.splitlines():
        if '[CRON_FAILURE]' in line:
            nxt = response.split(line, 1)[1].strip().splitlines()
            return 'reported failure: ' + (nxt[0].strip() if nxt else line.strip())[:300]
    if error:
        return 'error: ' + error.strip().splitlines()[0][:300]
    if response.strip() == '[SILENT]':
        return 'reported nothing new ([SILENT])'
    lines = [l.strip() for l in response.splitlines() if l.strip()]
    if not lines:
        return 'no final response was recorded'
    outcome = lines[0].strip('# ').strip()[:300]
    if lines[0].startswith('#'):
        # A bare ticket heading says nothing about the result; add the first sentence under it.
        first = next((l for l in lines[1:] if not l.startswith('#')), '')
        first = re.split(r'(?<=[.!?])\s', first.lstrip('-* ').replace('**', ''), maxsplit=1)[0][:300]
        if first:
            outcome += '. ' + first
    return outcome


def _trim(text, limit=BODY_LIMIT):
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rsplit('\n', 1)[0] + '\n... (trimmed)'


def summary(run, response, numbers, own_reply):
    """Reply text for one run on one ticket."""
    minutes = max(0, round(((run['finished'] or 0) - (run['started'] or 0)) / 60))
    route = '/'.join(p for p in (run.get('provider'), run.get('model')) if p) or 'unknown route'
    text = (f"Hermes run {run['id'][:12]} ended: {run['state']} after {minutes} min "
            f"({route}, {run['tools']} tool calls). Outcome: {_outcome(response, run.get('error'))}")
    if numbers:
        text += '\nThe same run also worked on ' + ', '.join(f'#{n}' for n in numbers) + '.'
    if not own_reply and response and response.strip() != '[SILENT]':
        text += '\n\nThe run posted no reply here itself. Its final response:\n' + _trim(response)
    return text


def ended_runs(home=None, limit=ROWS, since=None):
    """Ended agent runs with their session and confirmed tickets, newest first."""
    home = home or hermes_tasks._home()
    db = hermes_tasks._db(home / 'cron' / 'executions.db')
    state = hermes_tasks._db(home / 'state.db')
    if not db or not state:
        for handle in (db, state):
            if handle:
                handle.close()
        return []
    try:
        rows = db.execute("SELECT id,job_id,status,started_at,finished_at,error FROM executions "
                          "WHERE started_at IS NOT NULL AND finished_at IS NOT NULL "
                          "AND status NOT IN ('claimed','running') ORDER BY finished_at DESC LIMIT ?",
                          (limit,)).fetchall()
        out = []
        for r in rows:
            started, finished = hermes_tasks._stamp(r['started_at']), hermes_tasks._stamp(r['finished_at'])
            if started is None or finished is None or (since is not None and finished < since):
                continue
            session = _session_at(state, r['job_id'], started)
            if not session:
                continue   # scheduler-only maintenance: no conversation, no ticket work
            tickets = hermes_tasks._owned_requests(state, session['id'])
            if not tickets:
                continue
            tools = state.execute("SELECT count(*) FROM messages WHERE session_id=? AND role='tool'",
                                  (session['id'],)).fetchone()[0]
            out.append({'id': r['id'], 'job_id': r['job_id'], 'state': r['status'], 'error': r['error'],
                        'started': started, 'finished': finished, 'model': session['model'],
                        'provider': session['billing_provider'] if 'billing_provider' in session.keys() else None,
                        'tools': tools, 'request_ids': tickets,
                        'response': _response(home, r['job_id'], finished, state, session['id'])})
        return out
    finally:
        db.close()
        state.close()


def reconcile(api, *, home=None, now=None):
    """Post one summary per ended run on each ticket it confirmed work on."""
    now = time.time() if now is None else now
    path = hermes_delivery.state_dir() / 'summaries.json'
    try:
        saved = json.loads(path.read_text())
    except (OSError, ValueError):
        saved = {}
    since = saved.setdefault('since', now - BACKFILL)
    posted_runs = set(saved.get('posted', []))
    posted, errors = [], []
    reports = {}
    for run in ended_runs(home, since=since):
        if run['finished'] < since or run['id'] in posted_runs:
            continue
        complete = True
        for rid in run['request_ids']:   # read every ticket first so replies can name the others
            if rid not in reports:
                try:
                    reports[rid] = api('/api/requests/' + rid)
                except Exception as error:   # one unreachable ticket must not stop the others
                    errors.append(f'{rid}: {type(error).__name__}')
                    complete = False
        for rid in run['request_ids']:
            report = reports.get(rid)
            if report is None:
                continue
            messages = report.get('messages', [])
            if run['id'][:12] in MARKER.findall('\n'.join(m.get('text') or '' for m in messages)):
                continue
            own = any(m.get('author') == 'agent' and run['started'] <= (m.get('ts') or 0) <= run['finished'] + 60
                      for m in messages)
            numbers = []
            for other in run['request_ids']:
                if other != rid:
                    numbers.append((reports.get(other) or {}).get('number') or other)
            text = summary(run, run['response'], numbers, own)
            try:
                api(f'/api/requests/{rid}/messages', {'author': 'agent', 'text': text, 'task_step': {
                    'action': 'record Hermes run outcome', 'attempt': '1',
                    'result': f"run {run['id'][:12]} {run['state']}", 'status': 'finished'}})
            except Exception as error:
                errors.append(f'{rid}: {type(error).__name__}')
                complete = False
                continue
            messages.append({'author': 'agent', 'text': text, 'ts': now})
            posted.append({'run': run['id'], 'request_id': rid, 'number': report.get('number')})
        if complete:
            posted_runs.add(run['id'])
    saved['posted'] = sorted(posted_runs)[-500:]
    saved['checked_at'] = now
    with hermes_delivery.locked('summaries'):
        path.write_text(json.dumps(saved, indent=2))
    return {'posted': posted, 'errors': errors}


def cap_question(streak):
    return (f"Hermes worked this ticket in the last {streak['runs']} inbox runs in a row without finishing it, "
            "so it is pausing here (blocked) and moving on to other requests. Reply on this ticket with what "
            "to do next (what is still wrong, a narrower goal, or \"keep going\"); your reply reopens it for "
            "the next run.")


def enforce_cap(api, *, runs=None):
    """Ask the operator about a ticket the inbox job keeps taking (#1300 gap 3).

    list_requests only advises a run to skip a capped ticket. Here a ticket that
    reached the streak cap is set to blocked with a question, once per streak;
    the operator's reply reopens it (server req_message) and restarts its count.
    """
    path = hermes_delivery.state_dir() / 'capped.json'
    try:
        saved = json.loads(path.read_text())
    except (OSError, ValueError):
        saved = {}
    runs = hermes_tasks.list_runs(hermes_tasks.MAX_RUNS) if runs is None else runs
    rows = api('/api/requests?status=open,in_progress')
    last = {r['id']: max([m.get('ts') or 0 for m in r.get('messages') or []
                          if m.get('author') == 'operator'] or [0.0]) for r in rows}
    asked = saved.setdefault('asked', {})
    blocked, errors = [], []
    for rid, streak in hermes_tasks.ticket_streaks(runs, last).items():
        latest = streak['run_ids'][0]
        if rid not in last or asked.get(rid) == latest:
            continue
        try:
            api(f'/api/requests/{rid}/status', {'status': 'blocked', 'note': cap_question(streak)})
        except Exception as error:
            errors.append(f'{rid}: {type(error).__name__}')
            continue
        asked[rid] = latest
        blocked.append({'request_id': rid, 'runs': streak['runs']})
    with hermes_delivery.locked('capped'):
        path.write_text(json.dumps(saved, indent=2))
    return {'blocked': blocked, 'errors': errors}
