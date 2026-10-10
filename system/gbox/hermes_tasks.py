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
    rows = db.execute(
        "SELECT id, started_at, model, input_tokens, output_tokens FROM sessions "
        "WHERE source='cron' AND id LIKE ? ORDER BY started_at DESC LIMIT 10",
        (f"cron_{job_id}_%",),
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


def list_runs(limit: int = 8) -> list[dict]:
    """Return actual Hermes agent runs, omitting scheduler claims that never started."""
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
                "WHERE started_at IS NOT NULL ORDER BY started_at DESC LIMIT ?", (max(1, min(limit, 20)),),
            ).fetchall()
        names = _jobs(home)
        out = []
        for r in rows:
            started = _stamp(r["started_at"])
            session = _session(state, r["job_id"], started) if state else None
            out.append({"id": r["id"], "job_id": r["job_id"], "name": names.get(r["job_id"], r["job_id"]),
                        "state": r["status"], "started": started, "finished": _stamp(r["finished_at"]),
                        "model": session["model"] if session else None,
                        "tokens_in": session["input_tokens"] if session else 0,
                        "tokens_out": session["output_tokens"] if session else 0,
                        "progress": _last_action(state, session["id"]) if session else "Hermes is starting",
                        "error": r["error"]})
        db.close()
        if state:
            state.close()
        return out
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
        if r["error"]:
            lines.append("Error: " + r["error"])
        return {"id": run_id, "job_id": r["job_id"], "name": _jobs(home).get(r["job_id"], r["job_id"]),
                "state": r["status"], "started": started, "finished": _stamp(r["finished_at"]),
                "session_id": session["id"] if session else None, "model": session["model"] if session else None,
                "tokens_in": session["input_tokens"] if session else 0,
                "tokens_out": session["output_tokens"] if session else 0,
                "output": "\n\n".join(lines)[-70000:] or "Hermes has not emitted output yet."}
    except (OSError, ValueError, sqlite3.Error):
        return None


_get_run_output = get_run


def get_run(run_id: str) -> dict | None:
    """Return the transcript plus every individual tool attempt and its result."""
    run = _get_run_output(run_id)
    if not run:
        return None
    run["steps"], run["request_id"] = [], None
    if not run["session_id"]:
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
                    if isinstance(call["input"], dict):
                        run["request_id"] = run["request_id"] or call["input"].get("request_id") or call["input"].get("parent_request_id")
            else:
                result = _tool_text(m["content"] or "")
                for step in reversed(run["steps"]):
                    if step["status"] == "running" and step["action"].replace("mcp__gbox__", "") == (m["tool_name"] or "").replace("mcp__gbox__", ""):
                        step.update(result=result, status="failed" if '"error"' in result[:200] else "finished")
                        break
        state.close()
    except (OSError, ValueError, sqlite3.Error):
        pass
    return run
