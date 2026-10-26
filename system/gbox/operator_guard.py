"""Protect the operator's live game from automation (docs/stream-stability.md).

A worker runs one emulator at a time (tools._close_previous_games), so any launch_game on the PC the operator is
playing on saves and closes their game, and a session swap restarts its emulator. Both black out the operator's
stream. These helpers decide:

- which running sessions belong to the operator (not agent-owned, gbox.background_testing.agent_owned);
- whether an automated (agent_use / agent actor) launch or swap may touch a worker or a session;
- on the Spark, while the operator plays there, which Hermes queue items to defer and how to lower the CPU/IO
  priority of agent sandboxes (bwrap trees under ~/.hermes) that run their own emulators.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable, Iterable

from .background_testing import agent_owned

AGENT_ACTORS = ("agent", "mcp", "gbox-agent", "hermes")
SANDBOX_MARKERS = ("/.hermes/cache/scratch", "/.hermes/sandbox")   # bwrap roots of Hermes agent tasks
SANDBOX_NICE = 19
WATCH_TTL_S = 180


def report_watch(store, viewer: str, sid: str | None, *, now=None, host: str = ""):
    """Short renewable viewer lease; applies to bot demos as well as human-owned sessions. host: the viewing machine's
    address (viewing(): the pad takeover's check that input comes from a machine that watches the session)."""
    import time
    if not sid:
        store.delete("session_watch", viewer)
        return
    store.put("session_watch", viewer, {"session_id": sid, "until":
              (time.time() if now is None else now) + WATCH_TTL_S, **({"host": host} if host else {})})


VIEW_CACHE_S, VIEW_MISS_S = 2.0, 0.5         # the input route asks on every pad change: a store read at most this often
_VIEWING: dict[tuple, tuple] = {}


def viewing(store, sid: str, host: str = "", *, now=None) -> bool:
    """Whether the machine at `host` watches session `sid` right now: its app said it shows the session
    (POST /api/broadcast/watching) or it streams it (GET /api/sessions/{sid}/mjpeg). The operator's pad input takes the
    pad from the session's bot only then (gbox/pad_takeover.py): a client never claims a session it isn't viewing. A row
    written before hosts were recorded counts for any machine."""
    import time
    now = time.time() if now is None else now
    hit = _VIEWING.get((sid, host))
    if hit and hit[0] > now:
        return hit[1]
    rows = [r for r in store.all("session_watch") if r.get("session_id") == sid and r.get("until", 0) > now]
    ok = any(not host or not r.get("host") or r.get("host") == host for r in rows)
    if len(_VIEWING) > 512:
        _VIEWING.clear()
    _VIEWING[(sid, host)] = (now + (VIEW_CACHE_S if ok else VIEW_MISS_S), ok)
    return ok


def kept_by(job: dict | None) -> set:
    """Sessions a launch keeps running (game_link host, the MercMode warm pool's parked / playing titles)."""
    inp = (job or {}).get("input") or {}
    return ({inp.get("keep_session") or ""} | set(inp.get("keep_sessions") or [])) - {""}


def watched_sessions(store, wid: str, *, now=None, keep=()) -> list[dict]:
    """Watched running sessions on this worker that a launch would close; `keep` (kept_by) are left out: a launch
    that keeps them up does not take the operator's view away (2026-10-24: every MercMode preload was rejected
    while the operator watched the playing title)."""
    import time
    now = time.time() if now is None else now
    ids = {r.get("session_id") for r in store.all("session_watch") if r.get("until", 0) > now} - set(keep)
    return [s for sid in ids if sid and worker_of(sid) == wid
            and (s := store.get("session", sid)) and s.get("state") == "running"]


def watching_reason(store, wid: str, keep=()) -> str | None:
    watched = watched_sessions(store, wid, keep=keep)
    if watched:
        titles = ", ".join(s.get("title") or s["session_id"] for s in watched)
        return f"Watching {titles} in a connected stream or PiP. Close that view before loading another game on this PC."
    return None


def is_agent(actor: str | None, agent_use: bool = False) -> bool:
    return bool(agent_use) or (actor or "") in AGENT_ACTORS


def worker_of(session_id: str) -> str:
    return (session_id or "").split("-")[0]


def operator_sessions(sessions: Iterable[dict], label: Callable[[str], dict | None],
                      launch_job: Callable[[str], dict | None], worker_ids: Iterable[str] | None = None,
                      keep: str = "") -> list[dict]:
    """Running sessions the operator owns, optionally only those on `worker_ids`; `keep` is excluded (a game_link
    host that a launch keeps running)."""
    wanted = set(worker_ids) if worker_ids is not None else None
    out = []
    for s in sessions:
        sid = s.get("session_id") or ""
        if s.get("state") != "running" or not sid or sid == keep:
            continue
        if wanted is not None and worker_of(sid) not in wanted:
            continue
        if not agent_owned(label(sid), launch_job(sid.split("-", 1)[-1])):
            out.append(s)
    return out


def launch_block(candidates: list[dict], busy: Callable[[str], list[dict]]) -> tuple[list[dict], str | None]:
    """For an automated launch: the candidate workers without an operator game, and the reason to refuse when none
    is left. `busy(worker_id)` lists the operator sessions on that worker."""
    free, taken = [], []
    for w in candidates:
        (taken if busy(w["id"]) else free).append(w)
    if free or not taken:
        return free, None
    names = ", ".join(sorted({w.get("name") or w["id"] for w in taken}))
    titles = ", ".join(sorted({s.get("title") or s.get("game_id") or s["session_id"]
                               for w in taken for s in busy(w["id"])}))
    return [], (f"The operator is playing {titles} on {names}. An automated launch there would save and close their "
                "game (one emulator per PC), so it was not queued. Use another PC (node=idle) or wait until they stop.")


# --- Spark-side protection for Hermes work ----------------------------------------------------------------------

def spark_operator_sessions(sessions: Iterable[dict], workers: Iterable[dict]) -> list[dict]:
    """Operator sessions on a Linux worker (the Spark, where Hermes runs). `sessions` rows come from the API, which
    has no slabel/job lookups: an agent's test session carries owner=agent in its label row or agent_use in its
    launch job, both unavailable here, so the caller passes rows already filtered or accepts the conservative view
    (every running Spark session counts as the operator's)."""
    linux = {w.get("id") for w in workers if w.get("os") == "linux" and w.get("online", True)}
    return [s for s in sessions if s.get("state") == "running" and worker_of(s.get("session_id") or "") in linux
            and not s.get("agent_owned")]


def _proc_table(proc_root: Path) -> dict[int, tuple[int, str]]:
    """pid -> (ppid, cmdline) from /proc (Linux)."""
    table = {}
    for d in proc_root.iterdir():
        if not d.name.isdigit():
            continue
        try:
            stat = (d / "stat").read_text()
            ppid = int(stat[stat.rindex(")") + 2:].split()[1])
            cmd = (d / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace").strip()
        except (OSError, ValueError, IndexError):
            continue
        table[int(d.name)] = (ppid, cmd)
    return table


def sandbox_pids(table: dict[int, tuple[int, str]], markers: Iterable[str] = SANDBOX_MARKERS) -> list[int]:
    """Every process inside a Hermes agent sandbox: bwrap roots whose command line names a sandbox folder, and all
    their descendants (the agent's own Dolphin/RetroArch, compilers, Python)."""
    roots = {pid for pid, (_, cmd) in table.items()
             if "bwrap" in cmd.split(" ", 1)[0] and any(m in cmd for m in markers)}
    children: dict[int, list[int]] = {}
    for pid, (ppid, _) in table.items():
        children.setdefault(ppid, []).append(pid)
    out, todo = set(), list(roots)
    while todo:
        pid = todo.pop()
        if pid in out:
            continue
        out.add(pid)
        todo.extend(children.get(pid, []))
    return sorted(out)


def throttle_agent_sandboxes(proc_root: str | Path = "/proc", nice: int = SANDBOX_NICE,
                             setprio: Callable[[int, int], None] | None = None,
                             ionice: Callable[[int], None] | None = None) -> dict:
    """Lower agent sandboxes to nice 19 and the idle I/O class while the operator plays on this machine. Raising
    niceness needs no privilege; it is never lowered again here (the sandbox finishes at low priority)."""
    root = Path(proc_root)
    if not root.is_dir():
        return {"throttled": [], "skipped": "no /proc"}
    setprio = setprio or (lambda pid, n: os.setpriority(os.PRIO_PROCESS, pid, n))

    def _ionice(pid):
        subprocess.run(["ionice", "-c", "3", "-p", str(pid)], capture_output=True, timeout=5)
    ionice = ionice or _ionice
    done, failed = [], []
    for pid in sandbox_pids(_proc_table(root)):
        try:
            if os.name != "nt" and setprio is not None and os.getpriority(os.PRIO_PROCESS, pid) >= nice:
                continue                                  # already throttled on an earlier tick
        except (OSError, AttributeError):
            pass
        try:
            setprio(pid, nice)
            try:
                ionice(pid)
            except (OSError, subprocess.SubprocessError):
                pass
            done.append(pid)
        except (OSError, PermissionError):
            failed.append(pid)
    return {"throttled": done, "failed": failed}
