"""Pause the operator's local ComfyUI while it renders during a MercMode game on this host - and only then.

The Spark (lilspark) is an NVIDIA GB10 Grace-Blackwell board: a single GPU with unified memory. The emulators
(Dolphin, Citron) draw through the graphics pipeline while ComfyUI/torch runs CUDA compute on the *same* SMs and
the same LPDDR5X bandwidth, so a render in flight starves the game of frame time. The operator accepts pausing
ComfyUI during play ("games at full speed on the Spark while Comfy still renders in the gaps",
system/docs/pine-radio-gbox-resource-handoff.md).

Freeze only during renders (the operator, 2026-11-10, through Pine Box: with MercMode playing round after round the
old rule - SIGSTOP for every launching/starting/playing phase - left :8188 frozen almost all the time, so Pine's
"ask for an image" never got an answer). Now, while a MercMode run on THIS host is launching/starting/playing:
  - ComfyUI with nothing in its queue stays running (an idle server costs the game nothing; the PiP menu sees it);
  - ComfyUI with a prompt running or pending (GET <url>/queue: queue_running / queue_pending), or one that misses
    QUEUE_TIMEOUT_S on SLOW_READS reads in a row (assumed busy), is SIGSTOPped. The render pauses and finishes in
    the gaps.
  - the queue is read on every scheduler tick and every WATCH_S by start()'s watcher, so a prompt submitted
    mid-round is stopped within seconds.
In the gaps (round end, warm-park, title rotation, MercMode off) a paused ComfyUI is SIGCONTed, and stays awake.

The coordinator's state (paused, pid, since, why, the game's title / phase, stops) is published in STATE_FILE under
gbox-data (state_path) and in status(), so Pine can say "paused by gBox, the render finishes at the next gap".

Design rules:
- Reversible & fail-soft: every signal and probe is wrapped; any failure is logged and never raised into the
  scheduler, so a missing or unsignalable ComfyUI can never block, delay or break a game.
- Always resumed: release() (called on disable and on server shutdown) always leaves ComfyUI running, so the process
  is never stranded SIGSTOPped.
- Resumed outside gBox (someone SIGCONTed it): the next active tick sees the process running again, forgets its own
  pause and decides from the queue like any other tick.
- This host only: it signals a process on this machine, and only when the ComfyUI URL is loopback. SIGSTOP/SIGCONT
  are POSIX-only, so Windows workers (JAYBUILTFINALE, i9-NUC) are inert even if the flag were set there.
"""
from __future__ import annotations

import json
import os
import signal
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

# The phases in which the game process is (or is about to be) rendering and must own the GPU. Everything else
# (parked at a results screen, a warm/ready paused title, an ended run, or no run at all) is a gap where ComfyUI runs.
ACTIVE_PHASES = ("launching", "starting", "playing")

# Real POSIX signals where available; harmless sentinels elsewhere so the logic stays unit-testable on any OS.
STOP = getattr(signal, "SIGSTOP", "SIGSTOP")
CONT = getattr(signal, "SIGCONT", "SIGCONT")

QUEUE_TIMEOUT_S = 1.5          # an idle ComfyUI answers /queue in milliseconds; no answer in this long = assumed busy
WATCH_S = 2.0                  # start()'s watcher: the queue read this often while a game plays and ComfyUI runs
STATE_FILE = "comfy-coordinator.json"
HEARTBEAT_S = 30.0             # the state file is rewritten on every change, and at least this often while it ticks
SLOW_READS = 2                 # "slow" pauses only on this many reads in a row (one slow answer on a busy CPU is not a
                               # render; a server that keeps missing the timeout is assumed to be rendering)

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def game_active(run: dict | None) -> bool:
    """True when the host's current MercMode/screensaver run is driving the GPU (a game needs full frame time)."""
    return bool(run) and run.get("phase") in ACTIVE_PHASES


def is_loopback(url: str) -> bool:
    """We only ever signal a ComfyUI that is on this machine; a remote URL means hands off."""
    host = urlparse(url if "://" in (url or "") else f"//{url}").hostname
    return (host or "localhost") in _LOOPBACK_HOSTS


