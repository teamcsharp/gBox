"""Bounded, durable dispatch of favorite-game engineering and inbox acceptance.

The cheap cron pump owns admission; agents own isolated task workspaces. Queue
claims precede cron writes and uncertain writes are reconciled, never replayed.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
import time

from . import hermes_delivery as delivery, hermes_task_mode as mode, hermes_quota

PREFIX = 'gBox queue '
STAGES = ('inventory', 'analysis', 'reader', 'writer', 'runtime')
ACTIVE = ('claimed', 'running')
HASH = re.compile(r'^[0-9a-f]{64}$')
ID = re.compile(r'^[0-9a-f]{16}$')


def _path():
    return delivery.state_dir() / 'work-queue.json'


def _read():
    return json.loads(_path().read_text()) if _path().exists() else {
        'version': 1, 'items': {}, 'last_lane': 'inbox'}


def _save(data):
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    tmp.replace(p)


def _api(path, body=None):
    from .hermes_availability import _api as api
    return api(path, body)


def _executions():
    # A missing/unreadable DB is not evidence of spare capacity.
    p = mode._home() / 'cron/executions.db'
    with sqlite3.connect(f'file:{p.as_posix()}?mode=ro', uri=True, timeout=3) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute('SELECT id,job_id,status,started_at,finished_at FROM executions '
                          'ORDER BY rowid DESC').fetchall()
    latest, active = {}, set()
    for row in rows:
        r = dict(row)
        # A scheduled occurrence with no start still reserves its job.
        if r['status'] in ACTIVE:
            active.add(r['job_id'])
        if r.get('started_at'):
            latest.setdefault(r['job_id'], r)
    return latest, active


def _native_jobs():
    # Read the local control DB: GET /api/tasks can enqueue inventory jobs.
    p = Path(__file__).resolve().parents[1] / 'gbox-data/gbox.sqlite3'
    with sqlite3.connect(f'file:{p.as_posix()}?mode=ro', uri=True, timeout=3) as db:
        return [json.loads(row[0]) for row in db.execute(
            "SELECT body FROM docs WHERE kind='job' AND json_extract(body,'$.state') "
            "IN ('queued','running','cancelling')")]


def _stamp(value):
    from .hermes_tasks import _stamp
    return _stamp(value) or 0


def _on_main():
    p = delivery.state_dir() / 'branches.json'
    if not p.exists():
        return set()
    data = json.loads(p.read_text())
    # Old observations are hints only; agents must confirm deployment and acceptance.
    return {rid for rid, value in data.get('reported', {}).items() if value.startswith('on_main:')}


def sync(data, favorites, requests, *, now):
    """Inventory every durable favorite, including missing catalog entries."""
    if (not isinstance(favorites, dict) or not isinstance(favorites.get('items'), list)
            or favorites.get('count') != len(favorites['items'])):
        raise ValueError('Incomplete favorite snapshot; dispatch deferred')
    if len({g['game_id'] for g in favorites['items']}) != favorites['count']:
        raise ValueError('Duplicate favorite snapshot; dispatch deferred')
    favorite_ids = {g['game_id'] for g in favorites['items']}
    children = {(r.get('context') or {}).get('hermes_favorite_game'): r for r in requests
                if (r.get('context') or {}).get('hermes_favorite_game')}
    for item in data['items'].values():
        if item['lane'] == 'favorite':
            item['favorite'] = item['game_id'] in favorite_ids
    for game in favorites['items']:
        gid = game['game_id']
        if not ID.fullmatch(gid):
            raise ValueError('Invalid favorite game ID')
        item = data['items'].setdefault('favorite:' + gid, {
            'lane': 'favorite', 'game_id': gid, 'stages': {}, 'attempts': 0,
            'last_dispatched': 0, 'created': now})
        item.update(title=game.get('title') or gid, platform=game.get('platform'),
                    favorite=True, in_catalog=game.get('in_catalog') is True)
    # Non-favorite showcase games also own durable child requests. Recover a
    # lost POST response for them before a dispatcher can create a duplicate.
    for item in data['items'].values():
        gid = item.get('game_id')
        if item['lane'] == 'favorite' and gid in children:
            item.update(request_id=children[gid]['id'], number=children[gid]['number'])
            item.pop('request_uncertain', None)
    for request in requests:
        if request['id'] == data.get('parent_request_id'):
            continue  # its child game tasks are the executable units
        if request['id'] in {r['id'] for r in children.values()}:
            continue
        # Automatic recurring review reminders are never engineering work.
        context = request.get('context') or {}
        body = str(request.get('body') or request.get('title') or '').lstrip()
        actionable = request.get('source') in ('gap', 'characters')
        repair = bool(context.get('auto_report') or context.get('native_replacement')
                      or actionable and (context.get('character') or context.get('what')
                                         or body.startswith('Extract ') or 'pick whip' in body.lower()))
        operator_child = (request.get('parent_request_id') and request.get('author') == 'operator'
                          and request.get('source') not in {'characters', 'gap', 'system', 'automation', 'agent', 'review'})
        if ((request.get('automated') and not repair and not operator_child and not actionable)
                or body.startswith(('gBox request review', '<agent-message', '<task-notification'))):
            continue
        if request.get('status') not in ('open', 'in_progress'):
            continue
        item = data['items'].setdefault('inbox:' + request['id'], {
            'lane': 'inbox', 'request_id': request['id'], 'attempts': 0, 'last_dispatched': 0,
            'created': request.get('created', now)})
        item.update(number=request.get('number'), title=request.get('title'), repair=repair,
                    extraction_engineering=context.get('extraction_engineering') is True,
                    session_observer=bool(context.get('session_observer')),
                    launch_failure=bool(context.get('launch_failure')),
                    operator_requested=bool(context.get('replacement_requested')),
                    game_id=context.get('game_id'), target=context.get('target'),
                    character=context.get('character'))
    data.update(favorites_count=len(favorite_ids), synced_at=now)


def next_stage(item):
    return next((stage for stage in STAGES if (item.get('stages', {}).get(stage) or {}).get('status') != 'verified'), None)


def _final_report(run):
    from . import hermes_summaries as summaries, hermes_tasks
    home = mode._home()
    state = hermes_tasks._db(home / 'state.db')
    if not state:
        return ''
    try:
        session = summaries._session_at(state, run['job_id'], _stamp(run['started_at']))
        return summaries._response(home, run['job_id'], _stamp(run.get('finished_at')), state, session['id'])[:12000] if session else ''
    finally:
        state.close()


def _preserve_report(item, run):
    """The durable dispatch claim owns this report even if legacy tool attribution cannot decode it."""
    if (not item.get('local') or not ID.fullmatch(str(item.get('request_id', '')))
            or not re.fullmatch('[0-9a-f]{32}', str(run.get('id', '')))):
        return
    if item.get('report_posted_run') == run['id']:
        return
    try:
        if item.get('report_run') != run['id']:
            report = _final_report(run)
            if not report:
                return
            item.update(report_run=run['id'], final_report=report)
        marker = f"Local queue checkpoint {run['id']}:"
        request = _api('/api/requests/' + item['request_id'])
        if not any(marker in m.get('text', '') for m in request.get('messages', [])):
            _api('/api/requests/' + item['request_id'] + '/messages', {'author': 'agent',
                'text': marker + '\nModel-reported result; acceptance still requires verification.\n\n' + item['final_report']})
        item['report_posted_run'] = run['id']
        item.pop('report_error', None)
    except Exception as exc:  # retain the report locally and retry posting next tick
        item['report_error'] = type(exc).__name__


def reconcile(data, jobs, latest, active, *, now):
    """One completed occurrence advances the queue exactly once, even after a crash."""
    by_name = {j.get('name'): j for j in jobs}
    for item in data['items'].values():
        if item.get('dispatch_state') == 'uncertain':
            job = by_name.get(item.get('job_name'))
            if job:
                item.update(job_id=job['id'], dispatch_state='queued')
            else:
                continue  # An unacknowledged creation stays held for inspection.
        jid = item.get('job_id')
        if not jid:
            continue
        job = next((j for j in jobs if j['id'] == jid), None)
        if jid in active or job and job.get('enabled'):
            continue
        run = latest.get(jid)
        if not run:
            continue
        if _stamp(run['started_at']) < item.get('last_dispatched', 0) - 2:
            continue  # Old history cannot settle a newer queued occurrence.
        _preserve_report(item, run)
        if run['id'] == item.get('last_run_id'):
            continue
        item.update(last_run_id=run['id'], dispatch_state='finished', last_finished=now)
        advanced = item.get('checkpoint_at', 0) >= item.get('last_dispatched', 0)
        failures = 0 if advanced else item.get('no_progress_runs', 0) + 1
        item['no_progress_runs'] = failures
        # Make room for other titles; repeated reading/error runs back off instead of spinning.
        delay = min(6 * 3600, 300 * 2 ** min(failures - 1, 6)) if failures else 60
        item['retry_at'] = max(item.get('retry_at', 0), now + delay)


def candidates(data, requests, native, owned, on_main, *, now):
    by_id = {r['id']: r for r in requests}
    busy_requests = set(owned) | {j.get('parent_request_id') for j in native}
    busy_games = {(j.get('input') or {}).get('game_id') or
                  ((j.get('input') or {}).get('game') or {}).get('game_id') for j in native}
    busy_games.update(i.get('game_id') for i in data['items'].values()
                      if i.get('dispatch_state') in ('queued', 'uncertain') or i.get('request_id') in owned)
    heavy = sum(j.get('tool') in ('analyze_binary', 'ghidra_script', 'characters', 'doa2_assets') for j in native)
    result = []
    for key, item in data['items'].items():
        rid = item.get('request_id')
        if (rid and rid in busy_requests or item.get('retry_at', 0) > now
                or item.get('game_id') and item['game_id'] in busy_games
                or item.get('request_uncertain') or item.get('dispatch_state') in ('queued', 'uncertain')):
            continue
        req = by_id.get(rid, {})
        if item['lane'] == 'favorite':
            # a recently played title the Sonic showcase found without a writer (ensure_item) is worked like a favorite
            if (not (item.get('favorite') or item.get('showcase')) or not item.get('in_catalog')
                    or item['game_id'] in busy_games or not next_stage(item)):
                continue
            if heavy >= 2 and next_stage(item) in ('inventory', 'analysis'):
                continue
            # Explicit operator closure/block is respected; the readiness manifest stays separate.
            if req.get('status') in ('done', 'blocked'):
                continue
        elif req.get('status') not in ('open', 'in_progress'):
            continue
        item['on_main'] = rid in on_main
        result.append((key, item))
    repair_games = {i.get('game_id') for _, i in result if i.get('repair') and i.get('game_id')}
    return [(k, i) for k, i in result if i['lane'] != 'favorite' or i['game_id'] not in repair_games]


def priority_rank(item, data) -> int:
    """Position of this item's game or request in the operator's priority list, then in the Spark helper's triage
    list (launch failures, crashes, regressions), which always ranks after every operator entry; past both when
    not listed."""
    order = [str(x) for x in (data.get('priority') or [])]
    triage = [str(x) for x in (data.get('triage_priority') or []) if str(x) not in order]
    for key in (item.get('game_id'), item.get('request_id'), str(item.get('number') or '')):
        if key and key in order:
            return order.index(key)
    for key in (item.get('request_id'), str(item.get('number') or '')):
        if key and key in triage:
            return len(order) + triage.index(key)
    return len(order) + len(triage)


def add_triage_priority(request_ids, *, limit=200) -> list[str]:
    """The Spark helper's inbox triage: these requests go ahead of unlisted work, behind the operator's list."""
    with delivery.locked('work-queue'):
        data = _read()
        current = [str(x) for x in (data.get('triage_priority') or [])]
        for rid in request_ids:
            if str(rid) not in current:
                current.append(str(rid))
        data['triage_priority'] = current[-limit:]
        _save(data)
        return data['triage_priority']


def set_priority(ids) -> list[str]:
    """Operator priority: game ids and/or request ids (or numbers) worked first in their lane; saved in the queue data."""
    data = _read()
    data['priority'] = [str(x).strip() for x in ids if str(x).strip()]
    _save(data)
    return data['priority']


def get_priority() -> list[str]:
    return list(_read().get('priority') or [])


def choose(options, data):
    """Alternate lanes and first attempts/follow-ups so acceptance is not postponed indefinitely; inside a lane the
    operator's priority list (games or requests) comes first."""
    preferred = 'favorite' if data.get('last_lane') == 'inbox' else 'inbox'
    lane = [v for v in options if v[1]['lane'] == preferred] or options
    if lane and len({v[1]['lane'] for v in lane}) == 1:
        followup = data.get('last_' + lane[0][1]['lane'] + '_kind') == 'new'
        lane = [v for v in lane if bool(v[1].get('last_dispatched')) == followup] or lane
    return min(lane, key=lambda v: (
        priority_rank(v[1], data),
        # starred favorites first; a showcase-only title (recently played, no writer yet) after them
        0 if (v[1]['lane'] == 'favorite' and (v[1].get('favorite') or not v[1].get('showcase')))
        or v[1].get('operator_requested') or v[1].get('session_observer')
        else 1 if v[1].get('repair') or v[1]['lane'] == 'favorite' else 2 if v[1].get('on_main') else 3,
        v[1].get('last_dispatched', 0),
        v[1].get('created', 0), v[0])) if lane else None


