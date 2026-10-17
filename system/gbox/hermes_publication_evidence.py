"""Bounded producer-side evidence for legacy publication and reviewed merges.

Device-work reads saved facts only. Reconciliation performs these optional
historical joins; missing, ambiguous or truncated evidence stays unknown.
"""
from __future__ import annotations

import json
import re
import sqlite3
import subprocess

from . import hermes_delivery as D, hermes_tasks as T

SHA = re.compile(r'[0-9a-f]{40}\Z')
BACKFILL_LIMIT = 20
SESSION_LIMIT = 100
MESSAGE_LIMIT = 250
MAX_BYTES = 4 * 1024 * 1024


def key(record):
    return f'{record["pr_number"]}:{record["commit"]}'


def publication_messages(messages, only_ids):
    """Only publication calls and their own responses participate in pairing.

    Duplicate unrelated tool responses in an overlapping worker session cannot
    make the publisher ambiguous; duplicate publication identities still do.
    """
    selected, ids = [], set()
    action = lambda name: (name or '').removeprefix('mcp__gbox__')
    for message in messages:
        raw = message.get('tool_calls')
        if message.get('role') != 'assistant' or not raw or 'publish_task_changes' not in str(raw):
            continue
        calls = json.loads(raw) if isinstance(raw, str) else raw
        kept = []
        for call in calls:
            if call.get('id') not in only_ids:
                continue
            fn = call.get('function') or {}
            if action(fn.get('name')) == 'publish_task_changes':
                kept.append(call)
            elif fn.get('name') == 'tool_call':
                args = fn.get('arguments') or {}
                args = json.loads(args) if isinstance(args, str) else args
                members = [m for m in args.get('calls', []) if action(m.get('name')) == 'publish_task_changes']
                if members:
                    kept.append(call | {'function': fn | {'arguments': json.dumps(args | {'calls': members})}})
        if kept:
            ids.update(c['id'] for c in kept)
            selected.append(message | {'tool_calls': json.dumps(kept)})
    return selected + [m for m in messages if m.get('role') == 'tool' and m.get('tool_call_id') in ids
                       and action(m.get('tool_name')) == 'publish_task_changes']


