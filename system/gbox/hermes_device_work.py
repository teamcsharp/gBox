"""Read-only device work evidence, separate from machine polling and dispatch.

An inference response, an ended cron execution, a published PR and a resolved
request are distinct facts. Never turn a model name or the current route into
historical device attribution. Missing evidence remains explicit.
"""
from __future__ import annotations

import json
import platform
import re
import sqlite3
import time
from pathlib import Path
from typing import Literal

from . import hermes_delivery as D, hermes_providers as P, hermes_tasks as T

LIMIT = 2000
ACTIVE = {'running', 'claimed', 'queued'}
RID = re.compile(r'[0-9a-f]{16}\Z')
SHA = re.compile(r'[0-9a-f]{40}\Z')


def _read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {} if default is None else default


def friendly(name):
    return {'sparkdeux': 'Spark2', 'unknown': 'Unknown device', 'mixed': 'Multiple inference devices'}.get(
        (name or '').casefold(), name or 'Unknown device')


def _nodes():
    from . import hermes_pool, hermes_local
    settings = hermes_local.settings()
    nodes = hermes_pool.node_settings(settings)
    if not nodes:
        nodes = {settings.host_name: settings}
    return [{'id': name, 'name': friendly(name), 'provider': cfg.provider,
             'model': cfg.model, 'endpoints': {cfg.proxy_url.rstrip('/'), cfg.upstream.rstrip('/')}}
            for name, cfg in nodes.items()]


def _device(call, nodes):
    """Observed endpoint first; a named provider must map uniquely to a node."""
    endpoint = (call.get('base_url') or '').rstrip('/')
    candidates = [n for n in nodes if endpoint and endpoint in n['endpoints']]
    if not candidates and not endpoint:
        candidates = [n for n in nodes if call.get('provider') == n['provider']
                      and call.get('provider') not in ('custom', 'local', 'ollama', 'vllm')]
    if len(candidates) == 1:
        n = candidates[0]
        return n['id'], 'logged_endpoint' if endpoint in n['endpoints'] else 'logged_named_provider'
    provider = call.get('provider')
    if provider and not P.is_local(provider, endpoint) and provider != 'custom':
        return 'provider:' + provider, 'logged_provider'
    return 'unknown', 'unknown_device'


def observed_routes(session, nodes):
    rows = {}
    for call in (session or {}).get('calls', []):
        if call.get('state') != 'ok':
            continue
        device, source = _device(call, nodes)
        key = (device, call.get('provider'), call.get('model'))
        at = call.get('completed_at') or call.get('ts')
        row = rows.setdefault(key, {'device_id': device, 'name': friendly(device),
            'provider': key[1], 'model': key[2], 'source': source, 'calls_ok': 0,
            'first': at, 'last': at})
        row['calls_ok'] += 1
        row['first'], row['last'] = min(row['first'], at), max(row['last'], at)
    return list(rows.values())


def _scan(now):
    scan = P.scanner()
    scan.refresh(now, P._tz())
    with scan.lock:
        return {key: dict(row, calls=[dict(c) for c in row['calls']]) for key, row in scan.sessions.items()}


