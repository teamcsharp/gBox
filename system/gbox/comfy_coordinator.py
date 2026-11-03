"""Pause the operator's local ComfyUI while a MercMode game actively renders on this host.

The Spark (lilspark) is an NVIDIA GB10 Grace-Blackwell board: a single GPU with unified memory. The emulators
(Dolphin, Citron) draw through the graphics pipeline while ComfyUI/torch runs CUDA compute on the *same* SMs and
the same LPDDR5X bandwidth, so a render in flight starves the game of frame time. The operator accepts pausing
ComfyUI during play ("games at full speed on the Spark while Comfy still renders in the gaps",
system/docs/pine-radio-gbox-resource-handoff.md).

This coordinator is driven by the autoplay/MercMode scheduler tick (gbox.screensaver.Screensaver.tick, which also
runs on every MercMode transition via nudge()). When a MercMode run on THIS host is launching/starting/playing we
SIGSTOP the local ComfyUI server; in the gaps (round end, warm-park, title rotation, MercMode off) we SIGCONT it.

Design rules:
- Reversible & fail-soft: every signal is wrapped; any failure is logged and never raised into the scheduler, so a
  missing or unsignalable ComfyUI can never block, delay or break a game.
- Always resumed: release() (called on disable and on server shutdown) always leaves ComfyUI running, so the process
  is never stranded SIGSTOPped.
- This host only: it signals a process on this machine, and only when the ComfyUI URL is loopback. SIGSTOP/SIGCONT
  are POSIX-only, so Windows workers (JAYBUILTFINALE, i9-NUC) are inert even if the flag were set there.
"""
from __future__ import annotations

import os
import signal
import threading
from urllib.parse import urlparse

# The phases in which the game process is (or is about to be) rendering and must own the GPU. Everything else
# (parked at a results screen, a warm/ready paused title, an ended run, or no run at all) is a gap where ComfyUI runs.
ACTIVE_PHASES = ("launching", "starting", "playing")

# Real POSIX signals where available; harmless sentinels elsewhere so the logic stays unit-testable on any OS.
STOP = getattr(signal, "SIGSTOP", "SIGSTOP")
CONT = getattr(signal, "SIGCONT", "SIGCONT")

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
    """Idempotent SIGSTOP/SIGCONT of the local ComfyUI, keyed off whether a game is rendering on this host."""

    def __init__(self, url: str, enabled: bool, *, log=print, find=None, kill=None):
        self.url = url or ""
        self.enabled = bool(enabled)
        self._log = log
        self._find = find if find is not None else (lambda: find_comfy_pid(self.url))
        self._kill = kill if kill is not None else os.kill
        # POSIX job-control signals, or an injected killer (tests) on an OS without them.
        self.supported = kill is not None or (hasattr(signal, "SIGSTOP") and hasattr(signal, "SIGCONT"))
        self.lock = threading.RLock()
        self.paused = False            # did WE stop it (so WE must resume it)?
        self.pid: int | None = None
        self.stops = 0
        self.conts = 0
        self.note = "idle"

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

    # --- public API -------------------------------------------------------
    def sync(self, active: bool) -> None:
        """Pause ComfyUI while a game renders here; resume it in the gaps. Idempotent and never raises."""
        if not self.supported or not is_loopback(self.url):
            return
        try:
            with self.lock:
                if not self.enabled:                         # turned off at runtime: never strand a paused process
                    if self.paused:
                        self._resume_locked("disabled")
                    return
                if active:
                    if self.paused and not self._alive(self.pid):
                        self.paused, self.pid = False, None  # our process died; re-pause whatever is listening now
                    if not self.paused:
                        pid = self._find()
                        if not pid:
                            self.note = "no ComfyUI to pause"
                            return                            # not running: nothing to do (fail-soft)
                        if self._signal(pid, STOP):
                            self.pid, self.paused, self.stops = pid, True, self.stops + 1
                            self.note = f"paused pid {pid} (game rendering)"
                            self._log(f"comfy-coordinator: SIGSTOP ComfyUI pid={pid} (game active on this host)",
                                      flush=True)
                elif self.paused:
                    self._resume_locked("gap")
        except Exception as exc:                             # noqa: BLE001 - the scheduler tick must survive anything
            self._log(f"comfy-coordinator: sync failed: {type(exc).__name__}: {exc}", flush=True)

    def _resume_locked(self, why: str) -> None:
        pid = self.pid
        if pid and self._signal(pid, CONT):
            self.conts += 1
            self.note = f"resumed pid {pid} ({why})"
            self._log(f"comfy-coordinator: SIGCONT ComfyUI pid={pid} ({why})", flush=True)
        self.paused, self.pid = False, None

    def release(self) -> None:
        """Always leave ComfyUI running. Called on feature disable and on server shutdown. Never raises."""
        try:
            with self.lock:
                if self.paused:
                    self._resume_locked("release")
        except Exception as exc:                             # noqa: BLE001
            self._log(f"comfy-coordinator: release failed: {type(exc).__name__}: {exc}", flush=True)

    def status(self) -> dict:
        """Telemetry for the MercMode panel / API, so the operator can see it pausing and resuming in step."""
        return {"enabled": self.enabled, "supported": self.supported, "loopback": is_loopback(self.url),
                "url": self.url, "paused": self.paused, "pid": self.pid,
                "stops": self.stops, "conts": self.conts, "note": self.note}