EMULATOR_STAGES = ('runtime',)   # favorite stages whose agents start emulators (replacement testing in a game)


def _operator_playing():
    """Operator games running on the Spark (Hermes' own machine): the gBox API rows marked not agent-owned on a
    Linux worker. Unknown (API down) counts as none: the rest of tick() fails loudly on its own API calls."""
    from . import operator_guard
    try:
        sessions = _api('/api/sessions?include_ended=false')
        workers = _api('/api/workers')
        return operator_guard.spark_operator_sessions(sessions, workers)
    except Exception:  # noqa: BLE001
        return []


def launches_emulator(item) -> bool:
    """Queue items whose agents start an emulator on this machine: the favorite runtime stage (replacement tested
    in a running game) and inbox repairs that need gameplay acceptance."""
    if item.get('lane') == 'favorite':
        return next_stage(item) in EMULATOR_STAGES
    return bool(item.get('repair')) and not item.get('extraction_engineering')


def throttle_sandboxes(playing, throttle=None):
    """While the operator plays here: running agent sandboxes drop to nice 19 and the idle I/O class."""
    if not playing:
        return None
    from . import operator_guard
    try:
        return (throttle or operator_guard.throttle_agent_sandboxes)()
    except Exception as e:  # noqa: BLE001
        return {'error': f'{type(e).__name__}: {e}'[:200]}


