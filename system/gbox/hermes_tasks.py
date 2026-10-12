"""Read-only view of Hermes cron runs for the gBox Tasks panel.

Hermes owns these files. Keep a failed or missing Hermes installation from
breaking the ordinary gBox task inventory.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import re
import sqlite3


RUN_ID = re.compile(r"[0-9a-f]{32}\Z")


def _home() -> Path:
    return Path(os.environ.get("GBOX_HERMES_HOME") or Path.home() / ".hermes")


def _db(path: Path):
    if not path.is_file():
        return None
    db = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=1)
    db.row_factory = sqlite3.Row
    return db


def _stamp(value: str | None) -> float | None:
    try:
        return dt.datetime.fromisoformat(value).timestamp() if value else None
    except (TypeError, ValueError):
        return None


def _jobs(home: Path) -> dict[str, str]:
    try:
        data = json.loads((home / "cron" / "jobs.json").read_text(encoding="utf-8"))
        return {j["id"]: j.get("name") or j["id"] for j in data.get("jobs", []) if j.get("id")}
    except (OSError, ValueError, TypeError):
        return {}


def _session(db: sqlite3.Connection, job_id: str, started: float | None):
    # An unsuccessful scheduler claim has no Hermes conversation. A real run
    # creates a session within seconds of its execution start.
    # Match by start time, not among the job's newest sessions: a busy job has
    # far more than 10 sessions, and older runs would lose their model/tickets.
    if not started:
        return None
    rows = db.execute(
        "SELECT * FROM sessions WHERE source='cron' AND id LIKE ? "
        "AND started_at BETWEEN ? AND ? ORDER BY started_at DESC LIMIT 10",
        (f"cron_{job_id}_%", started - 120, started + 120),
    ).fetchall()
    nearest = min(rows, key=lambda s: abs(s["started_at"] - started)) if rows and started else None
    return nearest if nearest and abs(nearest["started_at"] - started) < 120 else None


def _last_action(db: sqlite3.Connection, session_id: str) -> str:
    row = db.execute(
        "SELECT role, content, tool_name, tool_calls FROM messages WHERE session_id=? "
        "AND role IN ('assistant','tool') ORDER BY id DESC LIMIT 1", (session_id,),
    ).fetchone()
    if not row:
        return "Hermes is starting"
    if row["role"] == "tool":
        return f"Finished {row['tool_name'] or 'tool'}"
    if row["content"]:
        return row["content"].strip().splitlines()[0][:140]
    return "Hermes is using a tool" if row["tool_calls"] else "Hermes is working"


def _owned_requests(db: sqlite3.Connection, session_id: str) -> list[str]:
    """Only acknowledged work reserves tickets; reading or attempting does not."""
    try:
        rows = db.execute(
            "SELECT role,content,tool_name,tool_call_id,tool_calls FROM messages "
            "WHERE session_id=? AND role IN ('assistant','tool') ORDER BY id", (session_id,)
        ).fetchall()
    except sqlite3.Error:
        # Older/missing transcript schemas cannot establish a response identity,
        # but must not hide the ordinary run viewer.
        return []
    return confirmed_request_ids([dict(row) for row in rows])


def confirmed_request_ids(messages: list[dict]) -> list[str]:
    """Pure successful-work evidence shared with finalized usage accounting.

    The shared scanner pairs by call ID and exact action and unwraps known MCP
    envelopes. Payload prose and read-only request results never assign work.
    Multiple confirmed tickets are returned without allocating session tokens.
    """
    # Lazy import keeps accounting's existing dependency on this run viewer
    # acyclic while sharing its pure response parser.
    from . import hermes_accounting
    try:
        calls = hermes_accounting._calls(messages)
    except (hermes_accounting.Deferred, TypeError, AttributeError):
        return []
    owned = set()
    actions = {'reply_request', 'set_request_status', 'start_job', 'prepare_task_workspace',
               'publish_task_changes', 'capture_request_screenshot', 'capture_worker_screen',
               'record_request_metrics'}
    for call in calls:
        if not isinstance(call.get('name'), str) or not isinstance(call.get('call_id'), str) or not call['call_id']:
            continue
        action = call['name'].removeprefix('mcp__gbox__')
        if action not in actions and not action.startswith('job_'):
            continue
        if not call['has_response'] or call['wrapped_ambiguous'] or call['rejected']:
            continue
        args, result = call['args'], call['result']
        if not isinstance(args, dict) or not isinstance(result, dict):
            continue
        ids = {source[key] for source in (args, args.get('input'), args.get('inputs'), args.get('metrics'))
               if isinstance(source, dict) for key in ('request_id', 'parent_request_id')
               if isinstance(source.get(key), str) and re.fullmatch(r'[0-9a-f]{16}', source[key])}
        if len(ids) != 1:
            continue
        rid = next(iter(ids))
        if any(result.get(key) not in (None, rid) for key in ('request_id', 'parent_request_id', 'attached_request_id')):
            continue
        if action.startswith('job_') or action == 'start_job':
            tool = action[4:] if action.startswith('job_') else args.get('tool')
            ok = (isinstance(result.get('id'), str) and re.fullmatch(r'[0-9a-f]{16}', result['id'])
                  and result.get('state') in ('queued', 'running', 'succeeded')
                  and isinstance(tool, str) and result.get('tool') == tool)
        elif action in ('prepare_task_workspace', 'publish_task_changes'):
            ok = result.get('request_id') == rid and isinstance(result.get('path'), str) and bool(result['path'])
        elif action == 'capture_request_screenshot':
            attachments = result.get('attachments')
            ok = result.get('author') == 'agent' and isinstance(attachments, list) and any(
                isinstance(a, dict) and isinstance(a.get('sha256'), str)
                and re.fullmatch(r'[0-9a-f]{64}', a['sha256']) for a in attachments)
        elif action == 'capture_worker_screen':
            ok = (result.get('attached_request_id') == rid and isinstance(result.get('sha256'), str)
                  and re.fullmatch(r'[0-9a-f]{64}', result['sha256']))
        elif action == 'set_request_status':
            ok = ((result.get('request_id') or result.get('id')) == rid
                  and args.get('status') in ('open', 'in_progress', 'done', 'blocked')
                  and result.get('status') == args['status'])
        else:
            field = 'metrics' if action == 'record_request_metrics' else 'posted_message'
            ok = (result.get('ok') is True and result.get('request_id') == rid
                  and isinstance(result.get(field), dict))
        if ok:
            owned.add(rid)
    return sorted(owned)


def _usage(session) -> dict:
    def value(key, default=0):
        return session[key] if session and key in session.keys() and session[key] is not None else default
    # Hermes CanonicalUsage.input_tokens excludes cache reads and writes.
    # Its prompt_tokens property is the sum of all three input categories.
    detail = {k: value(k) for k in ('input_tokens', 'cache_read_tokens', 'cache_write_tokens',
                                  'reasoning_tokens', 'api_call_count')}
    detail.update({k: value(k, None) for k in ('actual_cost_usd', 'estimated_cost_usd', 'cost_status')})
    return {'tokens_in': sum(detail[k] for k in ('input_tokens', 'cache_read_tokens', 'cache_write_tokens')),
            'tokens_out': value('output_tokens'), 'tokens_detail': detail}


def _script_output(home, job_id, finished):
    if not finished:
        return ''
    files = list((home / 'cron/output' / job_id).glob('*.md'))
    nearest = min(files, key=lambda p: abs(p.stat().st_mtime - finished)) if files else None
    return nearest.read_text(encoding='utf-8')[-70000:] if nearest and abs(nearest.stat().st_mtime - finished) < 120 else ''


DEFAULT_RUNS, MAX_RUNS = 20, 100
STREAK_CAP = 3          # consecutive inbox task-mode runs one ticket may take (#1300 gap 3)
TASK_MODE_NAME = "gBox inbox task mode"


def ticket_streaks(runs: list[dict], last_operator: dict[str, float] | None = None,
                   cap: int = STREAK_CAP, name: str = TASK_MODE_NAME) -> dict[str, dict]:
    """Tickets the recurring inbox job has worked `cap` or more ended runs in a row.

    `runs` are list_runs/`/api/tasks` rows in any order. Only ended runs of the
    recurring job count: one-shot dispatches for a ticket are deliberate. A run
    that confirmed no ticket neither counts nor breaks a streak, and an operator
    message on a ticket (``last_operator[rid]`` = its newest timestamp) restarts
    that ticket's count, because the operator asked for more.
    Returns ``{rid: {"runs": n, "run_ids": [...], "since": oldest start}}``.
    """
    last_operator = last_operator or {}
    ended = sorted((r for r in runs if r.get("name") == name and r.get("state") not in ("claimed", "running")),
                   key=lambda r: r.get("started") or 0, reverse=True)
    worked = []
    for run in ended:
        rids = set(run.get("request_ids") or []) | {t.get("id") for t in run.get("tickets") or [] if t.get("id")}
        if rids:
            worked.append((run, rids))
    if not worked:
        return {}
    out = {}
    for rid in worked[0][1]:
        streak = []
        for run, rids in worked:
            if rid not in rids or (run.get("started") or 0) <= last_operator.get(rid, 0):
                break
            streak.append(run)
        if len(streak) >= cap:
            out[rid] = {"runs": len(streak), "run_ids": [r.get("id") for r in streak],
                        "since": streak[-1].get("started")}
    return out


def capped_note(streak: dict) -> str:
    return (f"The last {streak['runs']} inbox runs in a row all worked this ticket with no new operator message. "
            "Choose another actionable request this run; return to this one only if no other actionable "
            "operator request exists.")


def list_runs(limit: int = DEFAULT_RUNS) -> list[dict]:
    """Return actual Hermes agent runs, omitting scheduler claims that never started.

    Maintenance scripts run every few minutes and outnumber agent runs, so the
    scan reads many more execution rows than it returns; a job without a Hermes
    session (a script) keeps only its newest finished row.
    """
    limit = max(1, min(int(limit or DEFAULT_RUNS), MAX_RUNS))
    home = _home()
    try:
        db = _db(home / "cron" / "executions.db")
        state = _db(home / "state.db")
        if not db:
            if state:
                state.close()
            return []
        with db:
            rows = db.execute(
                "SELECT id,job_id,status,started_at,finished_at,error FROM executions "
                "WHERE started_at IS NOT NULL ORDER BY CASE WHEN status='running' "
                "THEN 0 ELSE 1 END, started_at DESC LIMIT ?", (max(200, limit * 25),),
            ).fetchall()
        names = _jobs(home)
        try:
            from .hermes_work_queue import claims
            queue_claims = claims()
        except (OSError, ValueError, KeyError):
            queue_claims = {}
        out, terminal_scripts = [], set()
        for r in rows:
            if len(out) >= limit:
                break
            started = _stamp(r["started_at"])
            session = _session(state, r["job_id"], started) if state else None
            if not session and r['status'] not in ('claimed', 'running'):
                if r['job_id'] in terminal_scripts:
                    continue
                terminal_scripts.add(r['job_id'])
            out.append({"id": r["id"], "job_id": r["job_id"], "name": names.get(r["job_id"], r["job_id"]),
                        "state": r["status"], "started": started, "finished": _stamp(r["finished_at"]),
                        "model": session["model"] if session else None,
                        "provider": session['billing_provider'] if session and 'billing_provider' in session.keys() else None,
                        **_usage(session),
                        "request_ids": sorted(set(_owned_requests(state, session['id']) if session else []) |
                                              ({queue_claims[r['job_id']]} if r['status'] in ('claimed', 'running')
                                               and r['job_id'] in queue_claims else set())),
                        "progress": _last_action(state, session["id"]) if session else
                                    ('Maintenance is running' if r['status'] in ('claimed', 'running') else
                                     'Completed without inference' if r['status'] == 'completed' else 'Run failed before inference'),
                        "error": r["error"]})
        db.close()
        if state:
            state.close()
        return out[:limit]
    except (OSError, ValueError, sqlite3.Error):
        return []


def _tool_calls(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        calls = json.loads(raw)
        out = []
        for call in calls:
            fn = call.get("function") or {}
            args = json.loads(fn.get("arguments") or "{}")
            if fn.get("name") == "tool_call" and isinstance(args.get("calls"), list):
                out.extend(f"→ {c.get('name', 'tool')} {json.dumps(c.get('arguments', {}), ensure_ascii=False)[:1200]}" for c in args["calls"])
            else:
                out.append(f"→ {fn.get('name', 'tool')} {json.dumps(args, ensure_ascii=False)[:1200]}")
        return out
    except (TypeError, ValueError):
        return ["→ tool call (arguments unavailable)"]


def _structured_calls(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        calls = json.loads(raw)
        out = []
        for call in calls:
            fn = call.get("function") or {}
            args = json.loads(fn.get("arguments") or "{}")
            nested = args.get("calls") if fn.get("name") == "tool_call" else None
            for item in nested if isinstance(nested, list) else [{"name": fn.get("name"), "arguments": args}]:
                out.append({"action": item.get("name") or "tool", "input": item.get("arguments") or {}})
        return out
    except (TypeError, ValueError, AttributeError):
        return [{"action": "tool", "input": {"error": "arguments unavailable"}}]


def _tool_text(content: str) -> str:
    if content.startswith("<untrusted_tool_result") and "\n\n" in content:
        content = content.split("\n\n", 1)[1].rsplit("</untrusted_tool_result>", 1)[0]
    try:
        data = json.loads(content)
        if isinstance(data, dict) and isinstance(data.get("result"), str):
            content = data["result"]
            try:
                content = json.dumps(json.loads(content), ensure_ascii=False, indent=2)
            except ValueError:
                pass
    except ValueError:
        pass
    return content.strip()[:5000]


def get_run(run_id: str) -> dict | None:
    if not RUN_ID.fullmatch(run_id):
        return None
    home = _home()
    try:
        db = _db(home / "cron" / "executions.db")
        if not db:
            return None
        r = db.execute("SELECT * FROM executions WHERE id=?", (run_id,)).fetchone()
        db.close()
        if not r:
            return None
        started = _stamp(r["started_at"])
        state = _db(home / "state.db")
        session = _session(state, r["job_id"], started) if state else None
        request_ids = _owned_requests(state, session['id']) if session else []
        lines = []
        if session:
            messages = state.execute(
                "SELECT role,content,tool_name,tool_calls FROM messages WHERE session_id=? "
                "AND role IN ('assistant','tool') ORDER BY id DESC LIMIT 120", (session["id"],),
            ).fetchall()
            for m in reversed(messages):
                if m["role"] == "assistant":
                    if m["content"]:
                        lines.append("Hermes: " + m["content"].strip()[:5000])
                    lines.extend(_tool_calls(m["tool_calls"]))
                else:
                    lines.append(f"← {m['tool_name'] or 'tool'}: {_tool_text(m['content'] or '')}")
            state.close()
        elif state:
            state.close()
        if not session:
            lines.append(_script_output(home, r['job_id'], _stamp(r['finished_at'])))
        if r["error"]:
            lines.append("Error: " + r["error"])
        return {"id": run_id, "job_id": r["job_id"], "name": _jobs(home).get(r["job_id"], r["job_id"]),
                "state": r["status"], "started": started, "finished": _stamp(r["finished_at"]),
                "session_id": session["id"] if session else None, "model": session["model"] if session else None,
                "provider": session['billing_provider'] if session and 'billing_provider' in session.keys() else None,
                **_usage(session),
                "request_ids": request_ids,
                "output": "\n\n".join(lines)[-70000:] or "Hermes has not emitted output yet."}
    except (OSError, ValueError, sqlite3.Error):
        return None


_get_run_output = get_run


def _tool_failed(content: str) -> bool:
    """Classify structured outcomes, not mentions of errors in successful output."""
    if content.startswith('<untrusted_tool_result') and '\n\n' in content:
        content = content.split('\n\n', 1)[1].rsplit('</untrusted_tool_result>', 1)[0]
    try:
        data = json.loads(content)
    except (ValueError, TypeError):
        text = content.lstrip()
        if text.startswith(('BLOCKED:', 'ERROR:')):
            return True
        # Some MCP bridges return requests' transport exception as the result
        # string instead of setting isError. Match its direct failure envelope,
        # not quoted errors or successful terminal/documentation output.
        first_line = text.splitlines()[0] if text else ''
        return bool(re.match(r'Request failed:\s*HTTPS?ConnectionPool\(', first_line)
                    and any(reason in first_line.lower() for reason in (
                        'max retries exceeded with url:', 'failed to establish a new connection',
                        'connection refused', 'read timed out', 'connect timeout')))
    if not isinstance(data, dict):
        return False
    if data.get('error') or data.get('isError') or data.get('is_error'):
        return True
    if data.get('exit_code') not in (None, 0, '0'):
        return True
    if data.get('status') in ('error', 'failed', 'blocked', 'denied') or data.get('state') == 'failed':
        return True
    nested = data.get('result')
    if isinstance(nested, dict):
        return _tool_failed(json.dumps(nested))
    if isinstance(nested, str):
        return _tool_failed(nested)
    return False


def get_run(run_id: str) -> dict | None:
    """Return the transcript plus every individual tool attempt and its result."""
    run = _get_run_output(run_id)
    if not run:
        return None
    run["steps"], run["request_id"] = [], None
    if not run["session_id"]:
        # Script-only maintenance runs have no LLM session. Their report is the
        # durable progress stream, identified by the job's explicit prompt.
        try:
            jobs = json.loads((_home() / 'cron/jobs.json').read_text()).get('jobs', [])
            job = next((j for j in jobs if j.get('id') == run['job_id']), {})
            match = re.search(r'\brequest_id=([0-9a-f]{16})\b', job.get('prompt') or '')
            if match:
                run['request_id'] = match[1]
        except (OSError, ValueError):
            pass
        return run
    try:
        state = _db(_home() / "state.db")
        if not state:
            return run
        with state:
            rows = state.execute(
                "SELECT role,content,tool_name,tool_calls FROM messages WHERE session_id=? "
                "AND role IN ('assistant','tool') ORDER BY id", (run["session_id"],),
            ).fetchall()
        attempts = {}
        for m in rows:
            if m["role"] == "assistant":
                for call in _structured_calls(m["tool_calls"]):
                    action = call["action"]
                    attempts[action] = attempts.get(action, 0) + 1
                    run["steps"].append({"action": action, "attempt": attempts[action],
                                         "input": call["input"], "result": "Awaiting tool result", "status": "running"})
                    # The general inbox cron can touch multiple tickets in one
                    # run. A tool argument is not a reliable run-level report.
                    if run["name"] != "gBox inbox task mode" and isinstance(call["input"], dict):
                        run["request_id"] = run["request_id"] or call["input"].get("request_id") or call["input"].get("parent_request_id")
            else:
                result = _tool_text(m["content"] or "")
                for step in reversed(run["steps"]):
                    if step["status"] == "running" and step["action"].replace("mcp__gbox__", "") == (m["tool_name"] or "").replace("mcp__gbox__", ""):
                        step.update(result=result, status="failed" if _tool_failed(m["content"] or '') else "finished")
                        break
        state.close()
    except (OSError, ValueError, sqlite3.Error):
        pass
    return run
