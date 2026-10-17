"""Read-only, run-scoped tool budgets which survive Hermes context compaction.

Scheduler heartbeats and model-call totals are not tool attempts. Hermes keeps
copies of the same call when compacting: count each call ID once, including the
individual attempts in a tool_call batch. A durable count is used only when an
active execution, its original assignment, its observed billing endpoint and a
call in the incoming conversation all identify the same session.
"""
from __future__ import annotations

import datetime
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3

ASSIGNMENT = re.compile(r'Assigned queue task: request #(\d+) \(([0-9a-f]{16})\)')
MAX_EXECUTIONS = 128
MAX_ROWS = 1024
MAX_CALL_BYTES = 256 << 10
MAX_TOTAL_BYTES = 2 << 20
MAX_ASSIGNMENT_BYTES = 64 << 10


def assignment(messages):
    found = {match.groups() for message in messages if isinstance(message, dict)
             and message.get('role') in ('user', 'assistant')
             for match in ASSIGNMENT.finditer(str(message.get('content') or ''))}
    return next(iter(found)) if len(found) == 1 else None


def calls(messages):
    """Return unique call identities plus unidentifiable visible attempts.

    Missing IDs can still consume the visible budget, but cannot establish
    durable attribution. Conflicting reuse of an ID also fails attribution.
    """
    identities, anonymous, valid = {}, 0, True
    for message in messages:
        if not isinstance(message, dict) or message.get('role') != 'assistant':
            continue
        raw_calls = message.get('tool_calls') or []
        if not isinstance(raw_calls, list):
            anonymous += 1; valid = False
            continue
        for call in raw_calls:
            if not isinstance(call, dict):
                anonymous += 1; valid = False
                continue
            fn = call.get('function') or {}
            if not isinstance(fn, dict):
                anonymous += 1; valid = False
                continue
            args = fn.get('arguments') or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    pass
            batch = args.get('calls') if fn.get('name') == 'tool_call' and isinstance(args, dict) else None
            count = max(1, len(batch)) if isinstance(batch, list) else 1
            signature = json.dumps([fn.get('name'), args], sort_keys=True, separators=(',', ':'))
            identity = call.get('id')
            if not isinstance(identity, str) or not identity or len(identity) > 256:
                anonymous += count; valid = False
                continue
            if identity in identities and identities[identity] != (signature, count):
                valid = False
            else:
                identities[identity] = (signature, count)
    return identities, anonymous, valid


def _db(path):
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=0.1)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    return db


def _stamp(value):
    return datetime.datetime.fromisoformat(value).timestamp()


def measure(messages, endpoint, *, home=None):
    """Bounded indexed reads; no Store, migrations, writes, claims or model calls.

    On missing or ambiguous identity, retain only the visible conversation's
    count. Never borrow a previous execution's tools, even for the same ticket.
    """
    visible, anonymous, valid = calls(messages)
    result = {'attempts': sum(v[1] for v in visible.values()) + anonymous,
              'source': 'visible_messages', 'reason': 'unconfirmed_run_identity'}
    task = assignment(messages)
    if not task or not visible or not valid or not endpoint:
        return result
    recent = dict(list(visible.items())[-8:])
    home = Path(home or os.environ.get('HERMES_HOME') or Path.home() / '.hermes')
    matches = []
    try:
        with closing(_db(home / 'cron/executions.db')) as executions, closing(_db(home / 'state.db')) as state:
            runs = executions.execute("SELECT id,job_id,started_at FROM executions "
                "WHERE status IN ('running','claimed') AND started_at IS NOT NULL LIMIT ?",
                (MAX_EXECUTIONS + 1,)).fetchall()
            if len(runs) > MAX_EXECUTIONS:
                return result | {'reason': 'execution_read_bound'}
            read_bytes = read_rows = 0
            for run in runs:
                if not re.fullmatch(r'[0-9a-f]{12,64}', run['job_id']):
                    continue
                started = _stamp(run['started_at'])
                sessions = state.execute("SELECT id,started_at,billing_base_url FROM sessions "
                    "WHERE source='cron' AND id GLOB ? AND started_at BETWEEN ? AND ? "
                    "AND ended_at IS NULL LIMIT 2",
                    (f"cron_{run['job_id']}_*", started - 120, started + 120)).fetchall()
                if len(sessions) != 1:
                    continue
                session = sessions[0]
                # This is the endpoint recorded by this actual run, not a model
                # name or the controller's mutable current provider selection.
                if (session['billing_base_url'] or '').rstrip('/') != endpoint.rstrip('/'):
                    continue
                original = state.execute("SELECT CASE WHEN length(CAST(content AS BLOB))<=? THEN content END,"
                    "length(CAST(content AS BLOB)) FROM messages "
                    "WHERE session_id=? AND role='user' ORDER BY id LIMIT 1",
                    (MAX_ASSIGNMENT_BYTES, session['id'])).fetchone()
                if not original or original[0] is None or original[1] > MAX_ASSIGNMENT_BYTES:
                    continue
                if assignment([{'role': 'user', 'content': original[0]}]) != task:
                    continue
                rows = state.execute("SELECT CASE WHEN length(CAST(tool_calls AS BLOB))<=? THEN tool_calls END AS calls,"
                    "length(CAST(tool_calls AS BLOB)) AS bytes FROM messages WHERE session_id=? AND role='assistant' "
                    "AND tool_calls IS NOT NULL ORDER BY id LIMIT ?",
                    (MAX_CALL_BYTES, session['id'], MAX_ROWS + 1)).fetchall()
                read_rows += len(rows)
                read_bytes += sum(r['bytes'] for r in rows)
                if read_rows > MAX_ROWS or read_bytes > MAX_TOTAL_BYTES or any(r['calls'] is None for r in rows):
                    return result | {'reason': 'transcript_read_bound'}
                durable, missing, consistent = calls([{'role': 'assistant', 'tool_calls': json.loads(r['calls'])} for r in rows])
                # Hermes may send the newest call before persisting that row.
                # At least one recent immutable call must anchor this run; all
                # IDs already present must still agree, including older calls.
                if missing or not consistent or not any(durable.get(k) == v for k, v in recent.items()):
                    continue
                if any(k in durable and durable[k] != v for k, v in visible.items()):
                    return result | {'reason': 'conflicting_call_identity'}
                matches.append((run, session, durable))
            if len(matches) != 1:
                return result | {'reason': 'ambiguous_run_identity' if matches else 'unconfirmed_run_identity'}
            run, session, durable = matches[0]
            # Include not-yet-persisted visible calls, once per immutable ID.
            if any(k in durable and durable[k] != v for k, v in visible.items()):
                return result | {'reason': 'conflicting_call_identity'}
            combined = durable | visible
            return {'attempts': sum(v[1] for v in combined.values()), 'source': 'durable_transcript',
                    'execution_id': run['id'], 'session_id': session['id'], 'request_id': task[1],
                    'reason': 'active_execution_assignment_endpoint_and_calls_match'}
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        return result | {'reason': 'run_evidence_unavailable'}
