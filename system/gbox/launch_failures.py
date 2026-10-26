"""Launch failure reports: a failed game launch files itself, gets a first remedy, an investigation, and a verified fix.

docs/launch-failure-reports.md. The operator's rule: "When a game fails to load I need it to auto file a report and I
need that report checked into and resolved so we can get these games loading fluidly."

* A failed launch_game / session_swap job, or a session that ends with a crash code within CRASH_WINDOW_S of starting,
  is a failure. Operator cancels, intentional stops, agent test launches and request-owned jobs are not.
* Failures group by signature = game_id + mod + adapter + error class: the first files an inbox request, repeats append
  an occurrence to it (and reopen it when it had been closed).
* classify() names the error class with a short diagnosis; a safe first remedy runs where one exists (a relaunch with a
  longer boot timeout, re-staging the mod) and is recorded on the ticket. Nothing ever stops or replaces a running game.
* A new or reopened ticket is put first in the Hermes work queue's priority list (or dispatched directly when the
  legacy controller runs) with a task: find the cause, fix it in code, publish a draft PR with screenshots.
* tick() closes the loop: once the ticket's PR merged and the deploy carries it, a verification launch of the same game
  and mod runs on an idle node (evidence_capture: agent-owned test session, never a node someone plays on); success
  closes the ticket with the frame, failure reopens it with the new evidence. An operator launch of the same game and
  mod that keeps running counts as verification too.
* backfill() files the last days' failures the same way.

Everything the control plane does (requests, jobs, Hermes, evidence capture) comes in through Hooks, so the ledger is
tested with fakes (tests/test_launch_failures.py).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import threading
import time
from typing import Callable

KIND = "launch_failure"              # store kind: signature -> ledger record (one per ticket)
JOB_KIND = "launch_failure_job"      # store kind: job id / "session:<sid>" -> how it was handled (processed marker)
SETTING_ID = "launch_failures"       # store "setting" doc: {auto_remedy, investigate, verify}
LAUNCH_TOOLS = ("launch_game", "session_swap")
FAILED_STATES = ("failed", "invalid", "rejected")
CRASH_WINDOW_S = 60.0                # a session ending with a crash code this soon after starting failed to load
SUCCESS_RUN_S = 60.0                 # an operator session running this long after the last failure verifies the fix
RELAUNCH_MAX_AGE_S = 180.0           # an automatic relaunch only right after the failure (the operator still waits)
RELAUNCH_COOLDOWN_S = 1800.0         # at most one automatic relaunch per signature in this window
LONG_BOOT_S = 90.0                   # boot timeout of the content-timeout remedy (the default is 30 s)
VERIFY_RETRY_S = 600.0               # no idle node / capture busy: try the verification again after this
UNKNOWN_DEPLOY_GRACE_S = 2700.0      # no deploy record on this machine: verify this long after the merge
MAX_OCCURRENCES = 60
DEFAULTS = {"auto_remedy": True, "investigate": True, "verify": True}

ADAPTERS = ("retroarch", "dolphin", "flycast", "pcsx2", "duckstation", "rpcs3", "shadps4", "ppsspp", "xenia", "cemu", "mame",
            "redream", "xemu", "cxbx", "melonds", "citra", "ryujinx", "yuzu", "eden", "mupen64plus", "mgba", "steam",
            "rocketlauncher")
ADAPTER_RX = re.compile(r"\b(" + "|".join(ADAPTERS) + r")\b", re.I)
PLATFORM_ADAPTER = {"gamecube": "dolphin", "wii": "dolphin", "ps3": "rpcs3", "ps4": "shadps4", "xbox360": "xenia", "switch": "yuzu",
                    "xbox": "cxbx", "pc_steam": "steam"}

CANCELLED_RX = re.compile(r"cancelled by the operator|cancelled with its parent|^cancelled\b|stopped by the operator", re.I)
TRANSIENT_VERIFY_RX = re.compile(r"No idle node|Can't capture on|yielded|already running|server restarted|Interrupted|"
                                 r"cancelled|is offline|could not start", re.I)


# ------------------------------------------------------------------------------------------------ classification

@dataclasses.dataclass(frozen=True)
class ErrorClass:
    cls: str
    rx: re.Pattern
    diagnosis: str
    remedy: str                       # relaunch_long_boot | restage_mod | relaunch | none


CLASSES = (
    ErrorClass("previous_game_blocking",
               re.compile(r"previous game \((?P<blocker>.+?)\) could not be saved|previous emulator is still running", re.I),
               "Another game was running on this PC and could not be saved first, so gBox kept it running and refused "
               "to replace it. The new game never started. The blocker is the running game's save state, not this game.",
               "none"),
    ErrorClass("content_timeout",
               re.compile(r"started but content not running after (?P<secs>\d+)\s*s", re.I),
               "The emulator process started but did not report the game as running within its boot timeout. Usual "
               "causes: a slow first boot (shader or disc cache, a large staged image), a core that never leaves its "
               "menu for this image, or a mod image the core rejects.",
               "relaunch_long_boot"),
    ErrorClass("missing_bios",
               re.compile(r"(bios|firmware|prod\.keys|title\.keys|dc_boot|dc_flash|scph\w*)\b[^\n]{0,80}"
                          r"(missing|not found|required|absent)|(missing|no)\s+(bios|firmware)", re.I),
               "The emulator needs a BIOS/firmware file this node does not have.",
               "none"),
    ErrorClass("mod_fetch",
               re.compile(r"Fetching mod|fetch(?:ing)? (?:the )?mod|stag(?:e|ing) (?:the )?mod|mod .{0,60}(?:hash|checksum)|"
                          r"hash mismatch|Replacement preparation did not complete|Prepared replacement|"
                          r"\.gbox-mod\.json|[\\/]mods[\\/]", re.I),
               "The mod's files could not be fetched from the collection or staged on this PC (a timeout, an "
               "incomplete copy or a stale staged folder).",
               "restage_mod"),
    ErrorClass("mod_not_built",
               re.compile(r"no built mod .+ for this game", re.I),
               "The launch asked for a mod that was never built: it is neither on this PC nor in the central "
               "collection. Build the mod first (Special builds or a cast build), or launch the stock game without a mod.",
               "none"),
    ErrorClass("emulator_crash",
               re.compile(r"\b(?P<emu>[a-z0-9_]+) exited (?:with code )?(?P<code>-?\d+)|crashed|access violation|"
                          r"segmentation fault|0xc0000005", re.I),
               "The emulator process exited while the game was booting.",
               "relaunch"),
    ErrorClass("missing_file",
               re.compile(r"FileNotFoundError|not reachable from this node|No such file|cannot find the (?:file|path)|"
                          r"EBOOT\.BIN", re.I),
               "The game's file is not reachable from this node (library share offline, a moved file or a wrong path).",
               "none"),
    ErrorClass("worker_restarted",
               re.compile(r"worker .{0,60}restarted|server restarted|Interrupted: the gBox server", re.I),
               "The gBox worker (or the control plane) restarted while the launch was running, so it was abandoned.",
               "relaunch"),
    ErrorClass("worker_unavailable",
               re.compile(r"can't run launch_game|must update its worker|permission not granted|no worker|is offline", re.I),
               "No PC could take the launch: the chosen worker is offline, outdated or lacks the launch tool.",
               "none"),
    ErrorClass("state_restore",
               re.compile(r"state restore failed|restoration of the saved game moment|load_state", re.I),
               "The modded game started but the saved moment could not be restored into it.",
               "none"),
    ErrorClass("timeout",
               re.compile(r"timed out|timeout", re.I),
               "The launch did not finish within its time limit.",
               "relaunch"),
)
UNKNOWN_DIAGNOSIS = "Unclassified launch error: the investigation starts from the error text and the logs below."


def normalise_error(text: str) -> str:
    """The error without the parts that vary between occurrences (numbers, hashes, paths, quoted names)."""
    t = str(text or "").splitlines()[0] if str(text or "").strip() else ""
    t = re.sub(r"(?:[A-Za-z]:)?[\\/][^\s:'\"]+", "<path>", t)
    t = re.sub(r"\b[0-9a-f]{8,}\b", "<hex>", t, flags=re.I)
    t = re.sub(r"\d+(?:\.\d+)?", "<n>", t)
    t = re.sub(r"\(([^)]{0,80})\)", "(<x>)", t)
    return " ".join(t.lower().split())[:200]


def classify(error: str, *, adapter: str = "", session_exit: dict | None = None) -> dict:
    """{cls, label, diagnosis, remedy, detail} for an error text (or a session that ended with a crash code)."""
    error = str(error or "")
    if session_exit is not None:
        code = session_exit.get("returncode")
        secs = session_exit.get("lifetime_s")
        return {"cls": "emulator_crash", "remedy": "relaunch",
                "label": f"{adapter or 'emulator'} crashed {int(secs or 0)} s after starting (exit {_code(code)})",
                "diagnosis": "The launch reported the game running, then the emulator process exited with a crash code "
                             "within the first minute.",
                "detail": {"returncode": code, "lifetime_s": secs}}
    for c in CLASSES:
        m = c.rx.search(error)
        if not m:
            continue
        g = {k: v for k, v in m.groupdict().items() if v}
        if c.cls == "previous_game_blocking":
            label = (f"previous game ({g['blocker'][:60]}) could not be saved, so it kept running"
                     if g.get("blocker") else "the previous emulator could not be closed")
        elif c.cls == "content_timeout":
            label = f"{adapter or 'emulator'} content not running after {g.get('secs', '30')}s"
        elif c.cls == "missing_bios":
            name = re.search(r"[\w.-]+\.(?:bin|rom|keys|img|zip)\b", error, re.I)
            label = "missing BIOS/firmware" + (f": {name[0]}" if name else "")
            g["file"] = name[0] if name else ""
        elif c.cls == "mod_fetch":
            label = "the mod could not be fetched or staged"
        elif c.cls == "emulator_crash":
            label = (f"{g.get('emu') or adapter or 'emulator'} exited with code {_code(g.get('code'))} during boot"
                     if g.get("code") else f"{adapter or 'emulator'} crashed during boot")
        else:
            label = {"missing_file": "game file not reachable from this node",
                     "worker_restarted": "the worker restarted during the launch",
                     "worker_unavailable": "no PC could take the launch",
                     "state_restore": "the saved moment could not be restored after the swap",
                     "mod_not_built": "the mod was never built for this game",
                     "timeout": "the launch timed out"}[c.cls]
        return {"cls": c.cls, "label": label, "diagnosis": c.diagnosis, "remedy": c.remedy, "detail": g}
    first = (error.strip().splitlines() or ["launch failed"])[0]
    first = re.sub(r"^(?:RuntimeError|Unsupported|ToolUnavailable|ValueError|Exception):\s*", "", first)
    key = hashlib.sha1(normalise_error(error).encode()).hexdigest()[:8]
    return {"cls": "unknown:" + key, "label": first[:90] or "launch failed", "diagnosis": UNKNOWN_DIAGNOSIS,
            "remedy": "none", "detail": {}}


def _code(code) -> str:
    try:
        n = int(code)
    except (TypeError, ValueError):
        return str(code)
    return f"{n} (0x{n & 0xFFFFFFFF:08X})" if n < 0 or n > 255 else str(n)


def signature(game_id: str, mod: str, adapter: str, cls: str) -> str:
    return hashlib.sha1("\x1f".join([game_id or "", mod or "", (adapter or "").lower(), cls]).encode()).hexdigest()[:16]


def adapter_for(game: dict | None, error: str = "", known: str = "") -> str:
    """The emulator a launch used: a session's / job output's own name, else the platform rule, else the error text."""
    if known:
        return known.lower()
    game = game or {}
    plat = str(game.get("platform") or "")
    if plat in PLATFORM_ADAPTER:
        return PLATFORM_ADAPTER[plat]
    if game.get("core"):
        return "retroarch"
    m = ADAPTER_RX.search(error or "")
    if m:
        return m[1].lower()
    if (game.get("launch") or {}).get("kind") == "attract":
        return "rocketlauncher"
    return plat or "unknown"


def badge(summary: dict | None) -> str:
    """The words a client shows next to a failed launch."""
    if not summary or not summary.get("number"):
        return ""
    if summary.get("verified"):
        return f"Fixed, verified (#{summary['number']})"
    return f"Reported as #{summary['number']}, being investigated"


def summarize(store, rec: dict) -> dict:
    """A ticket as the clients show it: number, request status, ledger state, badge text."""
    req = store.get("request", rec["request_id"]) or {}
    out = {"request_id": rec["request_id"], "number": rec.get("number") or req.get("number"),
           "status": req.get("status") or "open", "state": rec.get("state"),
           "verified": rec.get("state") == "verified", "error_class": rec.get("error_class"),
           "label": rec.get("label"), "count": rec.get("count", 1), "signature": rec["id"],
           "last_seen": rec.get("last_seen")}
    return out | {"text": badge(out)}


def index(store) -> dict:
    """(game_id, mod) -> the newest ticket summary, for the Mods page cards (gbox/built_mods.py)."""
    out = {}
    for rec in store.all(KIND):
        k = (rec.get("game_id") or "", rec.get("mod") or "")
        if k not in out or (rec.get("last_seen") or 0) > (out[k].get("last_seen") or 0):
            out[k] = summarize(store, rec)
    return out


# ------------------------------------------------------------------------------------------------ the ledger

@dataclasses.dataclass
class Hooks:
    """What the ledger needs from the control plane. Every hook has a harmless default."""
    create_request: Callable[[dict], dict]                                  # RequestIn-shaped dict -> request doc
    workers: Callable[[], list] = lambda: []                                # [{id, name, os, online, idle_seconds, ...}]
    submit_job: Callable | None = None              # (tool, input, worker_id) -> job doc; actor gbox-auto, operator volume
    investigate: Callable | None = None             # (request_id, number, task, attempt) -> {mode, job_id, priority}
    queue_job_of: Callable[[str], str | None] = lambda rid: None            # Hermes queue job dispatched for a request
    unprioritize: Callable[[str], None] = lambda rid: None                  # drop a closed request from the priority list
    verify_launch: Callable | None = None           # (record, node) -> job doc (an evidence_capture job)
    deploy_contains: Callable[[str], bool | None] = lambda sha: None        # True / False / None = unknown here
    last_frame: Callable[[str], bytes | None] = lambda sid: None            # PNG of a session's last picture
    swap_parent: Callable[[dict], str | None] = lambda job: None            # the session_swap that ran this launch
    now: Callable[[], float] = time.time
    spawn: Callable[[Callable], None] = lambda fn: threading.Thread(target=fn, daemon=True,
                                                                     name="launch-failure").start()
    sleep: Callable[[float], None] = time.sleep


class Ledger:
    def __init__(self, store, hooks: Hooks):
        self.store, self.h = store, hooks
        self.lock = threading.RLock()

    # ---- settings ----
    def settings(self) -> dict:
        return DEFAULTS | {k: v for k, v in ((self.store.get("setting", SETTING_ID) or {}).items()) if k in DEFAULTS}

    def set_settings(self, **changes) -> dict:
        cur = self.settings() | {k: bool(v) for k, v in changes.items() if k in DEFAULTS and v is not None}
        self.store.put("setting", SETTING_ID, cur)
        return cur

    # ---- what happened ----
    def _resolve_worker_id(self, wid: str | None) -> str:
        """A restarted worker re-registers with a new id; follow worker_alias to the current one (server._wid)."""
        if not wid:
            return wid or ""
        for _ in range(20):
            a = self.store.get("worker_alias", wid)
            if not a or not a.get("to") or a["to"] == wid:
                break
            wid = str(a["to"])
        return wid

    def _worker(self, wid: str | None) -> dict:
        if not wid:
            return {}
        wid = self._resolve_worker_id(wid)
        return next((w for w in self.h.workers() if w.get("id") == wid or w.get("name") == wid), None) or \
            (self.store.get("worker", wid) or {"id": wid})

    def _job_artifacts(self, job: dict) -> list[dict]:
        receipt = self.store.get("receipt", job.get("receipt_id") or "") or {}
        arts = list(receipt.get("artifacts") or [])
        if job.get("log_sha"):
            meta = self.store.get("artifact", job["log_sha"])
            if meta:
                arts.append(meta)
        return arts

    def _read_json_artifact(self, arts: list[dict], name: str) -> dict:
        for a in arts:
            if a.get("name") == name:
                try:
                    return json.loads((self.store.read_artifact(a["sha256"]) or b"{}").decode("utf-8", "replace"))
                except ValueError:
                    return {}
        return {}

    def _recent_jobs(self, game_id: str, worker_id: str, before: float, limit: int = 12) -> list[dict]:
        try:
            with self.store.lock:
                rows = self.store.db.execute(
                    "SELECT body FROM docs WHERE kind='job' AND COALESCE(json_extract(body,'$.created'),0) BETWEEN ? AND ? "
                    "AND (json_extract(body,'$.worker_id')=? OR json_extract(body,'$.input.game_id')=? "
                    "OR json_extract(body,'$.input.game.game_id')=?) ORDER BY rowid DESC LIMIT ?",
                    (before - 3 * 3600, before + 1, worker_id or "", game_id, game_id, limit)).fetchall()
        except Exception:                                            # noqa: BLE001 - a fake store in tests
            rows = []
        out = []
        for (body,) in rows:
            j = json.loads(body)
            if j.get("tool") in ("get_frame",):
                continue
            out.append({"id": j.get("id"), "tool": j.get("tool"), "state": j.get("state"), "created": j.get("created"),
                        "worker_id": j.get("worker_id"), "error": str(j.get("error") or "")[:300],
                        "input": {k: v for k, v in (j.get("input") or {}).items() if k != "game"}})
        return out

    def _running_on(self, worker_id: str) -> list[dict]:
        out = []
        for s in self._sessions(state="running"):
            if (s.get("session_id") or "").split("-")[0] == worker_id:
                out.append(s)
        return out

    def _sessions(self, *, game_id: str = "", state: str = "") -> list[dict]:
        try:
            q, args = "SELECT body FROM docs WHERE kind='session'", []
            if game_id:
                q += " AND json_extract(body,'$.game_id')=?"
                args.append(game_id)
            if state:
                q += " AND json_extract(body,'$.state')=?"
                args.append(state)
            with self.store.lock:
                rows = self.store.db.execute(q, args).fetchall()
            return [json.loads(r[0]) for r in rows]
        except AttributeError:
            return [s for s in self.store.all("session") if (not game_id or s.get("game_id") == game_id)
                    and (not state or s.get("state") == state)]

    def facts_from_job(self, job: dict) -> dict:
        """Everything a ticket needs about one failed launch / swap job."""
        inp = job.get("input") or {}
        tool = job.get("tool")
        if tool == "session_swap":
            game_id = inp.get("game_id") or ""
            sess = self.store.get("session", inp.get("session_id") or "") or {}
            wid = (inp.get("session_id") or "").split("-")[0]
            if inp.get("to"):
                wid = (self._worker(inp["to"]) or {}).get("id") or inp["to"]
        else:
            game_id = ((inp.get("game") or {}) if isinstance(inp.get("game"), dict) else {}).get("game_id") or ""
            sess = {}
            wid = job.get("worker_id") or job.get("require_worker") or ""
        game = self.store.catalog_get(game_id) or (inp.get("game") if isinstance(inp.get("game"), dict) else {}) or {}
        error = str(job.get("error") or job.get("state") or "")
        arts = self._job_artifacts(job)
        diag = self._read_json_artifact(arts, "launch-failure.json")
        inner = []
        if tool == "session_swap":
            # the launch the swap ran: its own error, logs and diagnostics are the evidence
            try:
                with self.store.lock:
                    rows = self.store.db.execute(
                        "SELECT body FROM docs WHERE kind='job' AND json_extract(body,'$.tool')='launch_game' "
                        "AND json_extract(body,'$.input.game.game_id')=? AND COALESCE(json_extract(body,'$.created'),0) "
                        "BETWEEN ? AND ? ORDER BY rowid", (game_id, (job.get("started") or job.get("created") or 0) - 1,
                                                           (job.get("finished") or self.h.now()) + 1)).fetchall()
                inner = [json.loads(r[0]) for r in rows]
            except AttributeError:
                inner = []
            for ij in inner:
                arts += self._job_artifacts(ij)
                diag = diag or self._read_json_artifact(arts, "launch-failure.json")
        adapter = adapter_for(game, error, diag.get("adapter") or sess.get("adapter") or "")
        w = self._worker(wid)
        created, started, finished = job.get("created"), job.get("started"), job.get("finished")
        timings = {"queued_s": round(started - created, 1) if started and created else None,
                   "ran_s": round(finished - started, 1) if finished and started else None,
                   "stages": diag.get("timings") or {}}
        blocker = None
        cls_probe = classify(error, adapter=adapter)
        if cls_probe["cls"] == "previous_game_blocking" and wid:
            name = (cls_probe["detail"] or {}).get("blocker", "")
            running = self._running_on(wid)
            hit = next((s for s in running if name and name.lower() in str(s.get("title") or "").lower()), None) \
                or (running[0] if running else None)
            blocker = {"title": name or (hit or {}).get("title"), "session_id": (hit or {}).get("session_id"),
                       "adapter": (hit or {}).get("adapter"), "started": (hit or {}).get("started"),
                       "state": (hit or {}).get("state") or ("not running any more" if not hit else "")}
        mod = str(inp.get("mod") or "")
        return {"tool": tool, "job_id": job.get("id"), "game_id": game_id, "title": game.get("title") or game_id,
                "platform": game.get("platform") or "", "mod": mod, "adapter": adapter, "worker_id": wid,
                "worker": w.get("name") or wid or "unknown node", "worker_os": w.get("os") or "",
                "error": error, "state": job.get("state"), "created": created, "started": started, "finished": finished,
                "timings": timings, "progress_log": list(job.get("progress_log") or [])[-40:],
                "diag": diag, "artifacts": arts, "blocker": blocker,
                "staging": {"mod": mod, "staged_mod": (diag.get("staged_mod") or ""), "cached_on": game.get("cached_on"),
                            "staging": diag.get("staging"), "stage_reached": diag.get("stage")},
                "session": {k: sess.get(k) for k in ("session_id", "title", "adapter", "state", "mod", "started")} if sess else None,
                "inner_jobs": [{"id": j.get("id"), "state": j.get("state"), "error": str(j.get("error") or "")[:600]}
                               for j in inner],
                "recent_jobs": self._recent_jobs(game_id, wid, created or self.h.now()),
                "agent_use": bool(job.get("agent_use")), "game": game}

    def skip_reason(self, job: dict) -> str | None:
        """Why a finished launch job is not a failure to report (None = report it)."""
        if job.get("tool") not in LAUNCH_TOOLS:
            return "not a launch"
        if job.get("state") not in FAILED_STATES:
            return "did not fail"
        err = str(job.get("error") or "")
        if job.get("cancel") or job.get("cancel_requested") or CANCELLED_RX.search(err):
            return "cancelled by the operator"
        from .storage_policy import POLICY_RX
        if POLICY_RX.search(err):
            return "refused by the storage policy (a build not downloaded to that PC, or game data on its system drive)"
        if job.get("agent_use"):
            return "agent test launch (evidence capture / investigation): reported by its own task"
        if job.get("parent_request_id"):
            return "part of an inbox request's own work"
        if job.get("issue_internal"):
            return "internal diagnostic job"
        if (job.get("input") or {}).get("capture_backend"):
            return "Examine 3D capture session: reported by the capture"
        if job.get("tool") == "launch_game" and self.h.swap_parent(job):
            return "launched by a session swap: the swap reports it"
        marker = self.store.get(JOB_KIND, job.get("id") or "")
        if marker and marker.get("remedy_for"):
            return "an automatic remedy relaunch: recorded on its ticket"
        return None

    # ---- intake ----
    def observe_job(self, job: dict, *, source: str = "job", remedy: bool = True) -> dict | None:
        """A finished launch / swap job. Returns the ledger record it was filed under (None when skipped / seen)."""
        jid = job.get("id") or ""
        with self.lock:
            seen = self.store.get(JOB_KIND, jid)
            if seen and seen.get("signature"):
                return self.store.get(KIND, seen["signature"])
            why = self.skip_reason(job)
            if why:
                if not seen:
                    self.store.put(JOB_KIND, jid, {"id": jid, "skipped": why, "ts": self.h.now()})
                return None
            facts = self.facts_from_job(job)
            if not facts["game_id"]:
                self.store.put(JOB_KIND, jid, {"id": jid, "skipped": "no game id", "ts": self.h.now()})
                return None
            c = classify(facts["error"], adapter=facts["adapter"])
            rec = self._file(facts, c, source=source)
            self.store.put(JOB_KIND, jid, {"id": jid, "signature": rec["id"], "ts": self.h.now(), "source": source})
        self._stamp_job(jid, rec)
        if remedy and source != "backfill":
            self.h.spawn(lambda: self._remedy(rec["id"], facts, c, job))
        return rec

    def observe_session_end(self, session: dict, info: dict, *, stop_requested: bool = False,
                            label: dict | None = None) -> dict | None:
        """A session the worker reported ended. A crash code within CRASH_WINDOW_S of starting is a failed load."""
        sid = session.get("session_id") or ""
        if not isinstance(info, dict) or info.get("via") or stop_requested or session.get("replaced_by"):
            return None
        code = info.get("returncode")
        from .session_exit import crash_code, intentional
        if intentional(info) or not crash_code(info):
            return None
        started = session.get("started") or 0
        ended = session.get("ended") or self.h.now()
        lifetime = ended - started if started else None
        if lifetime is None or lifetime > CRASH_WINDOW_S:
            return None
        if (label or {}).get("owner") == "agent" or str((label or {}).get("label") or "").startswith("Evidence capture"):
            return None
        key = "session:" + sid
        with self.lock:
            if self.store.get(JOB_KIND, key):
                return None
            game = self.store.catalog_get(session.get("game_id") or "") or {}
            wid = sid.split("-")[0]
            w = self._worker(wid)
            adapter = adapter_for(game, "", session.get("adapter") or "")
            c = classify("", adapter=adapter, session_exit={"returncode": code, "lifetime_s": round(lifetime, 1)})
            log = str(info.get("log_tail") or "")
            frame = None
            try:
                frame = self.h.last_frame(sid)
            except Exception:                                    # noqa: BLE001 - a missing frame never loses the report
                frame = None
            facts = {"tool": "session", "job_id": sid.split("-", 1)[-1] if "-" in sid else "", "session_id": sid,
                     "game_id": session.get("game_id") or "", "title": game.get("title") or session.get("title") or "",
                     "platform": game.get("platform") or "", "mod": session.get("collection_mod") or session.get("mod") or "",
                     "adapter": adapter, "worker_id": wid, "worker": w.get("name") or wid, "worker_os": w.get("os") or "",
                     "error": f"{adapter} exited with code {_code(code)} {lifetime:.0f} s after the launch reported the game running",
                     "state": "ended", "created": started, "started": started, "finished": ended,
                     "timings": {"lifetime_s": round(lifetime, 1)}, "progress_log": [], "diag": {"log": log[-60000:]},
                     "artifacts": [], "blocker": None, "frame_png": frame,
                     "staging": {"mod": session.get("mod"), "staged_mod": session.get("staged_mod") or session.get("launch_mod")},
                     "session": {k: session.get(k) for k in ("session_id", "title", "adapter", "state", "mod", "started", "ended")},
                     "inner_jobs": [], "recent_jobs": self._recent_jobs(session.get("game_id") or "", wid, ended),
                     "agent_use": False, "game": game}
            if not facts["game_id"]:
                return None
            rec = self._file(facts, c, source="session")
            self.store.put(JOB_KIND, key, {"id": key, "signature": rec["id"], "ts": self.h.now(), "source": "session"})
            launch_jid = facts["job_id"]
        if launch_jid:
            self._stamp_job(launch_jid, rec)
        return rec

    # ---- filing ----
    def _title(self, facts: dict, c: dict) -> str:
        what = facts["title"] or facts["game_id"]
        what = what if len(what) <= 60 else what[:57] + "..."
        mod = f" ({facts['mod']})" if facts["mod"] else ""
        return f"Launch failed: {what}{mod} on {facts['worker']}: {c['label']}"[:140]

    def _evidence(self, facts: dict, c: dict, rid: str) -> tuple[list[dict], str]:
        """Attachments (stored artifacts) and the log section of the ticket body."""
        atts = []

        def put(name, data: bytes, media):
            ref = self.store.put_artifact(data, name, media, {"request": rid, "launch_failure": True,
                                                              "job": facts.get("job_id") or ""})
            atts.append({"sha256": ref.sha256, "name": name, "type": media, "size": ref.size})
            return ref
        lines = []
        job_log = "\n".join(str(x) for x in facts.get("progress_log") or [])
        worker_log = next((a for a in facts["artifacts"] if a.get("name") == "worker.log"), None)
        emu_logs = [a for a in facts["artifacts"] if a.get("name") in ("emulator-log.txt", "emulator.log")]
        for a in [worker_log] + emu_logs:
            if a:
                atts.append({"sha256": a["sha256"], "name": a["name"], "type": a.get("media_type") or "text/plain",
                             "size": a.get("size")})
        if job_log:
            put("job-progress.txt", job_log.encode("utf-8", "replace"), "text/plain")
            lines.append("Job progress (last lines):\n" + "\n".join(f"    {x}" for x in job_log.splitlines()[-12:]))
        emu = ""
        if emu_logs:
            emu = (self.store.read_artifact(emu_logs[0]["sha256"]) or b"").decode("utf-8", "replace")
        elif facts.get("diag", {}).get("log"):
            emu = str(facts["diag"]["log"])
            put("emulator-log.txt", emu.encode("utf-8", "replace"), "text/plain")
        elif ": " in facts["error"] and "\n" in facts["error"]:
            emu = facts["error"].split(": ", 1)[1]               # retroarch puts its log tail in the error text
            put("emulator-log.txt", emu.encode("utf-8", "replace"), "text/plain")
        if emu:
            lines.append("Emulator log tail:\n" + "\n".join(f"    {x}" for x in emu.rstrip().splitlines()[-15:]))
        else:
            lines.append("Emulator log: none came back from the worker (the emulator may not have started).")
        evidence = {k: v for k, v in facts.items() if k not in ("artifacts", "frame_png", "game")} | {
            "classification": c, "catalog": {k: (facts.get("game") or {}).get(k) for k in
                                             ("game_id", "title", "platform", "system", "core", "library", "rel_path",
                                              "launch", "playable", "cached_on", "size")}}
        put("launch-failure-evidence.json", json.dumps(evidence, indent=2, default=str, ensure_ascii=False).encode(),
            "application/json")
        if facts.get("frame_png"):
            put("last-frame.png", facts["frame_png"], "image/png")
        return atts, "\n\n".join(lines)

    def _body(self, facts: dict, c: dict, remedy_text: str, logs: str) -> str:
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(facts.get("finished") or self.h.now()))
        t = facts["timings"] or {}
        parts = [
            "## What failed\n"
            f"{facts['title'] or facts['game_id']} (game_id {facts['game_id']}, {facts['platform'] or '?'})"
            + (f" with mod {facts['mod']}" if facts["mod"] else " (stock game)")
            + f" on {facts['worker']}" + (f" ({facts['worker_os']})" if facts["worker_os"] else "")
            + f", emulator {facts['adapter']}. {facts['tool']} job {facts.get('job_id') or '-'} {facts['state']} at {when}.",
            "## Error\n```\n" + facts["error"][:1500] + "\n```",
            f"## Diagnosis ({c['cls'].split(':')[0]})\n{c['diagnosis']}",
            "## Automatic remedy\n" + remedy_text,
            "## Timings\n" + json.dumps(t, default=str),
            "## Mod and staging\n" + json.dumps(facts.get("staging") or {}, default=str),
        ]
        if facts.get("blocker"):
            b = facts["blocker"]
            parts.append("## Previous session blocking the launch\n"
                         f"{b.get('title') or '?'} (session {b.get('session_id') or 'not found'}, {b.get('adapter') or '?'}, "
                         f"{b.get('state') or '?'}). gBox saves the running game before switching; that save failed, so "
                         "the game was kept running. The fix belongs to that emulator's save state, and the operator "
                         "can stop it in Sessions to launch this one.")
        if facts.get("session"):
            parts.append("## Session\n" + json.dumps(facts["session"], default=str))
        if facts.get("inner_jobs"):
            parts.append("## Launch jobs the swap ran\n" + "\n".join(
                f"- {j['id']} [{j['state']}] {j['error']}" for j in facts["inner_jobs"]))
        parts.append("## Logs\n" + logs)
        if facts.get("recent_jobs"):
            parts.append("## Recent jobs on this node / for this game\n" + "\n".join(
                f"- {j['tool']} [{j['state']}] {j['id']}" + (f": {j['error'][:200]}" if j.get("error") else "")
                for j in facts["recent_jobs"][:12]))
        return "\n\n".join(parts)

    def _remedy_plan(self, c: dict, facts: dict) -> str:
        if not self.settings()["auto_remedy"]:
            return "Automatic remedies are switched off (POST /api/launch-failures/settings)."
        r = c["remedy"]
        if r == "relaunch_long_boot":
            return (f"Relaunch once on {facts['worker']} with a {int(LONG_BOOT_S)} s boot timeout, if the PC is still idle "
                    "and nothing else was launched meanwhile. The result is added below.")
        if r == "restage_mod":
            return ("Re-stage the mod on that PC (prepare_mod: fetches and verifies the files again without touching a "
                    "running game), then relaunch once if the PC is still idle. The result is added below.")
        if r == "relaunch":
            return "Relaunch once if the PC is still idle and nothing else was launched meanwhile. The result is added below."
        if c["cls"] == "previous_game_blocking":
            return ("None automatic: gBox never stops a running game (its progress could be lost). Stop the previous "
                    "game in Sessions, then launch again.")
        return "None automatic for this kind of failure: it goes straight to the investigation."

    def _file(self, facts: dict, c: dict, *, source: str) -> dict:
        sig = signature(facts["game_id"], facts["mod"], facts["adapter"], c["cls"])
        now = self.h.now()
        occ = {"ts": facts.get("finished") or now, "job_id": facts.get("job_id"), "tool": facts["tool"],
               "worker": facts["worker"], "error": facts["error"][:600], "source": source,
               "session_id": facts.get("session_id") or ""}
        rec = self.store.get(KIND, sig)
        req = self.store.get("request", rec["request_id"]) if rec else None
        if rec and req:
            rec["occurrences"] = (rec.get("occurrences") or [])[-(MAX_OCCURRENCES - 1):] + [occ]
            rec["count"] = rec.get("count", 0) + 1
            rec["last_seen"] = max(rec.get("last_seen") or 0, occ["ts"])
            atts, _logs = self._evidence(facts, c, req["id"])
            # closed, or failing again after its fix was deployed: the fix did not hold
            reopen = req.get("status") == "done" or rec.get("state") in ("verified", "awaiting_verify", "verifying")
            text = (f"Occurred again ({rec['count']} times): {facts['tool']} job {facts.get('job_id') or '-'} on "
                    f"{facts['worker']} at {time.strftime('%Y-%m-%d %H:%M', time.localtime(occ['ts']))}.\n"
                    f"Error: {facts['error'][:600]}")
            self._message(req["id"], text, atts, action="launch failure occurrence", result=f"occurrence {rec['count']}",
                          status="failed")
            if reopen:
                rec.update(state="investigating", reopened=now, pr=None, verify=None, verified=None,
                           reopen_count=rec.get("reopen_count", 0) + 1)
                self._set_status(req["id"], "open", "The failure happened again after the ticket was closed: reopened.")
            self.store.put(KIND, sig, rec)
            self._publish(rec)
            if reopen:                                           # after the record is saved: it updates it
                self.h.spawn(lambda: self._investigate(sig, reopened=True))
            return rec
        req = self.h.create_request({
            "title": self._title(facts, c), "body": "(collecting evidence)", "source": "automation", "kind": "text",
            "author": "system", "automated": True,
            "context": {"launch_failure": True, "auto_report": True, "signature": sig, "game_id": facts["game_id"],
                        "game": facts["title"], "mod": facts["mod"], "adapter": facts["adapter"],
                        "error_class": c["cls"], "worker": facts["worker"], "job_id": facts.get("job_id") or "",
                        "session_id": facts.get("session_id") or "", "launch_failure_source": source}})
        rid = req["id"]
        atts, logs = self._evidence(facts, c, rid)
        body = self._body(facts, c, self._remedy_plan(c, facts), logs)
        with self.store.lock:
            cur = self.store.get("request", rid) or req
            cur["body"] = body
            cur["messages"] = [{"author": "system", "text": body, "ts": now, "attachments": atts}] + [
                m for m in (cur.get("messages") or []) if m.get("text") != "(collecting evidence)"]
            img = next((a["sha256"] for a in atts if a["type"] == "image/png"), None)
            if img:
                cur["image"], cur["kind"] = img, "screenshot"
            self.store.put("request", rid, cur)
        rec = {"id": sig, "signature": sig, "request_id": rid, "number": req.get("number"), "game_id": facts["game_id"],
               "title": facts["title"], "mod": facts["mod"], "adapter": facts["adapter"], "error_class": c["cls"],
               "label": c["label"], "diagnosis": c["diagnosis"], "state": "investigating", "created": now,
               "first_seen": occ["ts"], "last_seen": occ["ts"], "count": 1, "occurrences": [occ], "remedies": [],
               "hermes": None, "pr": None, "verify": None, "verified": None, "worker_id": facts["worker_id"],
               "worker": facts["worker"]}
        self.store.put(KIND, sig, rec)
        self.store.audit("gbox-auto", "launch_failure.filed", rid, {"signature": sig, "class": c["cls"],
                                                                    "job": facts.get("job_id"), "source": source})
        self._publish(rec)
        self.h.spawn(lambda: self._investigate(sig))
        return rec

    # ---- request helpers ----
    def _message(self, rid: str, text: str, attachments=(), *, action: str = "", result: str = "", status: str = ""):
        with self.store.lock:
            r = self.store.get("request", rid)
            if not r:
                return
            m = {"author": "agent", "text": text, "ts": self.h.now(), "attachments": list(attachments)}
            if action:
                m["task_step"] = {"action": action, "attempt": "1", "result": str(result)[:4000], "status": status}
            r.setdefault("messages", []).append(m)
            self.store.put("request", rid, r)

    def _set_status(self, rid: str, status: str, note: str = ""):
        with self.store.lock:
            r = self.store.get("request", rid)
            if not r:
                return
            now = self.h.now()
            if status == "in_progress" and not r.get("started"):
                r["started"] = now
            if status == "done":
                r["completed"] = now
                r.setdefault("metrics", {})["duration_s"] = round(now - (r.get("started") or r.get("created") or now), 1)
            elif r.get("status") == "done":
                r["completed"] = None
            r["status"] = status
            if note:
                r.setdefault("messages", []).append({"author": "agent", "text": note, "ts": now, "attachments": []})
            self.store.put("request", rid, r)
        self.store.audit("gbox-auto", f"request.{status}", rid, {"note": note[:200], "launch_failure": True})

    def summary(self, rec: dict) -> dict:
        return summarize(self.store, rec)

    def _publish(self, rec: dict):
        """Put the ticket's state where the clients look: the catalog entry and the newest failed job."""
        s = self.summary(rec)
        try:
            self.store.catalog_update(rec["game_id"], launch_report=s | {"mod": rec.get("mod") or ""})
        except Exception:                                        # noqa: BLE001 - a game outside the catalog
            pass
        last = next((o for o in reversed(rec.get("occurrences") or []) if o.get("job_id")), None)
        if last:
            self._stamp_job(last["job_id"], rec)

    def _stamp_job(self, jid: str, rec: dict):
        with self.store.lock:
            j = self.store.get("job", jid)
            if j and j.get("state") not in ("queued", "running"):
                self.store.put("job", jid, j | {"launch_report": self.summary(rec)})

    def index(self) -> dict:
        return index(self.store)

    # ---- remedies ----
    def _relaunch_blocker(self, rec: dict, facts: dict, job: dict) -> str | None:
        if not self.settings()["auto_remedy"]:
            return "automatic remedies are switched off"
        if facts["tool"] != "launch_game":
            return "a swap is not repeated automatically: it would replace the running game"
        age = self.h.now() - (facts.get("finished") or 0)
        if age > RELAUNCH_MAX_AGE_S:
            return f"the failure is {int(age // 60)} min old; the operator may have moved on"
        wid = self._resolve_worker_id(facts["worker_id"])
        w = self._worker(wid)
        if not w.get("online"):
            return f"{facts['worker']} is offline"
        running = self._running_on(wid)
        if running:
            return (f"{running[0].get('title') or running[0].get('session_id')} is running on {facts['worker']}; "
                    "a relaunch would close it")
        recent = [r for r in rec.get("remedies") or [] if r.get("job_id") and r.get("action") == "relaunch"
                  and self.h.now() - r.get("ts", 0) < RELAUNCH_COOLDOWN_S]
        if recent:
            return f"already relaunched automatically {int((self.h.now() - recent[-1]['ts']) // 60)} min ago"
        try:
            with self.store.lock:
                newer = self.store.db.execute(
                    "SELECT COUNT(*) FROM docs WHERE kind='job' AND json_extract(body,'$.tool') IN ('launch_game','session_swap') "
                    "AND COALESCE(json_extract(body,'$.created'),0) > ? AND json_extract(body,'$.id') != ? "
                    "AND (json_extract(body,'$.worker_id')=? OR json_extract(body,'$.require_worker')=? "
                    "OR json_extract(body,'$.input.game.game_id')=? OR json_extract(body,'$.input.game_id')=?)",
                    (job.get("created") or 0, job.get("id") or "", wid, wid,
                     facts["game_id"], facts["game_id"])).fetchone()[0]
        except AttributeError:
            newer = 0
        if newer:
            return "another launch started on that PC or for this game since"
        return None

    def _wait_job(self, jid: str, timeout: float) -> dict:
        deadline = self.h.now() + timeout
        while True:
            j = self.store.get("job", jid) or {}
            if j.get("state") not in ("queued", "running") or self.h.now() >= deadline:
                return j
            self.h.sleep(1.0)

    def _remedy(self, sig: str, facts: dict, c: dict, job: dict):
        rec = self.store.get(KIND, sig)
        if not rec or c["remedy"] == "none" or not self.h.submit_job or not self.settings()["auto_remedy"]:
            return                                               # the ticket body already says why
        tried = []
        try:
            wid = self._resolve_worker_id(facts["worker_id"])
            if c["remedy"] == "restage_mod" and facts["mod"] and facts.get("game"):
                w = self._worker(wid)
                if not w.get("online"):
                    self._remedy_note(sig, "re-stage the mod", f"{facts['worker']} is offline; not re-staged", "skipped")
                    return
                pj = self.h.submit_job("prepare_mod", {"game": facts["game"], "mod": facts["mod"]}, wid)
                self._mark_remedy(pj["id"], sig)
                done = self._wait_job(pj["id"], 1800)
                ok = done.get("state") == "succeeded"
                tried.append(f"re-staged {facts['mod']} on {facts['worker']} (prepare_mod job {pj['id']}): "
                             + ("ready" if ok else f"failed: {str(done.get('error') or done.get('state'))[:300]}"))
                self._remedy_note(sig, "re-stage the mod", tried[-1], "finished" if ok else "failed", job_id=pj["id"])
                if not ok:
                    return
            why = self._relaunch_blocker(self.store.get(KIND, sig) or rec, facts, job)
            if why:
                self._remedy_note(sig, "relaunch", f"Not relaunched: {why}.", "skipped")
                return
            inp = dict(job.get("input") or {})
            boot = None
            if c["remedy"] == "relaunch_long_boot":
                secs = float((c.get("detail") or {}).get("secs") or 30)
                boot = max(LONG_BOOT_S, 3 * secs)
                inp["boot_timeout_s"] = boot
            nj = self.h.submit_job("launch_game", inp, wid)
            self._mark_remedy(nj["id"], sig)
            self._remedy_note(sig, "relaunch", f"Relaunching on {facts['worker']}"
                              + (f" with a {int(boot)} s boot timeout" if boot else "") + f" (job {nj['id']}).",
                              "running", job_id=nj["id"])
            done = self._wait_job(nj["id"], 900)
            if done.get("state") == "succeeded":
                sid = (done.get("output") or {}).get("session_id") or ""
                self._remedy_note(sig, "relaunch result",
                                  f"The relaunch worked (session {sid})"
                                  + (f": this game needs more than the default boot timeout on {facts['worker']}" if boot else "")
                                  + ". The investigation continues for a permanent fix.", "finished", job_id=nj["id"])
            else:
                self._remedy_note(sig, "relaunch result", "The relaunch failed too: "
                                  + str(done.get("error") or done.get("state") or "no result")[:800], "failed",
                                  job_id=nj["id"])
        except Exception as exc:                                 # noqa: BLE001 - the ticket keeps the attempt
            self._remedy_note(sig, "automatic remedy", f"Remedy could not run: {type(exc).__name__}: {exc}", "failed")

    def _mark_remedy(self, jid: str, sig: str):
        self.store.put(JOB_KIND, jid, {"id": jid, "remedy_for": sig, "ts": self.h.now()})

    def _remedy_note(self, sig: str, action: str, text: str, status: str, job_id: str = ""):
        with self.lock:
            rec = self.store.get(KIND, sig)
            if not rec:
                return
            rec.setdefault("remedies", []).append({"ts": self.h.now(), "action": action, "result": text[:800],
                                                   "status": status, "job_id": job_id})
            self.store.put(KIND, sig, rec)
        self._message(rec["request_id"], f"Automatic remedy ({action}): {text}", action="automatic remedy: " + action,
                      result=text, status=status)

    # ---- investigation ----
    def task(self, rec: dict) -> str:
        req = self.store.get("request", rec["request_id"]) or {}
        return (f"Launch failure report #{rec.get('number')} (request_id={rec['request_id']}): {req.get('title') or rec['label']}. "
                f"Failure class {rec['error_class'].split(':')[0]}: {rec['diagnosis']} It happened {rec.get('count', 1)} "
                f"time(s); game_id={rec['game_id']}, mod={rec.get('mod') or '(stock)'}, emulator {rec['adapter']}. "
                "Read get_request first: the error, logs (attached emulator-log.txt, job-progress.txt, worker.log), "
                "timings, staging and the automatic remedy results are on the ticket. Find the root cause, fix it in "
                "gBox code (adapters, tools, filemods, the swap path...) with a focused test, and publish it with "
                "publish_task_changes (a draft PR). Include screenshots of the game loading after the fix "
                "(evidence_capture with this game_id and mod on an idle node) in the PR. Never stop, pause or replace "
                "a game the operator is playing; reproduce only on an idle node in an agent-owned test session. Leave "
                "the ticket in_progress when the PR is up: the control plane verifies the fix with a launch of the same "
                "game and mod after the PR merges and deploys, and closes or reopens the ticket itself.")

    def _investigate(self, sig: str, reopened: bool = False):
        rec = self.store.get(KIND, sig)
        if not rec:
            return
        rid = rec["request_id"]
        if not self.settings()["investigate"] or not self.h.investigate:
            self._message(rid, "Investigation not queued: automatic investigation is switched off.",
                          action="queue investigation", result="switched off", status="skipped")
            return
        attempt = ((rec.get("hermes") or {}).get("attempt") or 0) + 1
        try:
            out = self.h.investigate(rid, rec.get("number") or 0, self.task(rec), attempt) or {}
        except Exception as exc:                                 # noqa: BLE001 - the work queue picks open tickets up later
            self._message(rid, f"Hermes investigation could not be queued now: {exc}. The ticket stays open; the Hermes "
                               "work queue picks up open launch-failure tickets on its next pass.",
                          action="queue investigation", result=str(exc)[:500], status="failed")
            return
        with self.lock:
            rec = self.store.get(KIND, sig) or rec
            rec["hermes"] = {"queued_at": self.h.now(), "mode": out.get("mode"), "job_id": out.get("job_id"),
                             "priority": out.get("priority"), "attempt": attempt}
            self.store.put(KIND, sig, rec)
        where = (f"Hermes job {out['job_id']}" if out.get("job_id") else
                 f"the Hermes work queue at priority {int(out.get('priority') or 0) + 1}")
        self._set_status(rid, "in_progress")
        self._message(rid, ("Reopened: " if reopened else "") + f"Investigation queued in {where}: find the cause, fix it "
                      "in code and publish a draft PR with screenshots. The control plane verifies the fix after the PR "
                      "merges and deploys.", action="queue investigation", result=out.get("job_id") or "queued",
                      status="running")
        self._publish(rec)

    # ---- verify and resolve ----
    def merged_pr(self, req: dict, since: float = 0) -> dict | None:
        """The newest 'PR #N merged to main as <sha>' reply (hermes_merges.reconcile) posted after `since`."""
        best = None
        for m in req.get("messages") or []:
            if (m.get("ts") or 0) < since:
                continue
            for hit in re.finditer(r"PR #(\d+) merged to (\S+) as ([0-9a-f]{7,40})", m.get("text") or ""):
                best = {"number": int(hit[1]), "base": hit[2], "sha": hit[3], "ts": m.get("ts") or 0}
        return best

    def operator_success(self, rec: dict) -> dict | None:
        """An operator session of the same game and mod, started after the last failure, that kept running."""
        now = self.h.now()
        for s in sorted(self._sessions(game_id=rec["game_id"]), key=lambda s: -(s.get("started") or 0)):
            if (s.get("started") or 0) <= (rec.get("last_seen") or 0):
                continue
            if (s.get("collection_mod") or s.get("mod") or "") != (rec.get("mod") or ""):
                continue
            lab = self.store.get("slabel", s.get("session_id") or "") or {}
            if lab.get("owner") == "agent" or str(lab.get("label") or "").startswith(("Evidence capture", "Launch verification")):
                continue
            end = s.get("ended") if s.get("state") == "ended" else now
            if end and end - (s.get("started") or end) >= SUCCESS_RUN_S:
                ex = s.get("exit")
                if isinstance(ex, dict) and ex.get("returncode") not in (None, 0) and not ex.get("via"):
                    continue
                return s
        return None

    def _verify_node(self, rec: dict) -> str:
        """The failing PC when it is idle (so the fix is proven where it failed), else any idle node."""
        w = self._worker(rec.get("worker_id") or "")
        if (w.get("online") and w.get("background_testing") is not False and not self._running_on(w.get("id") or "")
                and (w.get("os") != "windows" or (w.get("idle_seconds") or 0) >= 300)):
            return w.get("name") or w.get("id")
        return "auto"

    def close_verified(self, sig: str, how: str, text: str, frame: str | None = None, **extra):
        with self.lock:
            rec = self.store.get(KIND, sig)
            if not rec:
                return
            rec.update(state="verified", verified={"ts": self.h.now(), "how": how, "frame": frame, **extra})
            self.store.put(KIND, sig, rec)
        att = []
        if frame:
            meta = self.store.get("artifact", frame) or {}
            att = [{"sha256": frame, "name": meta.get("name") or "verification.png", "type": "image/png",
                    "size": meta.get("size")}]
        self._message(rec["request_id"], text, att, action="verify launch", result=how, status="finished")
        self._set_status(rec["request_id"], "done")
        try:
            self.h.unprioritize(rec["request_id"])
        except Exception:                                        # noqa: BLE001
            pass
        self._publish(rec)
        self.store.audit("gbox-auto", "launch_failure.verified", rec["request_id"], {"signature": sig, "how": how})

    def _reopen(self, sig: str, text: str, attachments=()):
        with self.lock:
            rec = self.store.get(KIND, sig)
            rec.update(state="investigating", reopened=self.h.now(), pr=None, verify=None,
                       reopen_count=rec.get("reopen_count", 0) + 1)
            self.store.put(KIND, sig, rec)
        self._message(rec["request_id"], text, attachments, action="verify launch", result="failed", status="failed")
        self._set_status(rec["request_id"], "open")
        self._publish(rec)
        self._investigate(sig, reopened=True)

    def tick(self) -> list[dict]:
        """One pass of the verify-and-resolve loop over every unverified ticket. Returns what changed."""
        changes = []
        for rec in self.store.all(KIND):
            if rec.get("state") == "verified":
                continue
            try:
                c = self._tick_one(rec)
            except Exception as exc:                             # noqa: BLE001 - one ticket never stops the others
                c = {"error": f"{type(exc).__name__}: {exc}"}
            if c:
                changes.append({"signature": rec["id"], "number": rec.get("number")} | c)
        return changes

    def _tick_one(self, rec: dict) -> dict | None:
        sig, rid, now = rec["id"], rec["request_id"], self.h.now()
        req = self.store.get("request", rid)
        if not req:
            return None
        h = rec.get("hermes") or {}
        if h.get("mode") == "queue" and not h.get("job_id"):
            jid = self.h.queue_job_of(rid)
            if jid:
                with self.lock:
                    cur = self.store.get(KIND, sig)
                    cur["hermes"] = h | {"job_id": jid, "dispatched_at": now}
                    self.store.put(KIND, sig, cur)
                    rec = cur
                self._message(rid, f"Hermes work queue dispatched job {jid} for this ticket.",
                              action="queue investigation", result=jid, status="running")
        if self.settings()["verify"]:
            s = self.operator_success(rec)
            if s:
                run = int(((s.get("ended") if s.get("state") == "ended" else now) or now) - (s.get("started") or now))
                frame = self._session_frame(s.get("session_id") or "")
                self.close_verified(sig, "operator launch",
                                    f"Verified: {rec['title']}" + (f" ({rec['mod']})" if rec.get("mod") else "")
                                    + f" launched successfully since the failure (session {s.get('session_id')}, "
                                    f"ran {run} s). Closing.", frame, session_id=s.get("session_id"))
                return {"verified": "operator launch"}
        state = rec.get("state")
        if state == "investigating":
            pr = self.merged_pr(req, since=rec.get("reopened") or 0)
            if pr:
                with self.lock:
                    cur = self.store.get(KIND, sig)
                    cur.update(state="merged", pr=pr)
                    self.store.put(KIND, sig, cur)
                self._message(rid, f"PR #{pr['number']} ({pr['sha']}) merged: verifying once the deploy carries it.",
                              action="verify launch", result="waiting for deploy", status="running")
                return {"state": "merged", "pr": pr["number"]}
            return None
        if state == "merged":
            pr = rec.get("pr") or {}
            inside = self.h.deploy_contains(pr.get("sha") or "")
            if inside is None and now - (pr.get("ts") or now) >= UNKNOWN_DEPLOY_GRACE_S:
                inside = True
            if inside:
                with self.lock:
                    cur = self.store.get(KIND, sig)
                    cur.update(state="awaiting_verify", verify={"retry_at": 0, "attempts": 0})
                    self.store.put(KIND, sig, cur)
                return {"state": "awaiting_verify"}
            return None
        if not self.settings()["verify"] or not self.h.verify_launch:
            return None
        if state == "awaiting_verify":
            v = rec.get("verify") or {}
            if now < (v.get("retry_at") or 0):
                return None
            node = self._verify_node(rec)
            try:
                job = self.h.verify_launch(rec, node)
            except Exception as exc:                             # noqa: BLE001 - busy capture / no idle node: later
                with self.lock:
                    cur = self.store.get(KIND, sig)
                    cur["verify"] = v | {"retry_at": now + VERIFY_RETRY_S, "last_error": str(exc)[:300]}
                    self.store.put(KIND, sig, cur)
                return {"verify": "deferred", "why": str(exc)[:200]}
            with self.lock:
                cur = self.store.get(KIND, sig)
                cur.update(state="verifying", verify=v | {"job_id": job["id"], "started": now, "node": node,
                                                         "attempts": (v.get("attempts") or 0) + 1})
                self.store.put(KIND, sig, cur)
            self._message(rid, f"Verification launch of {rec['title']} ({rec.get('mod') or 'stock'}) started on "
                               f"{'an idle node' if node == 'auto' else node} in an agent-owned test session "
                               f"(evidence_capture job {job['id']}).", action="verify launch", result=job["id"], status="running")
            return {"state": "verifying", "job": job["id"]}
        if state == "verifying":
            v = rec.get("verify") or {}
            job = self.store.get("job", v.get("job_id") or "") or {}
            if job.get("state") in ("queued", "running"):
                return None
            out = job.get("output") or {}
            frames = [f for f in out.get("frames") or [] if f.get("sha256")]
            good = [f for f in frames if not f.get("dark")]
            if job.get("state") == "succeeded" and good:
                self.close_verified(sig, "verification launch",
                                    f"Verified: {rec['title']} ({rec.get('mod') or 'stock'}) loaded and showed gameplay "
                                    f"on {out.get('worker') or v.get('node')} (evidence_capture job {job.get('id')}); the "
                                    "test session was stopped. Closing.", good[-1]["sha256"], job_id=job.get("id"))
                return {"verified": "verification launch"}
            err = str(job.get("error") or ("only black frames" if frames else job.get("state") or "no result"))
            if job.get("state") != "succeeded" and TRANSIENT_VERIFY_RX.search(err) and "no frame was captured" not in err:
                with self.lock:
                    cur = self.store.get(KIND, sig)
                    cur.update(state="awaiting_verify", verify=v | {"retry_at": now + VERIFY_RETRY_S, "last_error": err[:300]})
                    self.store.put(KIND, sig, cur)
                return {"verify": "retry", "why": err[:200]}
            atts = [{"sha256": f["sha256"], "name": f"verification-{i}.png", "type": "image/png"} for i, f in enumerate(frames[:3])]
            self._reopen(sig, f"Verification failed after PR #{(rec.get('pr') or {}).get('number')}: {err[:1200]}", atts)
            return {"state": "reopened", "why": err[:200]}
        return None

    def _session_frame(self, sid: str) -> str | None:
        try:
            png = self.h.last_frame(sid)
        except Exception:                                        # noqa: BLE001
            png = None
        if not png:
            return None
        return self.store.put_artifact(png, f"verified-{sid[-8:]}.png", "image/png",
                                       {"session": sid, "launch_failure": True}).sha256

    # ---- scanning ----
    def candidates(self, since: float) -> list[dict]:
        """Failed launch / swap jobs that finished after `since`, oldest first."""
        marks = ",".join("?" for _ in FAILED_STATES)
        try:
            with self.store.lock:
                rows = self.store.db.execute(          # the job-state index (Store.jobs) keeps the per-minute scan cheap
                    "SELECT body FROM docs INDEXED BY docs_queued_jobs WHERE kind='job' "
                    f"AND json_extract(body,'$.state') IN ({marks}) "
                    "AND json_extract(body,'$.tool') IN ('launch_game','session_swap') "
                    "AND COALESCE(json_extract(body,'$.finished'),json_extract(body,'$.created'),0) >= ? ORDER BY rowid",
                    (*FAILED_STATES, since)).fetchall()
            return [json.loads(r[0]) for r in rows]
        except AttributeError:
            return [j for j in self.store.all("job") if j.get("tool") in LAUNCH_TOOLS and j.get("state") in FAILED_STATES
                    and (j.get("finished") or j.get("created") or 0) >= since]

    def scan(self, since: float, *, source: str = "scan", remedy: bool = False) -> dict:
        filed, updated, skipped = [], [], {}
        for job in self.candidates(since):
            if self.store.get(JOB_KIND, job.get("id") or ""):
                continue
            before = {r["id"]: r.get("count", 0) for r in self.store.all(KIND)}
            rec = self.observe_job(job, source=source, remedy=remedy)
            if rec is None:
                why = (self.store.get(JOB_KIND, job.get("id") or "") or {}).get("skipped") or "skipped"
                skipped[why] = skipped.get(why, 0) + 1
            elif rec["id"] in before:
                updated.append(rec.get("number"))
            else:
                filed.append(rec.get("number"))
        return {"filed": filed, "updated": sorted(set(n for n in updated if n not in filed)), "skipped": skipped}

    def backfill(self, days: float = 7.0) -> dict:
        """File the failed launches of the last `days` days (grouped by signature) the same way as live ones."""
        out = self.scan(self.h.now() - days * 86400, source="backfill", remedy=False)
        return out | {"days": days}

    def preview(self, days: float = 7.0) -> dict:
        """What backfill would file, without filing: {signature: {title, count, jobs}}."""
        groups = {}
        for job in self.candidates(self.h.now() - days * 86400):
            if self.store.get(JOB_KIND, job.get("id") or "") or self.skip_reason(job):
                continue
            f = self.facts_from_job(job)
            if not f["game_id"]:
                continue
            c = classify(f["error"], adapter=f["adapter"])
            sig = signature(f["game_id"], f["mod"], f["adapter"], c["cls"])
            g = groups.setdefault(sig, {"title": self._title(f, c), "count": 0, "jobs": [],
                                        "existing": bool(self.store.get(KIND, sig))})
            g["count"] += 1
            g["jobs"].append(job.get("id"))
        return groups