def operator_gate(options, playing, throttled=None):
    """While the operator plays on the Spark (docs/stream-stability.md): defer emulator-launching items and allow
    one dispatch per tick. Returns (options, capacity cap or None, report)."""
    if not playing:
        return options, None, None
    kept = [v for v in options if not launches_emulator(v[1])]
    report = {'games': sorted({s.get('title') or s.get('game_id') or s.get('session_id') for s in playing}),
              'deferred': [v[0] for v in options if v not in kept], 'sandboxes': throttled}
    return kept, 1, report


def _prompt(item, playing=None):
    rid = item['request_id']
    header = (f"Assigned queue task: request #{item['number']} ({rid}). Work ONLY this request; "
              "the dispatcher has reserved it. Read get_request and get_dispatch_feedback first. "
              "Do not select a different ticket from list_requests. ")
    header += ('For game-build changes, keep supplying reviewed native inspection plans through the '
               'inspection_builds tool: op=plan for request revisions and reports, then implement the change and '
               'op=publish a launch:false cast_swap recipe with change_id, relevant writer dependencies, '
               'requests_ack and feedback_ack. Never acknowledge unread feedback or produce unchanged failures. '
               'The local build queue handles debounce, memory/disk headroom and safe worker admission; '
               'compile success is not gameplay verification. ')
    header += ('Use ollama_assist op=status to find opted-in idle helpers; delegate small decompilation evidence '
               'reviews with op=analyze, require_worker and agent_use=true only when ready. Never opt a PC in '
               'or download a model yourself. Treat helper artifacts as hypotheses and verify them. ')
    if playing:
        header += ('The operator is playing ' + ', '.join(playing) + ' on this machine right now. Do not start an '
                   'emulator here (no local Dolphin, RetroArch, PCSX2 or other game runs, no large parallel builds); '
                   'do source, reader and static-analysis work. Runtime tests go through gBox launch_game node=idle '
                   'on another PC, never on this one. ')
    if item['lane'] == 'inbox':
        if item.get('launch_failure'):
            # gbox/launch_failures.py: a game failed to load; the control plane verifies and closes it after the merge
            header += ('This is a launch failure report: a game failed to load. The request holds the error, logs, '
                       'timings, staging and the automatic remedy results. Find the root cause, fix it in gBox code '
                       'with a focused test and publish it (draft PR) with screenshots of the game loading after the '
                       'fix (evidence_capture on an idle node). Never stop, pause or replace a game the operator is '
                       'playing. Leave the request in_progress: the control plane verifies the fix with a launch of '
                       'the same game and mod after the PR merges and deploys, then closes or reopens it. ')
        elif item.get('session_observer'):
            header += ('This task supports passive observation of an operator gameplay session. '
                       'Read its observations, capture evidence and exact game build. Repair the native '
                       'model reader or read-only observation capability. Never send input, pause, stop, '
                       'reset, move, relaunch, or capture GPU draws on the operator session. Work from '
                       'owned files with REA/Ghidra and publish tested readers and reusable assets. '
                       'Keep replacement testing on a separate agent-owned session. ')
        elif item.get('extraction_engineering'):
            header += ('This is offline native extraction engineering. Read the exact failed job, accepted '
                       'receipt, source selection and every failed entry on the request. Diagnose source access '
                       'first, then use REA/Ghidra to repair or develop the bounded native model reader. Preserve '
                       'source hashes, publish focused tests and independently validate the requested extracted '
                       'assets. Do not launch, capture, pause or stop games or change saves/memory. Do not '
                       'substitute a replacement/gameplay task, and do not close after a plan or PR alone. ')
            if ID.fullmatch(str(item.get('game_id') or '')):
                from .native_engineering import prompt
                header += '\n' + prompt(item['game_id'], stage='reader') + '\n'
        elif item.get('repair'):
            header += ('This is unfinished native character work. Follow the request scope: extraction needs an '
                       'identified reusable native asset with validation; replacement additionally needs gameplay '
                       'acceptance. Read the preserved donor, target, '
                       'normalized pick point, exact game build, screenshot and checkpoint from the request. '
                       'Identify the selected actor and its native model/skeleton/animation slot using REA and '
                       'Ghidra evidence; do not silently replace the player when a different actor was selected. '
                       'Implement the missing reader/writer or rebuild marked assets, preserve source hashes, '
                       'test the round trip and replay this donor/target in the game. A preview, overlay, build '
                       'or successful tool exit is not completion. Require gameplay evidence of the actual '
                       'replacement, animations and controls. Record exact pending job IDs and the next step; '
                       'keep the request open until verified, or name a concrete external blocker. ')
            if ID.fullmatch(str(item.get('game_id') or '')):
                from .native_engineering import prompt
                header += '\n' + prompt(item['game_id'], stage=None) + '\n'
        header += ('Its published branch is recorded on main. Confirm the exact deployed files and perform '
                   'the outstanding acceptance check before writing more source. ' if item.get('on_main') else '')
        return header + mode._handoff()
    stage = next_stage(item)
    from .native_engineering import prompt
    engineering = prompt(item['game_id'], stage=stage, fingerprint=item.get('fingerprint'))
    template = Path(__file__).resolve().parents[1] / 'hermes/gbox/FAVORITE_WORK.md'
    fp = item.get('fingerprint') or {}
    hint = ''
    if stage in ('inventory', 'analysis'):
        hint = ('\nAssimilation fingerprint attached to this ticket: ' + fp['summary']
                + (f" Start from {fp.get('start_from') or fp.get('engine_reader')}."
                   if fp.get('start_from') or fp.get('engine_reader') else '')
                if fp.get('summary') and fp.get('source') != 'error' else
                '\nNo fingerprint yet: run assimilate op=fingerprint for this game_id first (start_job).')
    return header + f"\nGame: {item['title']} ({item['platform']}), game_id={item['game_id']}. " + (
        f"Next unfinished stage: {stage}. Preserved checkpoint: " + json.dumps(item.get('stages', {}))
        + hint + '\n' + engineering + '\n' + template.read_text(encoding='utf-8') + mode._handoff())