def _port(url: str, default: int = 8188) -> int:
    try:
        parsed = urlparse(url if "://" in (url or "") else f"//{url}").port
        return int(parsed) if parsed else default
    except (ValueError, TypeError):
        return default


def queue_state(url: str, timeout: float = QUEUE_TIMEOUT_S) -> dict:
    """ComfyUI's queue: {"state": "busy" | "idle" | "down" | "slow", "running": n, "pending": n}.
    busy = a prompt running or pending; idle = answered with an empty queue; down = nothing listening (or an error
    that is not a timeout); slow = no answer within timeout (an idle server answers at once, so: assumed rendering)."""
    base = (url if "://" in (url or "") else f"http://{url or '127.0.0.1:8188'}").rstrip("/")
    try:
        with urllib.request.urlopen(base + "/queue", timeout=timeout) as resp:   # noqa: S310 - loopback only
            body = json.loads(resp.read(1 << 20) or b"{}")
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return {"state": "slow", "running": None, "pending": None}
        return {"state": "down", "running": None, "pending": None}
    except (socket.timeout, TimeoutError):
        return {"state": "slow", "running": None, "pending": None}
    except Exception:                                        # noqa: BLE001 - a reset, a bad body: it is not rendering
        return {"state": "down", "running": None, "pending": None}
    if not isinstance(body, dict):
        return {"state": "idle", "running": 0, "pending": 0}
    running, pending = body.get("queue_running") or [], body.get("queue_pending") or []
    n_run = len(running) if isinstance(running, list) else 1
    n_pend = len(pending) if isinstance(pending, list) else 1
    return {"state": "busy" if n_run or n_pend else "idle", "running": n_run, "pending": n_pend}


def _normal_queue(q) -> dict:
    if isinstance(q, dict):
        return {"state": q.get("state") or "down", "running": q.get("running"), "pending": q.get("pending")}
    return {"state": str(q or "down"), "running": None, "pending": None}


def process_stopped(pid: int | None):
    """True when the process is in job-control stop (state T), False when it runs, None when that cannot be read."""
    if not pid:
        return None
    try:
        import psutil
        return psutil.Process(pid).status() == psutil.STATUS_STOPPED
    except Exception:                                        # noqa: BLE001 - psutil missing / the process gone
        return None


def find_comfy_pid(url: str) -> int | None:
    """The local ComfyUI server's PID: the process listening on its port, else a python 'ComfyUI'/'comfy main.py'."""
    try:
        import psutil
    except Exception:                                        # noqa: BLE001 - psutil missing: give up quietly
        return None
    port = _port(url)
    own = os.getpid()
    try:
        for conn in psutil.net_connections(kind="inet"):
            laddr = conn.laddr
            if laddr and getattr(laddr, "port", None) == port and conn.status == psutil.CONN_LISTEN \
                    and conn.pid and conn.pid != own:
                return conn.pid
    except Exception:                                        # noqa: BLE001 - permissions / races: fall through
        pass
    try:
        for proc in psutil.process_iter(["pid", "cmdline"]):
            if proc.info["pid"] == own:
                continue
            cmd = " ".join(proc.info.get("cmdline") or []).lower()
            if "comfyui" in cmd or ("comfy" in cmd and "main.py" in cmd):
                return proc.info["pid"]
    except Exception:                                        # noqa: BLE001
        pass
    return None


