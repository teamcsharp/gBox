"""gBox request ledger + inbox CLI for the coding agent (Claude Code).

Hooks (configured in .claude/settings.json):
  prompt   UserPromptSubmit: logs every chat request to the gBox inbox, and prints new operator reports
           (screenshots / eyedropper picks, with local image paths) so the agent sees them in context.
  stop     Stop: reads this session's transcript and adds the turn's real usage to the active request:
           tokens in/out (incl. cache), tools used, files changed, agent time.
CLI (for the agent):
  list [status]          open reports first
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
        last = r["messages"][-1]
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
    save_state(st)


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

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    try:
        if cmd in ("prompt", "stop"):
            ev = json.loads(sys.stdin.read() or "{}")
            (hook_prompt if cmd == "prompt" else hook_stop)(ev)
            return
        if cmd == "list":
            status = sys.argv[2] if len(sys.argv) > 2 else "open,in_progress,blocked"
            for r in api(f"/api/requests?status={status}"):
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