FINGERPRINT = None  # (game_id, title, platform, api=) -> compact dict; None = gbox.assimilate.ticket_fingerprint


def _fingerprint(item):
    """Step one of readiness: the assimilate fingerprint (engine, containers, codecs, nearest assimilated titles,
    reader to start from). Best effort: a ticket is never blocked on it."""
    try:
        from .assimilate import ticket_fingerprint
        fn = FINGERPRINT or ticket_fingerprint
        return fn(item['game_id'], item.get('title') or '', item.get('platform') or '', api=lambda p: _api(p),
                  max_files=1500)
    except Exception as e:  # noqa: BLE001
        return {'source': 'error', 'error': f'{type(e).__name__}: {e}'[:200], 'summary': 'fingerprint unavailable'}


def _ensure_request(data, item, requests):
    if item.get('request_id'):
        return
    parent = data.get('parent_request_id')
    if not parent or not any(r['id'] == parent for r in requests):
        raise ValueError('Favorites queue requires its existing operator parent request')
    if not item.get('fingerprint'):
        item['fingerprint'] = _fingerprint(item)
    fp = item['fingerprint']
    # Persist before POST. Lost responses are recovered by the context marker on the next scan.
    item['request_uncertain'] = True
    _save(data)
    r = _api('/api/requests', {
        'title': f"Character replacement readiness: {item['title']}", 'source': 'automation',
        'author': 'agent', 'automated': True, 'parent_request_id': parent,
        'context': {'hermes_favorite_game': item['game_id'], 'game_id': item['game_id'],
                    'assimilation_fingerprint': fp},
        'body': (f"Persistent work for favorite game {item['game_id']} ({item['platform']}). "
                 "Inventory the owned build, analyze executable/asset loaders, implement and test native "
                 "character extraction and replacement, then verify the rebuilt game. Preserve hash-identified "
                 "artifacts, reusable Ghidra projects and exact pending job IDs. Each run advances one bounded "
                 "stage; a report, extracted binary or preview alone is not a working character replacement."
                 f"\n\nFingerprint (gbox.assimilate, step one of inventory): {fp.get('summary', '')}")})
    if not ID.fullmatch(str(r.get('id', ''))):
        raise ValueError('Request creation was not acknowledged')
    item.update(request_id=r['id'], number=r['number'])
    item.pop('request_uncertain', None)
    _save(data)