def load_runs(since, now):
    """Read all active executions plus a bounded window, with visible coverage."""
    home = T._home()
    db = state = None
    notes = []
    try:
        db, state = T._db(home / 'cron/executions.db'), T._db(home / 'state.db')
        if not db:
            return [], ['Hermes execution database is unavailable.']
        # ISO-8601 strings may carry different offsets; SQLite converts both to UTC.
        columns = 'id,job_id,status,started_at,finished_at,error'
        active = db.execute(f'SELECT {columns} FROM executions WHERE started_at IS NOT NULL '
                            "AND status IN ('running','claimed') ORDER BY started_at DESC").fetchall()
        rows = db.execute(f'SELECT {columns} FROM executions '
            "WHERE started_at IS NOT NULL AND status NOT IN ('running','claimed') AND "
            "CAST(strftime('%s',COALESCE(finished_at,started_at)) AS REAL)>=? "
            "ORDER BY started_at DESC LIMIT ?",
            (since, LIMIT + 1)).fetchall()
        if len(rows) > LIMIT:
            notes.append(f'Execution history is limited to {LIMIT} rows; counts cover returned rows only.')
        names = T._jobs(home)
        from . import hermes_work_queue
        claims = hermes_work_queue.claims()
        assignments = {i.get('job_id'): i for i in hermes_work_queue._read().get('items', {}).values()
                       if i.get('job_id') and i.get('dispatch_state') == 'queued'}
        out = []
        for raw in [*active, *rows[:LIMIT]]:
            start, finish = T._stamp(raw['started_at']), T._stamp(raw['finished_at'])
            if not start or start > now or (finish and finish < since):
                continue
            session = T._session(state, raw['job_id'], start) if state else None
            messages = [dict(m) for m in state.execute('SELECT role,content,tool_name,tool_call_id,tool_calls,timestamp '
                'FROM messages WHERE session_id=? ORDER BY id', (session['id'],)).fetchall()] if session else []
            rids = set(T.confirmed_request_ids(messages))
            if raw['status'] in ACTIVE and raw['job_id'] in claims:
                rids.add(claims[raw['job_id']])
            assigned = assignments.get(raw['job_id']) or {}
            assignment = None
            if (raw['status'] in ACTIVE and assigned.get('inference_node')
                    and abs(start - (assigned.get('last_dispatched') or 0)) < 120):
                assignment = {'device_id': assigned['inference_node'], 'source': 'current_queue_assignment',
                    'provider': (assigned.get('route') or {}).get('provider'),
                    'model': (assigned.get('route') or {}).get('model')}
            out.append({'id': raw['id'], 'job_id': raw['job_id'],
                'title': names.get(raw['job_id'], raw['job_id']), 'state': raw['status'],
                'kind': 'hermes' if session else 'maintenance', 'assignment': assignment,
                'started': start, 'finished': finish, 'session_id': session['id'] if session else None,
                'request_ids': sorted(rids), 'recorded_outcomes': response_outcomes(messages),
                'current_action': P.redact(T._last_action(state, session['id'])) if session else
                ('Maintenance is running' if raw['status'] in ACTIVE else 'Execution ended without an inference session'),
                'error': P.redact(raw['error'] or '')[:500], 'tokens_in': T._usage(session)['tokens_in'] if session else None,
                'tokens_out': T._usage(session)['tokens_out'] if session else None})
        if not state:
            notes.append('Hermes session database is unavailable; ticket and model joins are unknown.')
        return out, notes
    except (OSError, ValueError, sqlite3.Error) as exc:
        return [], ['Hermes execution evidence is unavailable: ' + type(exc).__name__]
    finally:
        if db: db.close()
        if state: state.close()


def response_outcomes(messages):
    """Accept only exact successful tool responses, not assistant claims."""
    from . import hermes_accounting as A
    try:
        calls = A._calls(messages)
    except (A.Deferred, TypeError, AttributeError):
        return []
    out = []
    for call in calls:
        if not call['has_response'] or call['wrapped_ambiguous'] or call['rejected']:
            continue
        action = call['name'].removeprefix('mcp__gbox__')
        args, result = call['args'], call['result']
        if not isinstance(args, dict) or not isinstance(result, dict):
            continue
        rid = args.get('request_id')
        if not isinstance(rid, str) or not RID.fullmatch(rid):
            continue
        response = [m for m in messages if m.get('role') == 'tool' and m.get('tool_call_id') == call['call_id']
                    and (m.get('tool_name') or '').removeprefix('mcp__gbox__') == action]
        if len(response) != 1 or not isinstance(response[0].get('timestamp'), (int, float)):
            continue
        if (action == 'set_request_status' and args.get('status') == 'done'
                and (result.get('request_id') or result.get('id')) == rid and result.get('status') == 'done'):
            transition = result.get('status_transition') or {}
            changed = (transition.get('changed') is True and transition.get('previous') in ('open', 'in_progress', 'blocked')
                       and transition.get('status') == 'done' and type(transition.get('audit_seq')) is int
                       and transition['audit_seq'] > 0)
            out.append({'kind': 'request_resolved' if changed else 'request_status', 'request_id': rid, 'status': 'done',
                'title': 'Request completion accepted' if changed else 'Done status acknowledged; transition unproved',
                'verified': changed, 'observed_at': response[0]['timestamp'],
                'evidence': {'source': 'successful_set_request_status_response', 'call_id': call['call_id'],
                    'transition': transition,
                    'boundary': 'Server recorded a new completion; acceptance evidence remains on the request.' if changed else
                                'No new completion is credited: this can be a repeated done call or a legacy response.'}})
    return out


