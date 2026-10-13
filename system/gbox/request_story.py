"""The resolution story of one inbox request, for the desktop app's Detailed report (GET /api/requests/{id}/story).

The story is assembled in order from records gBox already keeps:

* the ticket itself (created/started/completed, its messages and their ``task_step`` entries),
* triage: who took the ticket first (a Hermes run that confirmed work on it, the gBox resolution agent's chat, a
  dispatch/claim step on the ticket, or the audited ``in_progress`` change),
* identification: every tool call (the resolution agent's chat events, the Hermes runs' tool calls, the ticket's
  task steps) with its input summarised,
* work: each Hermes run with its exact per-model usage (the ``hermes_run_<run>_model_<hash>_final_recorded_usage``
  records ``hermes_accounting`` writes into ``metrics.tokens_detail``), other solvers from
  ``metrics.usage_by_solver``, the local agent's usage, and the jobs the ticket started,
* code changes: the PRs linked to the ticket ("Published tested task changes: <url>", "PR #N merged to main as
  <sha>", the Hermes publication record), with files, folders and +/- lines from the local git repository when it
  is available, else the file list the publication recorded (no line counts),
* replies and the final resolution.

Nothing is invented. A value that was not recorded is ``None`` and the reason is listed in ``missing``. Cost is the
one derived number: the Hermes ledger's actual or estimated cost when it has one, otherwise tokens times a per-
provider price table (``[token_prices]`` in gbox.toml over the defaults below), always labelled as an estimate.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path, PurePosixPath

# USD per million tokens. Rough public list prices, used only when the provider's own ledger has no cost.
# Override or extend in gbox.toml:  [token_prices]  "zai/glm-5.3" = { in = 0.6, out = 2.2, cache_read = 0.11 }
# Keys are "provider/model" (exact) or "provider". A provider missing here gets no cost (None), never a guess.
DEFAULT_PRICES: dict[str, dict[str, float]] = {
    "zai": {"in": 0.60, "out": 2.20, "cache_read": 0.11},
    "deepseek": {"in": 0.28, "out": 0.42, "cache_read": 0.028},
    "anthropic": {"in": 3.00, "out": 15.00, "cache_read": 0.30},
    "openai": {"in": 1.25, "out": 10.00, "cache_read": 0.125},
    "openai-codex": {"in": 1.25, "out": 10.00, "cache_read": 0.125},
    "google": {"in": 1.25, "out": 10.00},
    "gemini": {"in": 1.25, "out": 10.00},
    "ollama": {"in": 0.0, "out": 0.0},          # gBox's own local models: no bill
    "local": {"in": 0.0, "out": 0.0},
}
PRICE_NOTE = ("Costs are estimates unless marked actual: the provider ledger's own figure when it has one, otherwise "
              "recorded tokens x the price table (USD per million tokens; [token_prices] in gbox.toml).")

REPO_URL = r"https://github\.com/[\w.-]+/[\w.-]+/pull/(\d+)"
PUBLISHED = re.compile(r"Published tested task changes: (" + REPO_URL + r")")
PULL_URL = re.compile(REPO_URL)
MERGED = re.compile(r"PR #(\d+) merged to ([\w./-]+) as ([0-9a-f]{7,40})(?: at (.+?UTC))?")
CLOSED = re.compile(r"PR #(\d+) closed without merge(?: at (.+?UTC))?")
ON_MAIN = re.compile(r"branch (hermes/[\w./-]+) \(head ([0-9a-f]{7,40})\)")
RECOVERY = re.compile(r"Opened draft PR #(\d+)")
MARKER = re.compile(r"hermes_run_([0-9a-f]{32})_model_[0-9a-f]{20}_final_recorded_usage\Z")
CLAIM_WORDS = re.compile(r"dispatch|claim|triage|assign|pick|take|queued for hermes", re.I)

MAX_STEPS = 200
MAX_FILES = 300
MAX_HUNKS = 24


# ---------------------------------------------------------------------------------------------------------------
# small helpers
def summarise(value, n: int = 160) -> str:
    """One readable line for a tool input or result: dicts as key=value pairs, text with whitespace collapsed."""
    if value is None or value == "" or value == {}:
        return ""
    if isinstance(value, str):
        text = value
        try:                                   # tool results are often JSON text
            parsed = json.loads(value)
            if isinstance(parsed, (dict, list)):
                return summarise(parsed, n)
        except (ValueError, TypeError):
            pass
    elif isinstance(value, dict):
        parts = []
        for k, v in value.items():
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False, default=str)
            parts.append(f"{k}={v}")
        text = ", ".join(parts)
    else:
        text = json.dumps(value, ensure_ascii=False, default=str)
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "\u2026"


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _dur(a, b):
    a, b = _num(a), _num(b)
    return round(b - a, 1) if a is not None and b is not None and b >= a else None


def _stamp(text):
    """'2026-10-01 12:00:00 UTC' (the reconciler's format) -> epoch seconds, else None."""
    if not text:
        return None
    try:
        import datetime as dt
        return dt.datetime.strptime(text.strip(), "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=dt.timezone.utc).timestamp()
    except ValueError:
        return None


def price_for(prices: dict, provider, model):
    """(key, {in, out[, cache_read]}) from the table: provider/model first, then provider; (None, None) if unknown."""
    if not provider:
        return None, None
    p = str(provider).lower()
    for key in ((f"{p}/{str(model).lower()}" if model else None), p):
        if key and isinstance(prices.get(key), dict) and _num(prices[key].get("in")) is not None \
                and _num(prices[key].get("out")) is not None:
            return key, prices[key]
    return None, None


def cost_of(prices: dict, provider, model, tokens_in, tokens_out, *, cache_read=None, actual=None, estimated=None):
    """{usd, kind: actual|estimate|unknown, basis} for one usage record. Never a number without a basis."""
    if _num(actual) is not None:
        return {"usd": round(float(actual), 6), "kind": "actual", "basis": "provider ledger (billed)"}
    if _num(estimated) is not None:
        return {"usd": round(float(estimated), 6), "kind": "estimate", "basis": "provider ledger estimate"}
    if _num(tokens_in) is None or _num(tokens_out) is None:
        return {"usd": None, "kind": "unknown", "basis": "token counts not recorded"}
    key, price = price_for(prices, provider, model)
    if price is None:
        who = "/".join(x for x in (provider, model) if x) or "an unnamed provider"
        return {"usd": None, "kind": "unknown", "basis": f"no price for {who} in the price table"}
    cached = _num(cache_read) or 0
    cached = min(cached, tokens_in)
    read_rate = _num(price.get("cache_read"))
    usd = ((tokens_in - cached) * price["in"] + cached * (read_rate if read_rate is not None else price["in"])
           + tokens_out * price["out"]) / 1e6
    return {"usd": round(usd, 6), "kind": "estimate",
            "basis": f"price table '{key}': ${price['in']}/M in, ${price['out']}/M out"
                     + (f", ${read_rate}/M cache reads" if read_rate is not None and cached else "")}


def folder_of(path: str) -> str:
    parent = str(PurePosixPath(path).parent)
    return "" if parent == "." else parent


def group_folders(files: list[dict]) -> list[dict]:
    """Files grouped by their folder, with summed +/- (None when any file's count is unknown)."""
    out: dict[str, dict] = {}
    for f in files:
        d = out.setdefault(f["folder"], {"path": f["folder"], "files": 0, "added": 0, "deleted": 0})
        d["files"] += 1
        for k in ("added", "deleted"):
            d[k] = None if d[k] is None or f.get(k) is None else d[k] + f[k]
    return sorted(out.values(), key=lambda d: d["path"])


# ---------------------------------------------------------------------------------------------------------------
# local git (GitHub-free): +/- per file and hunk headers for a commit or a range
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")


def parse_diff(text: str) -> list[dict]:
    """`git diff -U0` text -> [{path, folder, added, deleted, binary, hunks: [{old, new, added, deleted, context}]}]."""
    files, cur, hunk = [], None, None
    for line in text.splitlines():
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(.*) b/(.*)$", line)
            path = m[2] if m else line[11:]
            cur = {"path": path, "folder": folder_of(path), "added": 0, "deleted": 0, "binary": False, "hunks": [],
                   "hunks_total": 0}
            files.append(cur)
            hunk = None
        elif cur is None:
            continue
        elif line.startswith("Binary files "):
            cur.update(binary=True, added=None, deleted=None)
        elif line.startswith("+++ ") or line.startswith("--- "):
            continue
        elif line.startswith("@@"):
            m = _HUNK.match(line)
            cur["hunks_total"] += 1
            hunk = None
            if m and len(cur["hunks"]) < MAX_HUNKS:
                hunk = {"old": int(m[1]), "new": int(m[3]), "added": 0, "deleted": 0, "context": m[5].strip()[:80]}
                cur["hunks"].append(hunk)
        elif line.startswith("+") and not cur["binary"]:
            cur["added"] += 1
            if hunk:
                hunk["added"] += 1
        elif line.startswith("-") and not cur["binary"]:
            cur["deleted"] += 1
            if hunk:
                hunk["deleted"] += 1
    return files


def _git(repo: Path, *args, timeout=15, limit=6_000_000):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=timeout)
    if r.returncode:
        return None
    return r.stdout[:limit].decode("utf-8", "replace")


def repositories() -> list[Path]:
    """Local clones that may hold the ticket's commits: the Hermes repository, then this checkout."""
    out = []
    try:
        from . import hermes_delivery
        out.append(hermes_delivery.repository())
    except Exception:
        pass
    out.append(Path(__file__).resolve().parents[2])
    seen, found = set(), []
    for p in out:
        if p in seen or not p.exists():
            continue
        seen.add(p)
        if _git(p, "rev-parse", "--git-dir", timeout=5) is not None:
            found.append(p)
    return found


def local_diff(spec: dict, repos: list[Path] | None = None):
    """{files, source, repository} for {"commit": sha} (vs its first parent) or {"base", "head"}; None if not local."""
    for repo in repos if repos is not None else repositories():
        try:
            if spec.get("commit"):
                sha = (_git(repo, "rev-parse", "--verify", "--quiet", spec["commit"] + "^{commit}", timeout=5) or "").strip()
                if not sha:
                    continue
                parent = (_git(repo, "rev-parse", "--verify", "--quiet", sha + "^1", timeout=5) or "").strip()
                rng = [parent, sha] if parent else ["4b825dc642cb6eb9a060e54bf8d69288fbee4904", sha]
            else:
                rng = []
                for ref in (spec.get("base"), spec.get("head")):
                    sha = (_git(repo, "rev-parse", "--verify", "--quiet", str(ref) + "^{commit}", timeout=5) or "").strip()
                    if not sha:
                        break
                    rng.append(sha)
                if len(rng) != 2:
                    continue
            text = _git(repo, "diff", "-U0", "--no-color", "--no-ext-diff", "--no-renames", *rng, timeout=30)
            if text is None:
                continue
            return {"files": parse_diff(text), "source": "local git", "range": [r[:12] for r in rng]}
        except (OSError, subprocess.SubprocessError):
            continue
    return None


# ---------------------------------------------------------------------------------------------------------------
# the story, pure: plain records in, a JSON-ready dict out
def build(request: dict, *, jobs=(), chat=None, chat_model=None, runs=(), audits=(), workspace=None,
          diff=None, prices=None, now=None) -> dict:
    now = time.time() if now is None else now
    prices = {**DEFAULT_PRICES, **(prices or {})}
    x = request or {}
    rid = x.get("id")
    metrics = x.get("metrics") if isinstance(x.get("metrics"), dict) else {}
    detail = metrics.get("tokens_detail") if isinstance(metrics.get("tokens_detail"), dict) else {}
    messages = sorted((m for m in x.get("messages") or [] if isinstance(m, dict)), key=lambda m: _num(m.get("ts")) or 0)
    missing: list[str] = []
    workspace = workspace if isinstance(workspace, dict) else None

    # --- identification: every tool call in order --------------------------------------------------------------
    steps = []
    events = (chat or {}).get("events") or []
    for e in events:
        if e.get("type") == "tool_call":
            steps.append({"source": "gBox resolution agent", "run_id": (chat or {}).get("id"), "action": e.get("name") or "tool",
                          "input": summarise(e.get("args")), "result": "", "status": "running", "ts": _num(e.get("ts")),
                          "duration_s": None})
        elif e.get("type") in ("tool_result", "error"):
            for s in reversed(steps):
                if s["status"] == "running" and s["source"] == "gBox resolution agent" and \
                        (s["action"] == e.get("name") or e.get("type") == "error"):
                    s.update(result=summarise(e.get("text"), 220), status="failed" if e.get("type") == "error" else "finished",
                             duration_s=_dur(s["ts"], e.get("ts")))
                    break
    for run in runs:
        for s in run.get("steps") or []:
            steps.append({"source": f"Hermes run {run.get('name') or run.get('id') or ''}".strip(), "run_id": run.get("id"),
                          "action": str(s.get("action") or "tool").replace("mcp__gbox__", ""), "input": summarise(s.get("input")),
                          "result": summarise(s.get("result"), 220), "status": s.get("status") or "", "ts": None,
                          "at": _num(run.get("started")), "duration_s": None})
    for m in messages:
        ts_ = m.get("task_step")
        if isinstance(ts_, dict) and m.get("author") in ("agent", "system"):
            steps.append({"source": "ticket", "run_id": None, "action": ts_.get("action") or "update",
                          "input": "", "result": summarise(ts_.get("result") or m.get("text"), 220),
                          "status": ts_.get("status") or "", "ts": _num(m.get("ts")), "duration_s": None})
    for i, s in enumerate(steps):
        s["seq"] = i
    steps.sort(key=lambda s: (s["ts"] if s["ts"] is not None else (s.get("at") if s.get("at") is not None else float("inf")), s["seq"]))
    steps_total = len(steps)
    steps = steps[:MAX_STEPS]
    for s in steps:
        s.pop("seq", None)
        s.pop("at", None)
    if not steps_total:
        missing.append("No tool calls or task steps were recorded for this request.")

    # --- triage: who took it first ----------------------------------------------------------------------------
    candidates = []
    for run in runs:
        if _num(run.get("started")) is not None:
            candidates.append({"at": run["started"], "by": "Hermes", "agent": "/".join(v for v in (run.get("provider"), run.get("model")) if v) or None,
                               "tool": run.get("name") or "Hermes run", "run_id": run.get("id"), "evidence": "Hermes run that worked this ticket"})
    if chat and chat.get("id"):
        first = next((e.get("ts") for e in events if _num(e.get("ts")) is not None), None)
        candidates.append({"at": _num(chat.get("created")) or first, "by": "gBox resolution agent",
                           "agent": chat_model or chat.get("model"), "tool": f"chat {chat['id']}", "run_id": chat["id"],
                           "evidence": "resolution chat linked to the ticket"})
    for m in messages:
        ts_ = m.get("task_step")
        if isinstance(ts_, dict) and m.get("author") in ("agent", "system") and CLAIM_WORDS.search(ts_.get("action") or ""):
            candidates.append({"at": _num(m.get("ts")), "by": m.get("author"), "agent": None, "tool": ts_.get("action"),
                               "run_id": None, "evidence": "task step on the ticket: " + summarise(ts_.get("result"), 80)})
            break
    for a in audits:
        if a.get("action") == "request.in_progress":
            candidates.append({"at": _num(a.get("ts")), "by": a.get("actor"), "agent": None, "tool": "set_request_status in_progress",
                               "run_id": None, "evidence": "audit log"})
            break
    if not candidates and _num(x.get("started")) is not None:
        candidates.append({"at": x["started"], "by": None, "agent": None, "tool": None, "run_id": None,
                           "evidence": "the ticket's start time (who started it was not recorded)"})
    candidates = [c for c in candidates if _num(c.get("at")) is not None] or candidates
    triage = min(candidates, key=lambda c: _num(c.get("at")) if _num(c.get("at")) is not None else float("inf")) if candidates else None
    if triage:
        triage = dict(triage, wait_s=_dur(x.get("created"), triage.get("at")), candidates=len(candidates))
    else:
        missing.append("Nobody has claimed this request yet (no run, agent, dispatch step or status change recorded).")

    # --- work: runs and their usage ---------------------------------------------------------------------------
    by_run: dict[str, list[dict]] = {}
    for key, value in detail.items():
        m = MARKER.match(str(key))
        if m and isinstance(value, dict):
            by_run.setdefault(m[1], []).append(value)
    run_rows = {r.get("id"): r for r in runs if r.get("id")}
    work = []
    hermes_tokens: dict[tuple, list[int]] = {}
    for run_id in list(dict.fromkeys([*by_run, *run_rows])):
        row, records = run_rows.get(run_id) or {}, by_run.get(run_id) or []
        entry = {"id": run_id, "kind": "hermes", "name": row.get("name") or "Hermes run", "state": row.get("state"),
                 "started": _num(row.get("started")), "finished": _num(row.get("finished")), "models": [],
                 "tokens_in": None, "tokens_out": None, "api_calls": None, "cost": None, "usage_source": None,
                 "shared_with": max(0, len(row.get("request_ids") or []) - 1) or None, "steps": len(row.get("steps") or [])}
        if records:
            costs = []
            for r in records:
                tin, tout = _num(r.get("tokens_in_including_caches")), _num(r.get("tokens_out"))
                c = cost_of(prices, r.get("provider"), r.get("model"), tin, tout, cache_read=r.get("input_cache_read"),
                            actual=r.get("actual_cost_usd"), estimated=r.get("estimated_cost_usd"))
                costs.append(c)
                entry["models"].append({"provider": r.get("provider"), "model": r.get("model"), "task": r.get("task"),
                                        "tokens_in": tin, "tokens_out": tout, "api_calls": _num(r.get("api_call_count")),
                                        "cache_read": _num(r.get("input_cache_read")), "cost": c})
                acc = hermes_tokens.setdefault((r.get("provider"), r.get("model")), [0, 0])
                acc[0] += tin or 0
                acc[1] += tout or 0
            entry["tokens_in"] = sum(mm["tokens_in"] or 0 for mm in entry["models"])
            entry["tokens_out"] = sum(mm["tokens_out"] or 0 for mm in entry["models"])
            entry["api_calls"] = sum(mm["api_calls"] or 0 for mm in entry["models"])
            durations = [_num(r.get("inference_session_duration_s")) for r in records if _num(r.get("inference_session_duration_s")) is not None]
            entry["duration_s"] = max(durations) if durations else _dur(entry["started"], entry["finished"])
            entry["usage_source"] = "Hermes final model ledger (exact, attributed to this ticket)"
            entry["cost"] = _sum_costs(costs)
            entry["provider"], entry["model"] = entry["models"][0]["provider"], entry["models"][0]["model"]
        else:
            tin, tout = _num(row.get("tokens_in")), _num(row.get("tokens_out"))
            entry.update(provider=row.get("provider"), model=row.get("model"), tokens_in=tin, tokens_out=tout,
                         duration_s=_dur(entry["started"], entry["finished"]))
            d = row.get("tokens_detail") or {}
            entry["cost"] = cost_of(prices, row.get("provider"), row.get("model"), tin, tout, cache_read=d.get("cache_read_tokens"),
                                    actual=d.get("actual_cost_usd") if d.get("cost_status") == "actual" else None,
                                    estimated=d.get("estimated_cost_usd"))
            if tin is not None:
                entry["usage_source"] = "Hermes session counters" + (" (the session also worked other tickets)" if entry["shared_with"] else "")
            else:
                missing.append(f"Hermes run {run_id[:8]} has no recorded usage.")
        work.append(entry)

    solvers = [u for u in metrics.get("usage_by_solver") or [] if isinstance(u, dict)]
    attributed_in = attributed_out = 0
    for u in solvers:
        tin, tout = _num(u.get("tokens_in")) or 0, _num(u.get("tokens_out")) or 0
        attributed_in, attributed_out = attributed_in + tin, attributed_out + tout
        if (u.get("system") or "").lower() == "hermes":
            seen_in, seen_out = hermes_tokens.get((u.get("provider"), u.get("model")), [0, 0])
            tin, tout = max(0, tin - seen_in), max(0, tout - seen_out)
            if not (tin or tout):
                continue
            name = "Hermes usage not tied to a run"
        else:
            name = f"{u.get('system') or 'Agent'} usage"
        work.append({"id": None, "kind": "agent", "name": name, "state": None, "started": None, "finished": None,
                     "provider": u.get("provider"), "model": u.get("model"), "models": [], "tokens_in": tin, "tokens_out": tout,
                     "api_calls": None, "duration_s": _num(u.get("agent_seconds")) if u.get("timed") else None,
                     "cost": cost_of(prices, u.get("provider"), u.get("model"), tin, tout),
                     "usage_source": "request metrics (usage_by_solver)", "shared_with": None, "steps": 0})
    total_in, total_out = _num(metrics.get("tokens_in")), _num(metrics.get("tokens_out"))
    rest_in, rest_out = max(0, (total_in or 0) - attributed_in), max(0, (total_out or 0) - attributed_out)
    if chat and chat.get("id"):
        first = next((_num(e.get("ts")) for e in events if _num(e.get("ts")) is not None), None)
        last = next((_num(e.get("ts")) for e in reversed(events) if _num(e.get("ts")) is not None), None)
        work.append({"id": chat["id"], "kind": "local_agent", "name": "gBox resolution agent", "state": "running" if chat.get("busy") else "ended",
                     "started": first, "finished": last, "provider": "local", "model": chat_model or chat.get("model"),
                     "models": [], "tokens_in": rest_in if (rest_in or rest_out) else None, "tokens_out": rest_out if (rest_in or rest_out) else None,
                     "api_calls": None, "duration_s": _dur(first, last),
                     "cost": cost_of(prices, "local", None, rest_in, rest_out) if (rest_in or rest_out) else
                             {"usd": None, "kind": "unknown", "basis": "the agent recorded no tokens"},
                     "usage_source": "request metrics not attributed to another solver" if (rest_in or rest_out) else None,
                     "shared_with": None, "steps": sum(1 for e in events if e.get("type") == "tool_call")})
    elif rest_in or rest_out:
        work.append({"id": None, "kind": "unattributed", "name": "Usage recorded without a provider", "state": None,
                     "started": None, "finished": None, "provider": None, "model": None, "models": [],
                     "tokens_in": rest_in, "tokens_out": rest_out, "api_calls": None, "duration_s": None,
                     "cost": {"usd": None, "kind": "unknown", "basis": "the provider was not recorded"},
                     "usage_source": "request metrics", "shared_with": None, "steps": 0})
    if not work:
        missing.append("No agent run or token usage was recorded for this request.")

    job_rows = []
    for j in sorted(jobs, key=lambda j: _num(j.get("created")) or 0)[:100]:
        job_rows.append({"id": j.get("id"), "tool": j.get("tool"), "state": j.get("state"), "created": _num(j.get("created")),
                         "started": _num(j.get("started")), "finished": _num(j.get("finished")),
                         "duration_s": _dur(j.get("started"), j.get("finished")), "worker": j.get("worker_id"),
                         "input": summarise(j.get("input"), 120), "error": summarise(j.get("error"), 160) or None})

    # --- code changes ------------------------------------------------------------------------------------------
    pulls: dict[int, dict] = {}

    def pull(n, **kw):
        p = pulls.setdefault(int(n), {"number": int(n), "url": None, "state": "unknown", "merged_sha": None, "merged_at": None,
                                      "base": None, "branch": None, "published_at": None, "files": [], "folders": [],
                                      "added": None, "deleted": None, "source": None, "range": None})
        for k, v in kw.items():
            if v is not None and (p.get(k) in (None, "unknown") or k in ("state", "merged_sha", "merged_at")):
                p[k] = v
        return p

    branch_heads = []
    for m in messages:
        text, ts = m.get("text") or "", _num(m.get("ts"))
        for url, n in PUBLISHED.findall(text):
            p = pull(n, url=url, published_at=ts)
            if p["state"] == "unknown":
                p["state"] = "open"
        for n, base, sha, at in MERGED.findall(text):
            pull(n, state="merged", merged_sha=sha, base=base, merged_at=_stamp(at) or ts)
        for n, at in CLOSED.findall(text):
            if pulls.get(int(n), {}).get("state") != "merged":
                pull(n, state="closed")
        for n in RECOVERY.findall(text):
            pull(n, state="open", published_at=ts)
        if m.get("author") in ("agent", "system"):
            for n in PULL_URL.findall(text):
                pull(n)
        for branch, sha in ON_MAIN.findall(text):
            branch_heads.append({"branch": branch, "head": sha, "at": ts})
    if workspace and workspace.get("pr_number") is not None:
        pull(workspace["pr_number"], url=workspace.get("url"), branch=workspace.get("branch"),
             published_at=_num(workspace.get("published_at")))
    changes = []
    for n in sorted(pulls):
        p = pulls[n]
        spec = None
        if p["merged_sha"]:
            spec = {"commit": p["merged_sha"]}
        elif workspace and workspace.get("pr_number") == n and workspace.get("baseline") and workspace.get("commit"):
            spec = {"base": workspace["baseline"], "head": workspace["commit"]}
        found = diff(spec) if (diff and spec) else None
        if found and found.get("files") is not None:
            p.update(files=found["files"][:MAX_FILES], source=found.get("source") or "local git", range=found.get("range"))
        elif workspace and workspace.get("pr_number") == n and workspace.get("files"):
            p.update(files=[{"path": f, "folder": folder_of(f), "added": None, "deleted": None, "binary": False, "hunks": [],
                             "hunks_total": None} for f in workspace["files"][:MAX_FILES]],
                     source="Hermes publication record (file list only; no line counts)")
        else:
            missing.append(f"PR #{n}: files and line counts unavailable (no local commit"
                           + (f" {p['merged_sha']}" if p["merged_sha"] else "") + " and no cached file list).")
        changes.append(p)
    if not changes and workspace and workspace.get("baseline") and workspace.get("commit"):
        found = diff({"base": workspace["baseline"], "head": workspace["commit"]}) if diff else None
        files = (found or {}).get("files")
        changes.append({"number": None, "url": None, "state": "unpublished", "merged_sha": None, "merged_at": None, "base": None,
                        "branch": workspace.get("branch"), "published_at": None, "range": (found or {}).get("range"),
                        "files": files[:MAX_FILES] if files is not None else [
                            {"path": f, "folder": folder_of(f), "added": None, "deleted": None, "binary": False, "hunks": [], "hunks_total": None}
                            for f in workspace.get("files") or []],
                        "source": "local git" if files is not None else "Hermes workspace record", "folders": [], "added": None, "deleted": None})
    if not changes and metrics.get("files_changed"):
        changes.append({"number": None, "url": None, "state": "reported", "merged_sha": None, "merged_at": None, "base": None,
                        "branch": None, "published_at": None, "range": None,
                        "files": [{"path": f, "folder": folder_of(f), "added": None, "deleted": None, "binary": False, "hunks": [],
                                   "hunks_total": None} for f in metrics["files_changed"][:MAX_FILES]],
                        "source": "agent metrics (file list only; no line counts)", "folders": [], "added": None, "deleted": None})
    for c in changes:
        c["folders"] = group_folders(c["files"])
        known = [f for f in c["files"] if f.get("added") is not None]
        if c["files"] and len(known) == len(c["files"]):
            c["added"], c["deleted"] = sum(f["added"] for f in known), sum(f["deleted"] for f in known)
        if c["state"] == "merged" and branch_heads and not c["branch"]:
            c["branch"] = branch_heads[-1]["branch"]
    if not changes:
        missing.append("No code change (PR, branch or changed files) is linked to this request.")

    # --- replies and resolution -------------------------------------------------------------------------------
    replies = [{"author": m.get("author"), "ts": _num(m.get("ts")), "text": summarise(m.get("text"), 600),
                "action": (m.get("task_step") or {}).get("action") if isinstance(m.get("task_step"), dict) else None,
                "attachments": len(m.get("attachments") or [])} for m in messages[1:] if m.get("text") or m.get("attachments")]
    final = next((m for m in reversed(messages) if m.get("author") == "agent" and m.get("text")), None)
    resolution = {"status": x.get("status"), "completed": _num(x.get("completed")), "solved_by": x.get("solved_by"),
                  "verified": bool(x.get("solved_by")), "final_message": summarise(final.get("text"), 600) if final else None,
                  "final_at": _num(final.get("ts")) if final else None}
    if x.get("status") != "done":
        missing.append("The request is not resolved yet.")

    # --- stages and totals --------------------------------------------------------------------------------------
    created = _num(x.get("created"))
    triage_at = _num((triage or {}).get("at"))
    stamped = [s["ts"] for s in steps if s.get("ts") is not None]
    work_costs = [w["cost"] for w in work if w.get("cost")]
    stages = [{"key": "intake", "label": "Request filed", "start": created, "end": triage_at,
               "duration_s": _dur(created, triage_at), "tokens_in": None, "tokens_out": None, "cost": None,
               "detail": f"#{x.get('number')} from {x.get('source') or 'unknown source'}"},
              {"key": "triage", "label": "Triage", "start": triage_at, "end": triage_at, "duration_s": None,
               "tokens_in": None, "tokens_out": None, "cost": None,
               "detail": ("claimed by " + " \u00b7 ".join(v for v in ((triage or {}).get("by"), (triage or {}).get("agent"), (triage or {}).get("tool")) if v))
                         if triage else "not claimed yet"},
              {"key": "identify", "label": "Identification", "start": min(stamped) if stamped else None,
               "end": max(stamped) if stamped else None, "duration_s": _dur(min(stamped), max(stamped)) if stamped else None,
               "tokens_in": None, "tokens_out": None, "cost": None, "detail": f"{steps_total} tool call{'s' if steps_total != 1 else ''} and steps"}]
    for w in work:
        stages.append({"key": "work", "label": f"{w['name']}" + (f" \u00b7 {w['model']}" if w.get("model") else ""), "run_id": w.get("id"),
                       "start": w.get("started"), "end": w.get("finished"), "duration_s": w.get("duration_s"),
                       "tokens_in": w.get("tokens_in"), "tokens_out": w.get("tokens_out"), "cost": w.get("cost"),
                       "detail": w.get("usage_source") or "usage not recorded"})
    for c in changes:
        stages.append({"key": "changes", "label": (f"PR #{c['number']}" if c["number"] else "Code changes") + f" \u00b7 {c['state']}",
                       "pr": c["number"], "start": c.get("published_at"), "end": c.get("merged_at"),
                       "duration_s": _dur(c.get("published_at"), c.get("merged_at")), "tokens_in": None, "tokens_out": None,
                       "cost": None, "files": len(c["files"]), "folders": len(c["folders"]), "added": c["added"], "deleted": c["deleted"],
                       "detail": c["source"] or "files unavailable"})
    completed = _num(x.get("completed")) if x.get("status") == "done" else None
    stages.append({"key": "resolution", "label": "Resolved" if completed else f"Status: {str(x.get('status') or 'unknown').replace('_', ' ')}",
                   "start": completed, "end": completed, "duration_s": _dur(created, completed), "tokens_in": None, "tokens_out": None,
                   "cost": None, "detail": (resolution["final_message"] or "")[:160]})
    duration = _num(metrics.get("duration_s"))
    elapsed = False
    if duration is None:
        duration = _dur(created, completed)
    if duration is None and created is not None and x.get("status") != "done":
        duration, elapsed = round(max(0.0, now - created), 1), True
    totals = {"tokens_in": total_in, "tokens_out": total_out, "cost": _sum_costs(work_costs), "duration_s": duration,
              "elapsed": elapsed, "agent_seconds": _num(metrics.get("agent_seconds")), "tool_calls": steps_total,
              "jobs": len(job_rows), "files": sum(len(c["files"]) for c in changes),
              "added": _sum_known([c["added"] for c in changes]), "deleted": _sum_known([c["deleted"] for c in changes])}
    if total_in is None or total_out is None:
        missing.append("Token totals were not recorded on the request.")

    return {"request": {k: x.get(k) for k in ("id", "number", "title", "status", "source", "kind", "created", "started",
                                              "completed", "author", "parent_request_id")},
            "triage": triage, "identification": steps, "identification_total": steps_total, "runs": work, "jobs": job_rows,
            "changes": changes, "replies": replies, "resolution": resolution, "stages": stages, "totals": totals,
            "missing": missing, "prices": {"note": PRICE_NOTE, "table": prices}, "generated": now, "id": rid}


def _sum_known(values):
    vals = [v for v in values if v is not None]
    return sum(vals) if vals and len(vals) == len(values) else None


def _sum_costs(costs: list[dict]):
    """One cost from several: actual only if all actual; usd None if any part is unknown (partial sum kept apart)."""
    if not costs:
        return {"usd": None, "kind": "unknown", "basis": "no usage recorded", "partial_usd": None}
    known = [c for c in costs if _num(c.get("usd")) is not None]
    partial = round(sum(c["usd"] for c in known), 6) if known else None
    if len(known) != len(costs):
        return {"usd": None, "kind": "unknown", "partial_usd": partial,
                "basis": f"{len(costs) - len(known)} of {len(costs)} usage records have no price"}
    kind = "actual" if all(c["kind"] == "actual" for c in costs) else "estimate"
    return {"usd": partial, "kind": kind, "partial_usd": partial,
            "basis": "sum of " + ", ".join(sorted({c["basis"] for c in costs}))[:300]}


# ---------------------------------------------------------------------------------------------------------------
# gathering, impure: each source is optional and a failure only adds to `missing`
def hermes_runs_for(rid: str, limit: int = 100, detail: int = 6) -> list[dict]:
    """Hermes runs that confirmed work on the ticket (when this machine can read Hermes's databases), with steps."""
    from . import hermes_tasks
    rows = [r for r in hermes_tasks.list_runs(limit) if rid in (r.get("request_ids") or [])]
    out = []
    for r in sorted(rows, key=lambda r: r.get("started") or 0)[-detail:]:
        full = hermes_tasks.get_run(r["id"]) or {}
        out.append({**r, "steps": full.get("steps") or []})
    return out


def workspace_for(rid: str):
    """The Hermes publication record for the ticket (branch, baseline, commit, files, PR), if this machine has it."""
    from . import hermes_delivery
    if not re.fullmatch(r"[0-9a-f]{16}", rid or ""):
        return None
    path = hermes_delivery.state_dir() / (rid + ".json")
    return json.loads(path.read_text()) if path.is_file() else None


def assemble(store, config, request: dict, *, runs=None, workspace=None, diff=None) -> dict:
    rid = request["id"]
    runs, workspace, diff = runs or hermes_runs_for, workspace or workspace_for, diff or local_diff
    problems = []

    def attempt(what, fn, default):
        try:
            return fn()
        except Exception as error:  # an unreachable source never breaks the story
            problems.append(f"{what} unavailable ({type(error).__name__}).")
            return default

    ctx = request.get("context") or {}
    chat = attempt("Resolution chat", lambda: store.get("chat", ctx["resolution_chat_id"]) if ctx.get("resolution_chat_id") else None, None)
    jobs = attempt("Jobs", lambda: store.request_jobs(rid), [])
    audits = attempt("Audit log", lambda: store.audit_for(rid), [])
    hermes = attempt("Hermes runs", lambda: runs(rid), [])
    record = attempt("Hermes publication record", lambda: workspace(rid), None)
    prices = getattr(config, "token_prices", None) or {}
    chat_model = (chat or {}).get("model") or (getattr(config, "agent", None) or {}).get("model")
    cache: dict[str, object] = {}

    def cached_diff(spec):
        key = json.dumps(spec, sort_keys=True)
        if key not in cache:
            cache[key] = attempt("Local git", lambda: diff(spec), None)
        return cache[key]

    story = build(request, jobs=jobs, chat=chat, chat_model=chat_model, runs=hermes, audits=audits, workspace=record,
                  diff=cached_diff, prices=prices)
    story["missing"].extend(problems)
    return story
