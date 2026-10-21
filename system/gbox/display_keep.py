"""The Windows display stays awake while gBox uses this PC (#1881: the i9-NUC went blank when the operator walked
by; every Cxbx window capture of a sleeping display is black).

The desktop app's background-power module holds the display from Electron under this policy. A worker started by
scripts/standalone.ps1 has no Electron, so the worker holds the display itself: the heartbeat thread reads
/api/background/workers/<name>/status and keeps ES_DISPLAY_REQUIRED while gBox is using the PC (a running job or an
agent-owned game) or while the opted-in PC idles past five minutes (its status display). The operator's own game
releases it; so does the normal power policy when background work is paused. Nothing changes the global settings.
"""
from __future__ import annotations

from .config import HOST_OS

IDLE_S = 300.0
ES_CONTINUOUS, ES_DISPLAY_REQUIRED = 0x80000000, 0x00000002
STATUS_EVERY_S = 30.0


def wanted(status: dict | None, active_jobs: int = 0, host_os: str = HOST_OS) -> tuple[bool, str]:
    """(keep, reason) for a worker's /api/background/workers/<name>/status, the policy background-power.js applies."""
    if host_os != "windows" or not isinstance(status, dict):
        return False, "not a Windows worker, or no status"
    sessions = status.get("sessions") or []
    if any(s.get("agent_owned") is not True for s in sessions):
        return False, "the operator's game runs here"
    if status.get("online") is False:
        return False, "offline"
    working = active_jobs > 0 or bool(status.get("active")) or any(s.get("agent_owned") is True for s in sessions)
    if working:
        return True, "gBox is using this PC"
    idle = (status.get("worker") or {}).get("idle_seconds")
    if status.get("background_testing") is True and isinstance(idle, (int, float)) and idle >= IDLE_S:
        return True, "idle status display"
    return False, "PC active, or background work paused"


def _kernel32_setter():
    if HOST_OS != "windows":
        return None
    import ctypes
    return ctypes.windll.kernel32.SetThreadExecutionState


class Keeper:
    """Holds ES_DISPLAY_REQUIRED from one thread (the state is per thread); release restores the normal policy."""

    def __init__(self, setter=None):
        self._set = setter if setter is not None else _kernel32_setter()
        self.held, self.reason = False, "not started"

    def apply(self, keep: bool, reason: str) -> bool:
        if self._set is None:
            self.held, self.reason = False, "no display control on this host"
            return False
        if keep != self.held:
            self._set(ES_CONTINUOUS | ES_DISPLAY_REQUIRED if keep else ES_CONTINUOUS)
        self.held, self.reason = keep, reason
        return keep

    def release(self):
        self.apply(False, "worker stopped")