def publications():
    """Latest legacy receipt plus immutable publication receipts, deduplicated."""
    rows = {}
    root = D.state_dir()
    for path in [*root.glob('????????????????.json'), *root.glob('publications/*.json')]:
        row = _read(path)
        if (not RID.fullmatch(str(row.get('request_id') or '')) or not SHA.fullmatch(str(row.get('commit') or ''))
                or not row.get('published_at') or type(row.get('pr_number')) is not int
                or row.get('url') != f'https://github.com/{D.REPOSITORY}/pull/{row["pr_number"]}'):
            continue
        key = (row['pr_number'], row['commit'])
        if key not in rows or row.get('provenance'):
            rows[key] = row
    return list(rows.values())


def publication_provenance(request_id, now=None):
    """Snapshot observed contributors to this request, never the global route."""
    now = time.time() if now is None else now
    out = {'recorded_at': now, 'request_id': request_id, 'execution_host': platform.node(),
           'source': 'Hermes execution/session database and successful model-call log',
           'scope': 'Observed model assistance; validation ran on execution_host. Review and merge are separate.',
           'runs': [], 'status': 'unknown'}
    try:
        runs, notes = load_runs(now - 7 * 86400, now)
        sessions, nodes = _scan(now), _nodes()
        for run in runs:
            if request_id in run['request_ids']:
                routes = observed_routes(sessions.get(run['session_id']), nodes)
                if routes:
                    out['runs'].append({'run_id': run['id'], 'session_id': run['session_id'],
                        'started': run['started'], 'routes': routes})
        out['notes'] = notes + ['Retained logs cover at most seven days; unrecorded earlier contributors are unknown.']
        out['status'] = 'observed' if out['runs'] else 'unknown'
    except (OSError, ValueError, sqlite3.Error, TypeError):
        out['notes'] = ['Run provenance was unavailable at publication; no device was inferred.']
    return out


def pr_note(provenance):
    lines = ['Device contribution evidence:', '']
    routes = {}
    for run in provenance.get('runs', []):
        for row in run.get('routes', []):
            key = (row['device_id'], row.get('provider'), row.get('model'))
            routes.setdefault(key, []).append(run['run_id'])
    def cell(value):
        return str(value or 'unknown').replace('|', '/').replace('\n', ' ').replace('`', "'")
    if routes:
        lines += ['| Inference device | Provider | Model | Recorded runs |', '| --- | --- | --- | --- |']
        for (device, provider, model), ids in routes.items():
            lines.append(f'| {cell(friendly(device))} | {cell(provider)} | {cell(model)} | {cell(", ".join(ids))} |')
    else:
        lines += ['Inference device/model: **unknown**. No successful model call was linked to this request.']
    lines += ['', f'Validation execution host: `{cell(provenance.get("execution_host"))}`.',
              'Attribution describes recorded model assistance to this request, not sole authorship or task completion.',
              'Tests, publication, review, merge, deployment and gameplay acceptance remain separate evidence.', '']
    return '\n'.join(lines) + '\n'