def tick(*, now=None):
    now = time.time() if now is None else now
    with delivery.locked('work-queue'):
        # First, whatever the dispatcher decides below: agent sandboxes already running must not starve the
        # operator's game on this machine (docs/stream-stability.md).
        playing = _operator_playing()
        throttled = throttle_sandboxes(playing)
        controller = mode._job() or {}
        if not controller.get('enabled') or not controller.get('no_agent'):
            return {'status': 'disabled_or_legacy_controller'}
        data = _read()
        jobs = mode._jobs()
        latest, active = _executions()
        requests = _api('/api/requests')
        sync(data, _api('/api/favorites'), requests, now=now)
        reconcile(data, jobs, latest, active, now=now)
        _save(data)
        config = mode._config()
        path = delivery.state_dir() / 'feedback.json'
        feedback = json.loads(path.read_text()) if path.exists() else {}
        routes = hermes_quota.routes(config, feedback.get('routes') or [])
        eligible = [r for r in routes if feedback.get('cooldowns', {}).get(r['provider']+'/'+r['model'], 0) <= now]
        primary = {'provider': (config.get('cron') or {}).get('model_provider'),
                   'model': (config.get('cron') or {}).get('model')}
        if primary not in eligible:
            return {'status': 'waiting_for_route_supervisor', 'favorites': data['favorites_count']}
        from . import hermes_local
        local = hermes_local.is_local(primary)
        from . import hermes_pool
        pooled = local and hermes_pool.configured()
        pool_state = _api('/api/hermes/local/nodes') if pooled else None
        if local and not pooled:
            # The Spark's GPU model: one run at a time, never while the operator plays a game on the Spark.
            gate = local_gate()
            if gate:
                return {'status': 'waiting_for_operator', 'reason': gate, 'favorites': data['favorites_count']}
        local_settings = hermes_local.settings()
        limit = local_settings.max_parallel_jobs if local else min(4, max(1, int((config.get('cron') or {}).get('max_parallel_jobs') or 1)))
        if pooled:
            limit = pool_state['capacity']
        script_ids = {j['id'] for j in jobs if j.get('no_agent')}
        reserved = active - script_ids
        reserved.update(j['id'] for j in jobs if not j.get('no_agent') and j.get('enabled')
                        and (j.get('schedule') or {}).get('kind') == 'once')
        from .hermes_recovery import _active_requests
        owned = _active_requests()
        # A legacy/local resolution still owns its request until its chat finishes.
        chat_ids = {(r.get('context') or {}).get('resolution_chat_id'): r['id'] for r in requests
                    if (r.get('context') or {}).get('resolution_chat_id')}
        if chat_ids:
            owned.update(chat_ids[c['id']] for c in _api('/api/chat')
                         if c.get('busy') and c.get('id') in chat_ids)
        native = _native_jobs()
        options = candidates(data, requests, native, owned, _on_main(), now=now)
        # Both gates apply and the stricter wins: the operator's game on the Spark defers emulator-launching items
        # and caps dispatch at 1 (docs/stream-stability.md); the local route allows only small tasks, one at a time
        # (and returned above while the operator plays, through the proxy's gate).
        options, cap, gate = operator_gate(options, playing, throttled)
        if cap is not None:
            limit = min(limit, cap)
        titles = (gate or {}).get('games') or []
        deferred = 0
        if local and not pooled and not local_settings.allow_large_tasks:
            # Small, well-scoped tasks only; big multi-file work stays queued for a paid route.
            by_id = {r['id']: r for r in requests}
            small = [v for v in options if hermes_local.dispatch_size(v[1], by_id.get(v[1].get('request_id')))['size'] == 'small']
            deferred = len(options) - len(small)
            options = small
        dispatched = []
        slots = hermes_pool.assignments(pool_state['nodes'], data['items'], reserved)[0] if pooled else [None] * max(0, limit - len(reserved))
        slots = slots[:max(0, limit - len(reserved))]
        by_id = {r['id']: r for r in requests}
        for node in slots:
            # Give both backlogs capacity; spare slots go to whichever has work.
            counts = {lane: sum(j.get('name', '').startswith(PREFIX + lane + ' ') and
                               j['id'] in reserved for j in jobs) +
                      sum(d['lane'] == lane for d in dispatched) for lane in ('inbox', 'favorite')}
            least = min((counts[v[1]['lane']] for v in options), default=0)
            choices = [v for v in options if counts[v[1]['lane']] == least]
            if node and node.get('primary'):
                narrow = [v for v in options if hermes_local.dispatch_size(v[1], by_id.get(v[1].get('request_id')))['size'] == 'small']
                choices = narrow or (choices if node.get('allow_large_tasks') else [])
            chosen = choose(choices, data)
            if not chosen:
                continue
            key, item = chosen
            options.remove(chosen)
            if item.get('game_id'):
                options = [v for v in options if v[1].get('game_id') != item['game_id']]
            _ensure_request(data, item, requests)
            name = PREFIX + ('favorite ' + item['game_id'] if item['lane'] == 'favorite' else 'inbox ' + item['request_id'])
            prompt = _prompt(item, titles)
            if item.get('final_report'):
                prompt += '\nPrevious local run reported (verify claims before use):\n' + item['final_report'][-8000:]
            if (by_id.get(item.get('request_id'), {}).get('context') or {}).get('read_only'):
                prompt += ('\nREAD-ONLY REQUEST: do not edit source, saves or memory, install dependencies, '
                           'or prepare implementation changes. Inventory existing evidence, post unknowns '
                           'and missing evidence on the request, then finish this bounded inventory.')
            run_settings = hermes_pool.node_settings()[node['name']] if node else local_settings
            run_route = hermes_local.route(run_settings) if node else dict(primary)
            pin = ['--model', run_settings.model, '--provider', run_settings.provider] if node else []
            if local:
                prompt = hermes_local.local_prompt(prompt, run_settings)
                if node:
                    prompt += (' The prime Spark retains the request, workspace and artifacts. Read the latest '
                               'request checkpoints before work, including work from the other inference host. '
                               'Keep exact job IDs and evidence on the request so another local run can resume safely.')
            existing = [j for j in jobs if j.get('name') == name]
            if len(existing) > 1:
                raise RuntimeError('Ambiguous queue job identity')
            # Recheck the operator switch immediately before admission.
            if not (mode._job() or {}).get('enabled'):
                break
            attempt_kind = 'followup' if item.get('last_dispatched') else 'new'
            item.update(job_name=name, dispatch_state='uncertain', last_dispatched=now,
                        attempts=item.get('attempts', 0) + 1, local=local, route=run_route,
                        inference_node=node['name'] if node else None)
            _save(data)
            if existing:
                job = existing[0]
                mode._run('edit', job['id'], '--prompt', prompt, '--no-continuity',
                          '--reasoning-effort', run_settings.reasoning_effort if local else 'high',
                          *(pin or ['--unpin']))
                mode._run('resume', job['id'], '--run-now')
            else:
                mode._run('create', mode._once(), prompt, '--name', name, '--repeat', '1',
                          '--reasoning-effort', run_settings.reasoning_effort if local else 'high', *pin,
                          '--workdir', str(mode._PROMPT.parents[2]),
                          '--deliver', 'local', '--failure-deliver', 'local')
                found = [j for j in mode._jobs() if j.get('name') == name]
                if len(found) != 1:
                    raise RuntimeError('Queue launch acknowledgment missing')
                job = found[0]
            item.update(job_id=job['id'], dispatch_state='queued')
            data['last_lane'] = item['lane']
            data['last_' + item['lane'] + '_kind'] = attempt_kind
            _save(data)
            dispatched.append({'job_id': job['id'], 'request_id': item['request_id'],
                               'game_id': item.get('game_id'), 'lane': item['lane'], 'local': local,
                               **({'inference_node': node['name']} if node else {})})
        return {'status': 'dispatched' if dispatched else 'waiting', 'dispatched': dispatched,
                'active_or_queued': len(reserved) + len(dispatched), 'capacity': limit,
                'favorites': data['favorites_count'], 'eligible_tasks': len(options),
                'local_route': local, 'deferred_for_paid_route': deferred,
                **({'operator_playing': gate} if gate else {})}


