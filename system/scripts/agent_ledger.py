"""gBox request ledger + inbox CLI for the coding agent (Claude Code).

Hooks (configured in .claude/settings.json):
  prompt   UserPromptSubmit: logs every chat request to the gBox inbox, and prints new operator reports
           (screenshots / eyedropper picks, with local image paths) so the agent sees them in context.
  stop     Stop: reads this session's transcript and adds the turn's real usage to the active request:
           tokens in/out (incl. cache), tools used, files changed, agent time.
CLI (for the agent):
  list [status] [--group]  open reports first; --group: one line per kind of automated ticket
  show ID                full report; downloads the sketched screenshot and prints its path
  claim ID               mark in_progress; this turn's metrics are attributed to it
  reply ID "text"        message in the request thread (shown in the app)
  done ID ["note"]       complete it (duration recorded)
Never blocks the agent: every failure is swallowed (hooks also run as `... || true`).
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

SERVER = os.environ.get("GBOX_SERVER", "http://10.89.1.246:8765")
CANONICAL = Path("//10.89.1.246/ehm_eckx/gBox/system")                 # the Spark share is the source of truth
REPO = CANONICAL if CANONICAL.exists() else Path(__file__).resolve().parent.parent
HOME = Path.home() / ".gbox"
STATE = HOME / "ledger_state.json"
INBOX = HOME / "inbox"
SKIP_DIRS = {"gbox-data", "node_modules", "__pycache__", ".pytest_cache", ".git", "gbox.egg-info"}

# This exact scheduled harness instruction is a review trigger, not a new
# operator request. Keep other review prompts and actual review findings in the
# ledger. Unknown/changed templates deliberately retain the ordinary behavior.
_RECURRING_REVIEW = (
    'gBox request review (recurring, set up at the operator\'s request: "examine the requests I give gBox and how it responds; make sure it has the means to accomplish them").',
    '1. Run: cd //10.89.1.246/ehm_eckx/gBox/system && python scripts/chat_review.py --hours 0.25 --full  (only requests from the last 15 minutes).',
    '2. If there are no new requests, stop quietly with a one-line note.',
    '3. For each new request: judge whether gBox\'s agent understood the goal, used the right tools, verified, and answered. For every failure, find the root cause (missing tool/capability, bad tool output, prompt rule gap, crash, wrong model behaviour) and fix it in the canonical code on the share (never C:\\_tools\\gBox directly; write patch scripts with the Write tool; validate with ast.parse / jscheck.py). Prefer making the tool capable over adding prompt text. If a fix needs gbox.service restarted, only restart when no chat is busy and no agent/test session needs the Spark (check /api/chat busy flags and running sessions); Windows-worker code changes need the scratchpad sync.ps1 and a worker restart (kill the `-m gbox ... worker` python; the gBox.exe watchdog respawns it) only when the operator isn\'t mid-request.',
    '4. If gBox gave the operator a wrong or empty result, and the fix is in place, you may re-run the operator\'s request on their live session ONLY when it\'s harmless and clearly what they asked for; otherwise just report.',
    '5. Report briefly: requests seen, what failed, what you fixed.',
)


def recurring_review_prompt(prompt: str) -> bool:
    """Recognize only the observed scheduled instruction, never its findings."""
    return tuple(prompt.strip().splitlines()) == _RECURRING_REVIEW


def token() -> str:
    if t := os.environ.get("GBOX_TOKEN"):
        return t
    for p in (REPO / "gbox-data" / "api_token", CANONICAL / "gbox-data" / "api_token"):
        try:
            return p.read_text().strip()
        except OSError:
            pass
    return ""


def api(path, body=None, raw=False, timeout=5):
    req = urllib.request.Request(SERVER + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + token(), "Content-Type": "application/json",
                                          "X-GBox-Actor": "agent"}, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return data if raw else json.loads(data)


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(s: dict):
    HOME.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=1))


def fetch_image(r: dict) -> str | None:
    if not r.get("image"):
        return None
    INBOX.mkdir(parents=True, exist_ok=True)
    p = INBOX / f"request-{r['number']}-{r['id']}.png"
    if not p.exists():
        p.write_bytes(api(f"/api/artifacts/{r['image']}", raw=True, timeout=15))
    return str(p)


COACH_SOURCE = "coach"
COACH_FIRST_RUN_S = 3600              # the first hook run shows notes this new (older ones count as seen)
COACH_SHOW = 12                       # at most this many notes per hook run (the rest: `show ID`)


def is_coaching(r: dict) -> bool:
    """An autoplay coaching ticket (gbox/coaching.py): one per game, each operator message on it a note the operator
    typed while a bot played, with the moment captured (frame, save state, RAM)."""
    return r.get("source") == COACH_SOURCE or (r.get("context") or {}).get("coaching") is True


def operator_messages(r: dict) -> list:
    return [m for m in r.get("messages") or [] if m.get("author") == "operator"]


def note_key(r: dict, m: dict) -> str:
    return m.get("id") or f"{r['id']}:{m.get('ts')}"


def activity(r: dict) -> float:
    """When the operator last wrote on it (a new coaching note counts), else when it was filed: `list` puts a ticket
    with a fresh operator message first, not where its first message left it."""
    return max([r.get("created") or 0] + [m.get("ts") or 0 for m in operator_messages(r)])


def coaching_fresh(rows: list, seen: set) -> list:
    """[(ticket, message)] coaching notes not seen yet, oldest first."""
    out = [(r, m) for r in rows if is_coaching(r) for m in operator_messages(r) if note_key(r, m) not in seen]
    return sorted(out, key=lambda rm: rm[1].get("ts") or 0)


def describe_note(r: dict, m: dict, now: float | None = None) -> str:
    """One coaching note for the agent: the ticket, the note number, how long ago, the operator's words (with the
    session / PC / autoplay line coaching.compose added) and what of the moment was captured."""
    now = time.time() if now is None else now
    c = m.get("coach") or {}
    age = max(0, int(now - (m.get("ts") or now)))
    when = f"{age // 60} min ago" if age >= 60 else f"{age} s ago"
    caps = " ".join(f"{k} {(v or {}).get('state', '?')}" for k, v in (c.get("captures") or {}).items())
    lines = [f"#{r.get('number')} {r.get('title')} (id {r['id']}) · note #{c.get('note', '?')} · {when}"
             + (f" · {c.get('worker')} session {c.get('session_id')}" if c.get("session_id") else ""),
             f"  operator: {(m.get('text') or '').strip()[:700]}"]
    if caps:
        lines.append(f"  captured: {caps}  (scripts/agent_ledger.py show {r['id']} downloads them)")
    return "\n".join(lines)


def describe(r: dict, full=False) -> str:
    m = r["metrics"]
    lines = [f"#{r['number']} [{r['status']}] {r['title']}  (id {r['id']}, {r['kind']}, from {r['source']})"]
    if r.get("element"):
        e = r["element"]
        lines.append(f"  element: {e.get('selector')}  <{e.get('tag')}> \"{(e.get('text') or '')[:80]}\"  view={e.get('view')}")
    if (img := fetch_image(r)):
        lines.append(f"  screenshot: {img}")
    if full:
        for msg in r["messages"]:
            lines.append(f"  {msg['author']}: {msg['text']}")
            for a in msg.get("attachments") or []:
                INBOX.mkdir(parents=True, exist_ok=True)
                p = INBOX / f"request-{r['number']}-{a['sha256'][:10]}-{a['name']}"
                if not p.exists():
                    p.write_bytes(api(f"/api/artifacts/{a['sha256']}", raw=True, timeout=30))
                lines.append(f"    attachment: {p}")
        lines.append(f"  context: {json.dumps(r.get('context', {}))[:400]}")
        lines.append(f"  metrics: {json.dumps(m)}")
    elif r["messages"]:
        ops = operator_messages(r) if is_coaching(r) else []
        last = ops[-1] if ops else r["messages"][-1]          # a coaching ticket: its newest note, not a reply
        n = sum(len(m.get("attachments") or []) for m in r["messages"])
        lines.append(f"  {last['author']}: {last['text'][:300]}" + (f"  [{n} attached image(s): use show]" if n else ""))
    return "\n".join(lines)


# --- hooks ------------------------------------------------------------------------------------

def hook_prompt(ev: dict):
    st = load_state()
    sess = st.setdefault(ev.get("session_id", "default"), {})
    prompt = (ev.get("prompt") or "").strip()
    if recurring_review_prompt(prompt):
        # Do not leave the previous operator request or its explicit claims as
        # this automation turn's usage target. A real issue can still be claimed
        # explicitly during the review and measured from this fresh window.
        sess.update(chat_request=None, since=time.time(), claimed=[])
        prompt = ""
    if prompt.startswith(("<task-notification>", "<system-reminder>")):   # harness events, not operator requests
        prompt = ""
    if prompt:
        sys.path.insert(0, str(REPO))
        from gbox.inbox import automated
        is_system = automated({"body": prompt})
        parent = sess.get("operator_request") if is_system else None
        title = prompt.splitlines()[0][:100]
        r = api("/api/requests", {"title": title, "body": prompt, "source": "chat", "kind": "text",
                                  "automated": is_system, "parent_request_id": parent,
                                  "context": {"cwd": ev.get("cwd"), "session": ev.get("session_id")}})
        api(f"/api/requests/{r['id']}/status", {"status": "in_progress"})
        sess.update(chat_request=r["id"], since=time.time(), claimed=[])
        if not is_system:
            sess["operator_request"] = r["id"]
    # surface operator reports filed in the app (screenshots / eyedropper) that the agent hasn't seen yet
    seen = set(st.get("seen", []))
    fresh = [r for src in ("app", "gap") for r in api(f"/api/requests?status=open,in_progress&source={src}") if r["id"] not in seen]
    if fresh:
        print("gBox inbox: new operator reports (handle them with scripts/agent_ledger.py show/claim/reply/done):")
        for r in reversed(fresh):
            print(describe(r))
            seen.add(r["id"])
    st["seen"] = sorted(seen)
    try:
        hook_coaching(st, api(f"/api/requests?status=open,in_progress,blocked&source={COACH_SOURCE}"))
    except Exception as e:                             # a coaching read never stops the other reports
        print(f"(coaching notes unavailable: {e})", file=sys.stderr)
    save_state(st)


def hook_coaching(st: dict, rows: list, now: float | None = None, out=print) -> list:
    """Live coaching (operator 2026-10-20: "chat about the gameplay placing reports for improvements ... in realtime via
    live reporting"): every note the operator typed in the Sessions header's coach box while a bot played is a new
    operator message on that game's coaching ticket. Each one this agent has not seen is printed once, oldest first.
    The first run marks notes older than COACH_FIRST_RUN_S as seen. Returns the notes printed."""
    now = time.time() if now is None else now
    first = "seen_notes" not in st
    seen = set(st.get("seen_notes") or [])
    new = coaching_fresh(rows, seen)
    if first:
        seen.update(note_key(r, m) for r, m in new if now - (m.get("ts") or 0) > COACH_FIRST_RUN_S)
        new = [(r, m) for r, m in new if note_key(r, m) not in seen]
    shown = new[-COACH_SHOW:]
    if shown:
        out("gBox inbox: new coaching notes from the operator, typed while autoplay played (answer with "
            "scripts/agent_ledger.py reply ID \"...\"; the moment's frame / save state / RAM: show ID):")
        if len(new) > len(shown):
            out(f"  ({len(new) - len(shown)} older new notes not shown: scripts/agent_ledger.py show ID)")
        for r, m in shown:
            out(describe_note(r, m, now))
    seen.update(note_key(r, m) for r, m in new)
    keep = {note_key(r, m) for r in rows if is_coaching(r) for m in operator_messages(r)}
    st["seen_notes"] = sorted(seen & keep) if keep else sorted(seen)[-500:]
    return shown


def _ts(s: str) -> float:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return 0.0


def turn_usage(transcript: str, since: float) -> dict:
    """Sum usage of assistant messages after `since` (deduped by message id: a message spans several lines)."""
    seen, tin, tout, detail, tools, files = set(), 0, 0, {"input": 0, "cache_read": 0, "cache_write": 0}, {}, set()
    with open(transcript, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("type") != "assistant" or _ts(e.get("timestamp", "")) < since:
                continue
            msg = e.get("message") or {}
            for c in msg.get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    tools[c.get("name", "?")] = tools.get(c.get("name", "?"), 0) + 1
                    fp = (c.get("input") or {}).get("file_path")
                    if fp and c.get("name") in ("Edit", "Write", "NotebookEdit"):
                        files.add(fp)
            mid = msg.get("id")
            if mid in seen or not msg.get("usage"):
                continue
            seen.add(mid)
            u = msg["usage"]
            detail["input"] += u.get("input_tokens", 0)
            detail["cache_read"] += u.get("cache_read_input_tokens", 0)
            detail["cache_write"] += u.get("cache_creation_input_tokens", 0)
            tout += u.get("output_tokens", 0)
    tin = sum(detail.values())
    return {"tokens_in": tin, "tokens_out": tout, "tokens_detail": detail, "tools": tools, "files": files}


def changed_files(since: float) -> set[str]:
    """Repo files modified since the turn began (catches edits made through shell/python too)."""
    out = set()
    for root, dirs, names in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".venv")]
        for n in names:
            p = Path(root, n)
            try:
                if p.stat().st_mtime >= since:
                    out.add(p.relative_to(REPO).as_posix())
            except OSError:
                pass
    return out


def hook_stop(ev: dict):
    st = load_state()
    sess = st.get(ev.get("session_id", "default")) or {}
    since = sess.get("since")
    if not since or not ev.get("transcript_path"):
        return
    targets = sess.get("claimed") or [sess.get("chat_request")]
    targets = [t for t in targets if t]
    if not targets:
        return                                      # no request was worked on in this automation turn
    u = turn_usage(ev["transcript_path"], since)
    files = changed_files(since)                       # repo files only (scratch/tool files outside the repo don't count)
    for f in u["files"]:
        try:
            files.add(Path(f).resolve().relative_to(REPO.resolve()).as_posix())
        except (ValueError, OSError):
            pass
    for i, rid in enumerate(targets):                  # split the turn across the requests worked on
        share = 1 / len(targets)
        api(f"/api/requests/{rid}/metrics", {"tokens_in": int(u["tokens_in"] * share), "tokens_out": int(u["tokens_out"] * share),
                                             "tokens_detail": {k: int(v * share) for k, v in u["tokens_detail"].items()},
                                             "tools": u["tools"] if i == 0 else {}, "files_changed": sorted(files),
                                             "duration_s": round(time.time() - since, 1)})
    # A stopped agent turn may have left work unfinished. Completion is recorded
    # by the explicit `done` command, not inferred from the hook firing.
    sess["since"] = time.time()                        # mid-turn messages continue the same ledger window
    save_state(st)


# --- CLI --------------------------------------------------------------------------------------

def group_line(g: dict) -> str:
    """One line for a group of automated tickets (#1788): kind, count, pending, newest ticket and the ticket numbers."""
    latest = g["latest"]
    when = datetime.fromtimestamp(g["newest"]).strftime("%Y-%m-%d %H:%M") if g.get("newest") else "?"
    nums = " ".join(f"#{n}" for n in g["numbers"][:12]) + (f" (+{len(g['numbers']) - 12} more)" if len(g["numbers"]) > 12 else "")
    return (f"[{g['label']}] {g['count']} automated ({g['pending']} not done), newest #{latest.get('number')} {when} "
            f"{(latest.get('title') or '')[:70]}\n  tickets: {nums}  (show ID for one)")


def list_grouped(rows: list) -> str:
    """`list --group`: operator requests and build reports in full, each kind of automated ticket as one line."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # this checkout's rules, deployed or not
    from gbox.inbox import grouped
    numbers = {r["id"]: r.get("number") for r in rows}
    out = []
    for e in grouped(rows):
        out.append(group_line(dict(e, numbers=[numbers[i] for i in e["ids"]])) if "group" in e else describe(e))
    return "\n".join(out)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    try:
        if cmd in ("prompt", "stop"):
            ev = json.loads(sys.stdin.read() or "{}")
            (hook_prompt if cmd == "prompt" else hook_stop)(ev)
            return
        if cmd == "list":
            args = [a for a in sys.argv[2:] if a != "--group"]
            status = args[0] if args else "open,in_progress,blocked"
            rows = api(f"/api/requests?status={status}")
            rows.sort(key=activity, reverse=True)      # a fresh operator message (a coaching note) comes first
            if "--group" in sys.argv[2:]:
                print(list_grouped(rows))
            else:
                for r in rows:
                    print(describe(r))
        elif cmd == "show":
            print(describe(api(f"/api/requests/{sys.argv[2]}"), full=True))
        elif cmd == "claim":
            api(f"/api/requests/{sys.argv[2]}/status", {"status": "in_progress", "note": "On it."})
            st = load_state()
            for sess in st.values():
                if isinstance(sess, dict) and "chat_request" in sess:
                    sess.setdefault("claimed", []).append(sys.argv[2])
            save_state(st)
            print("claimed", sys.argv[2])
        elif cmd == "reply":
            api(f"/api/requests/{sys.argv[2]}/messages", {"author": "agent", "text": sys.argv[3]})
            print("replied")
        elif cmd == "done":
            api(f"/api/requests/{sys.argv[2]}/status", {"status": "done", "note": sys.argv[3] if len(sys.argv) > 3 else ""})
            st = load_state()
            for sess in st.values():
                if isinstance(sess, dict) and sys.argv[2] in sess.get("claimed", []):
                    sess["claimed"].remove(sys.argv[2])
            save_state(st)
            print("done", sys.argv[2])
    except Exception as e:                             # hooks must never break the agent
        if cmd not in ("prompt", "stop"):
            raise
        print(f"(g-box ledger unavailable: {e})", file=sys.stderr)


if __name__ == "__main__":
    main()