def _empty_metrics():
    return dict(active_runs=0, ended_runs=0, failed_runs=0, prs_opened=0, prs_merged=0,
        requests_resolved=0, calls_ok=None, calls_failed=None, tokens_in=None, tokens_out=None,
        wall_s=0.0, peak_concurrency=0, observed_run_count=0, inference_wall_s=None,
        mean_call_s=None, call_success_rate=None, ended_runs_with_delivery=0, ended_run_delivery_rate=None)


def _peak(intervals):
    points = sorted([(a, 1) for a, b in intervals if b > a] + [(b, -1) for a, b in intervals if b > a])
    current = maximum = 0
    for _, delta in points:
        current += delta
        maximum = max(maximum, current)
    return maximum


def aggregate(runs, sessions, nodes, receipts, requests, merges, calls, since, now):
    """Pure aggregation: no dispatch, health probes, GitHub calls or inference."""
    devices = {n['id']: {k: n[k] for k in ('id', 'name', 'provider', 'model')} | {'metrics': _empty_metrics()}
               for n in nodes}
    out, by_id = [], {}
    def ensure(device):
        return devices.setdefault(device, {'id': device, 'name': friendly(device), 'provider': None,
            'model': None, 'metrics': _empty_metrics()})
    for original in runs:
        run = dict(original)
        routes = observed_routes(sessions.get(run.get('session_id')), nodes)
        ids = {r['device_id'] for r in routes}
        device = next(iter(ids)) if len(ids) == 1 else 'mixed' if ids else 'unknown'
        assignment = run.get('assignment') or {}
        if not routes and run['state'] in ACTIVE and assignment.get('device_id'):
            device = assignment['device_id']
        if original.get('device_id'):
            device = original['device_id']
        accepted = [o for o in run.pop('recorded_outcomes', []) if since <= o['observed_at'] <= now
                    and requests.get(o['request_id'], {}).get('status') == 'done'
                    and (o['kind'] != 'request_resolved' or requests[o['request_id']].get('completed') ==
                         o['evidence']['transition'].get('at'))]
        run.update(device_id=device, updated=now, outcomes=accepted,
            attribution={'source': 'successful_model_calls' if routes else assignment.get('source') or original.get('attribution_source', 'unknown'),
                         'routes': routes, 'assignment': assignment,
                         'scope': 'Observed inference contribution; tool execution may run on another worker.' if routes else
                                  'Assignment only; no successful model call was observed.'})
        tickets = [{k: requests[rid].get(k) for k in ('id', 'number', 'title', 'status')}
                   for rid in run.get('request_ids', []) if rid in requests]
        run['tickets'] = tickets
        if len(tickets) == 1:
            run['title'] = f'#{tickets[0].get("number")}: {tickets[0].get("title") or run["title"]}'
        ensure(device)
        out.append(run); by_id[run['id']] = run
    # Receipts assign delivery to exact captured run IDs. Legacy receipts only
    # attach when one confirmed request run contains the publication timestamp.
    for rec in receipts:
        stamp = rec['published_at']
        candidates = [by_id[r['run_id']] for r in rec.get('provenance', {}).get('runs', []) if r.get('run_id') in by_id]
        candidates = [r for r in candidates if r['started'] <= stamp <= (r.get('finished') or now) + 5]
        if not candidates:
            candidates = [r for r in out if rec['request_id'] in r.get('request_ids', [])
                          and r['started'] <= stamp <= (r.get('finished') or now) + 5]
        if len(candidates) != 1:
            continue
        run = candidates[0]
        evidence = {'source': 'verified_publication_receipt', 'commit': rec['commit'],
                    'validation': rec.get('checks', []), 'provenance': rec.get('provenance', {})}
        if since <= stamp <= now:
            run['outcomes'].append({'kind': 'pr_published', 'title': f'PR #{rec["pr_number"]} published for review',
                'url': rec['url'], 'request_id': rec['request_id'], 'status': 'published', 'verified': True,
                'observed_at': stamp, 'evidence': evidence})
        merge = (merges.get('observations') or {}).get(str(rec['pr_number'])) or {}
        merged_at = T._stamp(merge.get('mergedAt'))
        if (merge.get('state') == 'MERGED' and merge.get('headRefOid') == rec['commit']
                and merge.get('baseRefName') == 'main' and merged_at and since <= merged_at <= now):
            run['outcomes'].append({'kind': 'pr_merged', 'title': f'PR #{rec["pr_number"]} merged to main',
                'url': rec['url'], 'request_id': rec['request_id'], 'status': 'merged', 'verified': True,
                'observed_at': merged_at, 'evidence': evidence | {'github_observation': merge,
                    'boundary': 'Contributor evidence only; reviewer/merger identity is not attributed to the model.'}})
        elif (merge.get('state') == 'MERGED' and merge.get('baseRefName') == 'main'
                and merged_at and since <= merged_at <= now and merge.get('headRefOid') != rec['commit']):
            run['outcomes'].append({'kind': 'pr_reviewed_merge',
                'title': f'PR #{rec["pr_number"]} merged at a different head; contribution unverified',
                'url': rec['url'], 'request_id': rec['request_id'], 'status': 'merged_at_different_head',
                'verified': False, 'observed_at': merged_at,
                'evidence': evidence | {'github_observation': merge,
                    'boundary': 'Additional commits/review changed the head. No merge credit without exact-head or ancestry evidence.'}})
    # A currently done request alone cannot prove which device resolved it.
    # Its completion is shown as context, never counted as a model delivery.
    for run in out:
        for ticket in run['tickets']:
            if ticket.get('status') == 'done' and not any(o.get('request_id') == ticket['id'] for o in run['outcomes']):
                run['outcomes'].append({'kind': 'request_status', 'title': f'Request #{ticket.get("number")} is done',
                    'request_id': ticket['id'], 'status': 'done', 'verified': False, 'observed_at': now,
                    'evidence': {'source': 'current_request_status', 'boundary': 'Resolving run/device not established.'}})
    intervals = {}
    for run in out:
        m = ensure(run['device_id'])['metrics']
        m['observed_run_count'] += 1
        m['active_runs' if run['state'] in ACTIVE else 'ended_runs'] += 1
        m['failed_runs'] += run['state'] in ('failed', 'error')
        a, b = max(since, run['started']), min(now, run.get('finished') or now)
        if run['state'] not in ACTIVE and not run.get('finished'):
            b = a  # no invented duration for missing finish timestamps
        intervals.setdefault(run['device_id'], []).append((a, b))
        m['wall_s'] += max(0.0, b-a)
    for device, rows in intervals.items():
        devices[device]['metrics']['peak_concurrency'] = _peak(rows)
    for device, row in devices.items():
        m = row['metrics']
        matched = [c for c in calls if c.get('host_name') == device and since <= (c.get('ts') or 0) <= now]
        if matched:
            ok = [c for c in matched if c.get('status') == 'ok']
            incoming = sum(c['prompt_tokens'] for c in ok) if all(isinstance(c.get('prompt_tokens'), (int, float)) for c in ok) else None
            outgoing = sum(c['completion_tokens'] for c in ok) if all(isinstance(c.get('completion_tokens'), (int, float)) for c in ok) else None
            duration = sum(c['duration_s'] for c in ok) if all(isinstance(c.get('duration_s'), (int, float)) for c in ok) else None
            m.update(calls_ok=len(ok), calls_failed=sum(c.get('status') == 'error' for c in matched),
                tokens_in=incoming, tokens_out=outgoing,
                inference_wall_s=round(duration, 3) if duration is not None else None)
            attempts = m['calls_ok'] + m['calls_failed']
            m['call_success_rate'] = m['calls_ok'] / attempts if attempts else None
            m['mean_call_s'] = m['inference_wall_s'] / len(ok) if ok and duration is not None else None
        row['model_source'] = 'current_configuration' if row.get('model') else 'unknown'
        row['models_seen'] = sorted({c['model'] for c in matched if c.get('model')})
        outcomes = [o for r in out if r['device_id'] == device for o in r['outcomes'] if o['verified']]
        m['prs_opened'] = len({o['url'] for o in outcomes if o['kind'] == 'pr_published'})
        m['prs_merged'] = len({o['url'] for o in outcomes if o['kind'] == 'pr_merged'})
        m['requests_resolved'] = len({o['request_id'] for o in outcomes if o['kind'] == 'request_resolved'})
        m['ended_runs_with_delivery'] = sum(r['state'] not in ACTIVE and any(o['verified'] and o['kind'] in
            ('pr_published', 'pr_merged', 'request_resolved') for o in r['outcomes'])
            for r in out if r['device_id'] == device)
        m['ended_run_delivery_rate'] = m['ended_runs_with_delivery'] / m['ended_runs'] if m['ended_runs'] else None
        m['wall_s'] = round(m['wall_s'], 3)
    return list(devices.values()), out