def local_gate():
    """Why local-model work must wait now (the operator plays on the Spark, or the gBox proxy is down), else None."""
    try:
        state = _api('/api/llm/local/status')
    except Exception as exc:  # noqa: BLE001 - the proxy lives in the gBox service; no service, no local route
        return f'gBox local model proxy unreachable ({type(exc).__name__})'
    if not state.get('enabled', True):
        return 'the local route is switched off ([hermes.local] enabled = false)'
    return state.get('gated')


def _readiness_row(item):
    fp = item.get('fingerprint') or {}
    return {'game_id': item['game_id'], 'title': item.get('title'), 'favorite': bool(item.get('favorite')),
            'showcase': bool(item.get('showcase')), 'next_stage': next_stage(item),
            'stages': {k: (v or {}).get('status') for k, v in (item.get('stages') or {}).items()},
            'request_id': item.get('request_id'), 'number': item.get('number'),
            'dispatch_state': item.get('dispatch_state'), 'attempts': item.get('attempts', 0),
            'fingerprint': fp.get('summary') or '', 'start_from': fp.get('start_from') or fp.get('engine_reader') or ''}


def item_state(game_id):
    """One title's readiness row (stages, next stage, ticket, fingerprint summary), or None when it is not queued."""
    item = _read()['items'].get('favorite:' + str(game_id))
    return _readiness_row(item) if item else None