def publisher(record, sessions, nodes, *, db=None):
    """Match one successful publish response and preceding served-model calls.

    Never use session billing configuration as evidence of the served provider.
    Query only sessions overlapping publication and a bounded message window.
    """
    from . import hermes_accounting as A, hermes_device_work as W
    owned = db is None
    db = T._db(T._home() / 'state.db') if owned else db
    if db is None:
        return None
    snapshot = False
    try:
        db.execute('SAVEPOINT publication_evidence')
        snapshot = True
        stamp = record['published_at']
        candidates = db.execute('SELECT id,source,started_at,ended_at FROM sessions '
            'WHERE started_at<=? AND (ended_at IS NULL OR ended_at>=?) '
            'ORDER BY started_at DESC LIMIT ?', (stamp, stamp, SESSION_LIMIT + 1)).fetchall()
        if len(candidates) > SESSION_LIMIT:
            return None
        matches, size = [], 0
        for raw in candidates:
            session = dict(raw)
            # Check byte lengths before materializing transcript fields. The
            # bounded row count alone does not bound a giant tool response.
            lengths = db.execute('SELECT length(CAST(COALESCE(content,\'\') AS BLOB)), '
                'length(CAST(COALESCE(tool_calls,\'\') AS BLOB)) FROM messages '
                'WHERE session_id=? AND timestamp>=? AND timestamp<=? ORDER BY id LIMIT ?',
                (session['id'], stamp - 600, stamp + 15, MESSAGE_LIMIT + 1)).fetchall()
            size += sum(row[0] + row[1] for row in lengths)
            if len(lengths) > MESSAGE_LIMIT or size > MAX_BYTES:
                return None
            messages = [dict(row) for row in db.execute(
                'SELECT role,content,tool_name,tool_call_id,tool_calls,timestamp FROM messages '
                'WHERE session_id=? AND timestamp>=? AND timestamp<=? ORDER BY id LIMIT ?',
                (session['id'], stamp - 600, stamp + 15, MESSAGE_LIMIT + 1))]
            if len(messages) > MESSAGE_LIMIT:
                return None
            # A live session can grow between the two reads. Apply the same
            # byte budget again and fail closed if the snapshot changed.
            actual = sum(len(str(m.get('content') or '').encode()) + len(str(m.get('tool_calls') or '').encode()) for m in messages)
            if actual != sum(row[0] + row[1] for row in lengths):
                return None
            try:
                identities = set()
                for message in messages:
                    if (message['role'] != 'tool' or
                            (message.get('tool_name') or '').removeprefix('mcp__gbox__') != 'publish_task_changes'):
                        continue
                    result = A._result(message.get('content'), action='publish_task_changes')
                    if isinstance(result, dict) and all(result.get(k) == record.get(k) for k in
                            ('request_id', 'commit', 'pr_number', 'url', 'published_at')):
                        identities.add(message.get('tool_call_id'))
                if not identities:
                    continue
                calls = A._calls(publication_messages(messages, identities))
            except (A.Deferred, ValueError, TypeError, AttributeError):
                # A malformed candidate cannot establish a unique source.
                return None
            for call in calls:
                result = call.get('result')
                if (call['name'].removeprefix('mcp__gbox__') != 'publish_task_changes'
                        or not call['has_response'] or call['rejected'] or call['wrapped_ambiguous']
                        or not isinstance(result, dict) or not isinstance(call['args'], dict)
                        or call['args'].get('request_id') != record['request_id']
                        or any(result.get(k) != record.get(k) for k in
                               ('request_id', 'commit', 'pr_number', 'url', 'published_at'))):
                    continue
                replies = [m for m in messages if m['role'] == 'tool'
                           and m.get('tool_call_id') == call['call_id']
                           and (m.get('tool_name') or '').removeprefix('mcp__gbox__') == 'publish_task_changes']
                if len(replies) != 1 or not isinstance(replies[0].get('timestamp'), (int, float)):
                    continue
                at = replies[0]['timestamp']
                if not stamp <= at <= stamp + 15:
                    continue
                served = [c for c in sessions.get(session['id'], {}).get('calls', [])
                          if c.get('state') == 'ok' and isinstance(c.get('completed_at'), (int, float))
                          and session['started_at'] <= c['completed_at'] <= at]
                routes = W.observed_routes({'calls': served}, nodes)
                matches.append({'source': 'successful_publish_response_and_model_calls',
                    'request_id': record['request_id'], 'commit': record['commit'],
                    'pr_number': record['pr_number'], 'url': record['url'], 'published_at': stamp,
                    'session_id': session['id'], 'session_source': session['source'],
                    'call_id': call['call_id'], 'response_at': at, 'routes': routes,
                    'boundary': 'Recorded model assistance in the publishing session; not sole authorship, review or task completion.'})
        return matches[0] if len(matches) == 1 else None
    except (OSError, ValueError, TypeError, sqlite3.Error):
        return None
    finally:
        if snapshot:
            db.execute('RELEASE publication_evidence')
        if owned:
            db.close()


def compare(base, head):
    """GitHub commit graph for two exact object IDs in the configured repository."""
    if not all(SHA.fullmatch(str(x)) for x in (base, head)):
        raise ValueError('Exact commit identities required')
    result = subprocess.run(['gh', 'api', f'repos/{D.REPOSITORY}/compare/{base}...{head}?per_page=1',
        '--jq', '{status,html_url,base_commit:{sha:.base_commit.sha},merge_base_commit:{sha:.merge_base_commit.sha}}'],
        cwd=D.repository(), capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=45)
    if result.returncode:
        raise RuntimeError('GitHub ancestry lookup failed')
    return json.loads(result.stdout)