class ComfyCoordinator:
    """Idempotent SIGSTOP/SIGCONT of the local ComfyUI: stopped while a game renders here AND ComfyUI has work."""

    def __init__(self, url: str, enabled: bool, *, log=print, find=None, kill=None, queue=None, stopped=None,
                 state_path=None, clock=time.time):
        self.url = url or ""
        self.enabled = bool(enabled)
        self._log = log
        self._find = find if find is not None else (lambda: find_comfy_pid(self.url))
        self._kill = kill if kill is not None else os.kill
        self._queue = queue if queue is not None else (lambda: queue_state(self.url))
        self._stopped = stopped if stopped is not None else process_stopped
        self._clock = clock
        # POSIX job-control signals, or an injected killer (tests) on an OS without them.
        self.supported = kill is not None or (hasattr(signal, "SIGSTOP") and hasattr(signal, "SIGCONT"))
        self.lock = threading.RLock()
        self.paused = False            # did WE stop it (so WE must resume it)?
        self.pid: int | None = None
        self.stops = 0
        self.conts = 0
        self.probes = 0
        self.outside_resumes = 0       # times it was found running again while we held it paused
        self.note = "idle"
        self.since: float | None = None  # when the current pause began
        self.why = ""                  # why it is paused now
        self.active = False            # the last sync's verdict: a game renders here
        self.context: dict = {}        # the run behind it (title / phase / warming)
        self.queue: dict | None = None # the last /queue read
        self._slow = 0                 # "slow" /queue reads in a row
        self.state_path = Path(state_path) if state_path else None
        self._published: tuple[dict | None, float] = (None, 0.0)
        self._watch_stop = threading.Event()
        self._kick = threading.Event()
        self._watcher: threading.Thread | None = None

    # --- internal helpers -------------------------------------------------
    def _signal(self, pid: int, sig) -> bool:
        try:
            self._kill(pid, sig)
            return True
        except ProcessLookupError:
            return False
        except Exception as exc:                             # noqa: BLE001 - never let a signal error reach the tick
            self._log(f"comfy-coordinator: signal {sig} -> pid {pid} failed: {type(exc).__name__}: {exc}", flush=True)
            return False

    def _alive(self, pid: int | None) -> bool:
        if not pid:
            return False
        try:
            self._kill(pid, 0)
            return True
        except Exception:                                    # noqa: BLE001 - dead, gone, or not signalable
            return False

    def _game(self) -> str:
        title = self.context.get("title")
        return f"{title} ({self.context.get('phase') or 'warming'})" if title else "a game boot"

    def _pause_locked(self, q: dict) -> None:
        pid = self._find()
        if not pid:
            self.note = "no ComfyUI to pause"
            return                                           # not running: nothing to do (fail-soft)
        if self._signal(pid, STOP):
            self.pid, self.paused, self.stops = pid, True, self.stops + 1
            self.since = self._clock()
            work = ("no answer from /queue in time (assumed rendering)" if q["state"] == "slow" else
                    f"a render in its queue ({q.get('running') or 0} running, {q.get('pending') or 0} pending)")
            self.why = f"{work} while {self._game()} plays here; it finishes at the next gap"
            self.note = f"paused pid {pid} (render during play)"
            self._log(f"comfy-coordinator: SIGSTOP ComfyUI pid={pid} ({work}; game active on this host)", flush=True)

    def _decide_active_locked(self) -> None:
        if self.paused and not self._alive(self.pid):
            self.paused, self.pid, self.since, self.why = False, None, None, ""  # our process died: decide afresh
        if self.paused and self._stopped(self.pid) is False:  # SIGCONTed outside gBox: forget our pause, re-check
            self.outside_resumes += 1
            self._log(f"comfy-coordinator: ComfyUI pid={self.pid} was resumed outside gBox; re-checking its queue",
                      flush=True)
            self.paused, self.pid, self.since, self.why = False, None, None, ""
        if self.paused:
            return                                           # held until the gap (a stopped server cannot answer)
        q = self.queue = _normal_queue(self._queue())
        self.probes += 1
        self._slow = self._slow + 1 if q["state"] == "slow" else 0
        if q["state"] == "busy" or self._slow >= SLOW_READS:
            self._pause_locked(q)
        elif q["state"] == "slow":
            self.note = f"/queue slow to answer ({self._slow} of {SLOW_READS} reads before it counts as rendering)"
        else:
            self.note = ("ComfyUI idle: left running during the game" if q["state"] == "idle"
                         else "no ComfyUI answering: nothing to pause")

    def _publish_locked(self, force: bool = False) -> None:
        if self.state_path is None:
            return
        try:
            body = self.status()
            last, at = self._published
            now = self._clock()
            if not force and body == last and now - at < HEARTBEAT_S:
                return
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_name(self.state_path.name + ".tmp")
            tmp.write_text(json.dumps({**body, "updated_at": round(now, 2)}, indent=1), encoding="utf-8")
            os.replace(tmp, self.state_path)
            self._published = (body, now)
        except Exception as exc:                             # noqa: BLE001 - the state file is a courtesy
            self._log(f"comfy-coordinator: state file failed: {type(exc).__name__}: {exc}", flush=True)

    # --- public API -------------------------------------------------------
    def sync(self, active: bool, context: dict | None = None, probe: bool | None = None) -> None:
        """Pause ComfyUI while a game renders here and ComfyUI has work; resume it in the gaps. Idempotent, never
        raises. context: the run behind the verdict ({title, phase, warming}) for the published state. probe: read
        the queue in this call; None = only when no watcher runs (with one, the scheduler tick never waits on HTTP:
        the watcher is woken and reads it at once on its own thread)."""
        if not self.supported or not is_loopback(self.url):
            return
        try:
            with self.lock:
                self.active = bool(active)
                if context is not None:
                    self.context = {k: v for k, v in dict(context).items() if v is not None}
                if not self.enabled:                         # turned off at runtime: never strand a paused process
                    if self.paused:
                        self._resume_locked("disabled")
                elif active:
                    if probe or (probe is None and self._watcher is None):
                        self._decide_active_locked()
                    elif not self.paused:
                        self._kick.set()                     # the watcher reads the queue now, off the tick
                elif self.paused:
                    self._resume_locked("gap")
                self._publish_locked()
        except Exception as exc:                             # noqa: BLE001 - the scheduler tick must survive anything
            self._log(f"comfy-coordinator: sync failed: {type(exc).__name__}: {exc}", flush=True)

    def watch_once(self) -> None:
        """The watcher's step: while a game renders here and ComfyUI runs, read its queue again (a prompt submitted
        mid-round is paused within WATCH_S, not at the next 30 s scheduler tick)."""
        with self.lock:
            due = self.enabled and self.active
        if due:
            self.sync(True, probe=True)

    def start(self, interval: float = WATCH_S) -> None:
        """Start the watcher thread (once). release() stops it."""
        if self._watcher is not None or not self.supported or not is_loopback(self.url):
            return

        def loop():
            while not self._watch_stop.is_set():
                self._kick.wait(interval)                    # every interval, or at once when a tick turns active
                self._kick.clear()
                if self._watch_stop.is_set():
                    break
                try:
                    self.watch_once()
                except Exception as exc:                     # noqa: BLE001
                    self._log(f"comfy-coordinator: watch failed: {type(exc).__name__}: {exc}", flush=True)

        self._watcher = threading.Thread(target=loop, daemon=True, name="comfy-coordinator-watch")
        self._watcher.start()

    def _resume_locked(self, why: str) -> None:
        pid = self.pid
        if pid and self._signal(pid, CONT):
            self.conts += 1
            self.note = f"resumed pid {pid} ({why})"
            self._log(f"comfy-coordinator: SIGCONT ComfyUI pid={pid} ({why})", flush=True)
        self.paused, self.pid, self.since, self.why = False, None, None, ""

    def release(self) -> None:
        """Always leave ComfyUI running. Called on feature disable and on server shutdown. Never raises."""
        self._watch_stop.set()
        self._kick.set()
        try:
            with self.lock:
                if self.paused:
                    self._resume_locked("release")
                self.active = False
                self._publish_locked(force=True)
        except Exception as exc:                             # noqa: BLE001
            self._log(f"comfy-coordinator: release failed: {type(exc).__name__}: {exc}", flush=True)

    def status(self) -> dict:
        """Telemetry for the MercMode panel / API / Pine's PiP menu: whether it is paused, since when and why."""
        return {"enabled": self.enabled, "supported": self.supported, "loopback": is_loopback(self.url),
                "url": self.url, "paused": self.paused, "pid": self.pid,
                "since": round(self.since, 2) if self.since else None, "why": self.why,
                "game_active": self.active, "game": dict(self.context), "queue": self.queue,
                "rule": "paused only while a game renders here AND ComfyUI has work; resumed at every gap",
                "stops": self.stops, "conts": self.conts, "probes": self.probes,
                "outside_resumes": self.outside_resumes, "note": self.note}