def ensure_item(game, *, fingerprint=None, source='showcase', now=None):
    """Put a catalog title in the readiness queue (the favorite lane: inventory -> analysis -> reader -> writer ->
    runtime, worked by Hermes with Ghidra / REA) with the assimilate fingerprint attached. Used by the Sonic showcase
    for a title without a writer: a favorite is already there (sync); a recently played one is added with
    `showcase: true`, which candidates() admits after the starred favorites. Never resets stages or a ticket.
    Raises BlockingIOError while the queue's tick holds the lock (the caller retries on its next pass)."""
    now = time.time() if now is None else now
    gid = str(game.get('game_id') or '')
    if not ID.fullmatch(gid):
        raise ValueError('Invalid game ID')
    with delivery.locked('work-queue'):
        data = _read()
        key = 'favorite:' + gid
        new = key not in data['items']
        item = data['items'].setdefault(key, {'lane': 'favorite', 'game_id': gid, 'stages': {}, 'attempts': 0,
                                              'last_dispatched': 0, 'created': now, 'favorite': False})
        item.update(title=item.get('title') or game.get('title') or gid,
                    platform=item.get('platform') or game.get('platform'),
                    in_catalog=item.get('in_catalog') or game.get('in_catalog', True) is True)
        item[source] = True
        item.setdefault('requested_by', [])
        if source not in item['requested_by']:
            item['requested_by'].append(source)
        fp = item.get('fingerprint') or {}
        if fingerprint and (not fp or fp.get('source') == 'error'):
            item['fingerprint'] = fingerprint
        _save(data)
        return _readiness_row(item) | {'new': new}