def ancestry(record, pull, *, compare_fn=compare, now):
    """A changed PR head contains the publication only with exact graph proof."""
    original, head = record.get('commit'), pull.get('headRefOid')
    merge = (pull.get('mergeCommit') or {}).get('oid')
    if (pull.get('state') != 'MERGED' or pull.get('baseRefName') != 'main'
            or pull.get('number') != record.get('pr_number') or pull.get('url') != record.get('url')
            or record.get('url') != f'https://github.com/{D.REPOSITORY}/pull/{record.get("pr_number")}'
            or not all(SHA.fullmatch(str(x)) for x in (original, head, merge)) or original == head):
        return None
    graph = compare_fn(original, head)
    expected_url = f'https://github.com/{D.REPOSITORY}/compare/{original}...{head}'
    verified = (graph.get('status') == 'ahead' and graph.get('html_url') == expected_url
                and (graph.get('base_commit') or {}).get('sha') == original
                and (graph.get('merge_base_commit') or {}).get('sha') == original)
    return {'source': 'github_commit_comparison', 'repository': D.REPOSITORY,
        'pr_number': record['pr_number'], 'published_commit': original, 'merged_head': head,
        'merge_commit': merge, 'base': 'main', 'verified': verified, 'observed_at': now,
        'comparison': graph,
        'boundary': 'Published commit is an ancestor of the reviewed PR head; later corrections, review and merge are separate contributions.'}


def valid_ancestry(record, pull, evidence):
    """Consumer rechecks all identities; an old observation cannot migrate heads."""
    if not isinstance(evidence, dict) or evidence.get('verified') is not True:
        return False
    try:
        expected = ancestry(record, pull, compare_fn=lambda *a: evidence.get('comparison') or {},
                            now=evidence.get('observed_at'))
    except (TypeError, ValueError):
        return False
    return bool(expected and expected['verified'] and all(evidence.get(k) == expected[k] for k in
        ('source', 'repository', 'pr_number', 'published_commit', 'merged_head', 'merge_commit', 'base')))


def backfill(saved, records, *, now, source_fn=None, compare_fn=compare):
    """At most twenty source joins and twenty graph lookups per reconciliation."""
    from . import hermes_device_work as W
    sources, graphs = saved.setdefault('publication_sources', {}), saved.setdefault('ancestry', {})
    ordered = sorted(records, key=lambda row: row['published_at'], reverse=True)
    source_count = graph_count = 0
    sessions = nodes = None
    errors = []
    for record in ordered:
        identity = key(record)
        if identity not in sources and source_count < BACKFILL_LIMIT:
            source_count += 1
            if source_fn is None:
                if sessions is None:
                    sessions, nodes = W._scan(now), W._nodes()
                source = publisher(record, sessions, nodes)
            else:
                source = source_fn(record)
            sources[identity] = {'checked_at': now, 'evidence': source}
        pull = (saved.get('observations') or {}).get(str(record['pr_number'])) or {}
        if record['commit'] == pull.get('headRefOid') or pull.get('state') != 'MERGED':
            continue
        existing = graphs.get(identity)
        if valid_ancestry(record, pull, existing) or graph_count >= BACKFILL_LIMIT:
            continue
        # Negative graph results are immutable for these exact object IDs too.
        if existing and existing.get('merged_head') == pull.get('headRefOid') and existing.get('merge_commit') == (pull.get('mergeCommit') or {}).get('oid'):
            continue
        graph_count += 1
        try:
            evidence = ancestry(record, pull, compare_fn=compare_fn, now=now)
            if evidence:
                graphs[identity] = evidence
        except (OSError, RuntimeError, ValueError, TypeError, subprocess.TimeoutExpired) as error:
            errors.append(f'#{record["pr_number"]} ancestry: {type(error).__name__}')
    return errors