def summary(store, window='today', now=None):
    if window not in P.WINDOWS:
        raise ValueError('window must be today or 7d')
    now = time.time() if now is None else now
    since = P.window_start(window, now, P._tz())
    runs, notes = load_runs(since, now)
    try:
        sessions = _scan(now)
    except (OSError, ValueError):
        sessions = {}; notes.append('Provider logs are unavailable; inference devices remain unknown.')
    requests = {rid: row for rid in {rid for r in runs for rid in r['request_ids']}
                if (row := store.get('request', rid))}
    from . import llm_proxy
    calls = [c for c in llm_proxy.read_log(since) if since <= (c.get('ts') or 0) <= now]
    devices, rows = aggregate(runs, sessions, _nodes(), publications(), requests,
                             _read(D.state_dir() / 'merges.json'), calls, since, now)
    notes += ['Model-call counts come from the retained local proxy ledger; they are not completed tasks.',
              'Ended executions are not completed requests. Current done status is not credited to a device without a resolving-run receipt.',
              'Run wall seconds sum overlapping executions and are not GPU time. Call duration includes proxy wait/handling; tokens per second is not reported.',
              'Log rotation and legacy receipts may omit historical attribution or merge evidence; unknown counts are null.',
              'PR merges are credited only when a recorded GitHub main-merge observation matches the published commit.',
              'Ended-run delivery rate is the fraction of returned ended runs with a recorded publication, exact-head merge, or new request completion in this window; it is not an acceptance score.']
    return {'generated_at': now, 'window': {'key': window, 'label': P.WINDOWS[window], 'start': since, 'end': now},
        'coverage': {'partial': True, 'notes': notes, 'sources': ['Hermes executions and sessions',
            'successful model-call logs', 'local proxy call ledger', 'publication receipts', 'recorded GitHub merge observations'],
            'observed_bounds': {'runs_start': min((r['started'] for r in rows), default=None),
                'calls_start': min((c.get('ts') for c in calls if c.get('ts')), default=None),
                'calls_end': max((c.get('ts') for c in calls if c.get('ts')), default=None)},
            'run_limit': LIMIT, 'metrics_scope': 'Observed evidence in the selected window, not lifetime totals.'},
        'devices': devices, 'runs': rows}


def install(app, store, auth):
    from fastapi import Depends
    import threading
    cache, lock = {}, threading.Lock()

    @app.get('/api/tasks/device-work')
    def device_work(window: Literal['today', '7d'] = 'today', actor=Depends(auth)):
        # One read-only snapshot per five seconds, shared by overlapping polls.
        with lock:
            now = time.time()
            prior = cache.get(window)
            if prior and now - prior['generated_at'] < 5:
                return prior
            value = summary(store, window, now)
            cache[window] = value
            return value