def snapshot(game_id=''):
    from .native_engineering import plan
    if game_id and not ID.fullmatch(str(game_id)):
        raise ValueError('Invalid game ID')
    data = _read()
    games = [{k: item.get(k) for k in ('game_id', 'title', 'platform', 'in_catalog', 'request_id',
             'number', 'dispatch_state', 'job_id', 'attempts', 'retry_at', 'stages', 'favorite', 'showcase')}
             | {'next_stage': next_stage(item)} for item in data['items'].values()
             if item['lane'] == 'favorite' and (item.get('favorite') or item.get('showcase')
                                               or game_id and item['game_id'] == game_id)]
    count = sum(bool(g.get('favorite')) for g in games)
    ready = sum(bool(g.get('favorite')) and g['next_stage'] is None for g in games)
    queued_count = len(games)
    if game_id:
        games = [g for g in games if g['game_id'] == game_id]
    else:
        games = [{k: v for k, v in g.items() if k != 'stages'} |
                 {'stages': {k: v.get('status') for k, v in (g.get('stages') or {}).items()}} for g in games]
    result = {'synced_at': data.get('synced_at'), 'favorites': count, 'tracked_games': queued_count,
              'verified_native_replacement': ready, 'games': games}
    if game_id:
        item = data['items'].get('favorite:' + game_id)
        result['engineering'] = plan(game_id, stage=next_stage(item) if item else 'inventory',
                                     fingerprint=(item or {}).get('fingerprint'))
        result['queued'] = item is not None
    return result


def checkpoint(game_id, request_id, stage, status, note, *, source_sha256='', artifacts=(), next_step='', now=None):
    """Retain exact-build milestones with stored evidence, never infer success from a run exit."""
    now = time.time() if now is None else now
    if stage not in STAGES or status not in ('partial', 'verified', 'blocked') or not note.strip():
        raise ValueError('A valid stage, status and concrete result note are required')
    if status == 'verified':
        if not HASH.fullmatch(source_sha256) or not artifacts:
            raise ValueError('Verified stages require the owned source hash and stored evidence artifacts')
        request = _api(f'/api/requests/{request_id}')
        attached = {a.get('sha256') for m in request.get('messages', []) for a in m.get('attachments', [])}
        attached.add(request.get('image'))
        for digest in artifacts:
            if not HASH.fullmatch(digest):
                raise ValueError('Invalid evidence hash')
            if digest not in attached:
                raise ValueError('Evidence must be attached to this game request')
            _api(f'/api/artifacts/{digest}/meta')  # missing artifacts refuse completion
        if stage == 'runtime':
            # A text report alone cannot claim native character replacement in gameplay.
            if not any(str(_api(f'/api/artifacts/{d}/meta').get('media_type', '')).startswith('image/') for d in artifacts):
                raise ValueError('Runtime verification requires a stored real gameplay screenshot')
    with delivery.locked('work-queue'):
        data = _read()
        item = data['items']['favorite:' + game_id]
        if item.get('request_id') != request_id:
            raise ValueError('Checkpoint request does not own this game queue item')
        previous_source = item.get('source_sha256')
        if source_sha256 and previous_source and source_sha256 != previous_source:
            raise ValueError('Source build changed; preserve and review its earlier evidence before resetting stages')
        if status == 'verified' and any((item['stages'].get(s) or {}).get('status') != 'verified'
                                        for s in STAGES[:STAGES.index(stage)]):
            raise ValueError('Verify the preceding exact-build stages first')
        record = {'status': status, 'note': note, 'next_step': next_step,
                  'source_sha256': source_sha256, 'artifacts': list(artifacts)}
        previous = item['stages'].get(stage) or {}
        changed = {k: v for k, v in previous.items() if k != 'at'} != record
        item['stages'][stage] = record | {'at': now if changed else previous.get('at', now)}
        if source_sha256:
            item['source_sha256'] = source_sha256
        if changed:
            item['checkpoint_at'] = now
        if status == 'blocked':
            item['retry_at'] = now + 6 * 3600
        _save(data)
        return {'game_id': game_id, 'request_id': request_id, 'stage': stage, 'status': status,
                'next_stage': next_stage(item), 'ready': next_stage(item) is None}


def install_script():
    root = Path(__file__).resolve().parents[1]
    path = mode._home() / 'scripts/gbox-work-queue.py'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('import sys,json\nsys.path.insert(0,' + repr(str(root)) + ')\n'
                    'from gbox.hermes_work_queue import tick\nprint(json.dumps(tick()))\n', encoding='utf-8')
    return path.name  # Hermes resolves scripts relative to ~/.hermes/scripts.


def pause_pending():
    with delivery.locked('work-queue'):
        data = _read()
        for job in mode._jobs():
            if job.get('name', '').startswith(PREFIX) and job.get('enabled'):
                mode._run('pause', job['id'])
                if not mode._active(job['id']):
                    for item in data['items'].values():
                        if item.get('job_id') == job['id']:
                            item['dispatch_state'] = 'paused'
        _save(data)


def claims():
    """Expose durable assignments before the agent's first mutation receipt."""
    return {item['job_id']: item['request_id'] for item in _read()['items'].values()
            if item.get('job_id') and item.get('request_id') and item.get('dispatch_state') == 'queued'}
