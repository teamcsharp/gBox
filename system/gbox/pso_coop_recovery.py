"""Wait through transient outages only for the exact opted-in PSO controller."""
from __future__ import annotations

import errno

import httpx

from .registry import Unsupported


def continuous_requested(driver, session_id):
    # Re-read the live intent: repeated Start can revoke continuous, and a new
    # driver or human takeover must never inherit an old controller's retries.
    from .tools import AUTOPLAY
    run = AUTOPLAY.get(session_id) or {}
    return bool(run.get("driver") is driver and not getattr(driver, "stopped", False)
                and not run.get("took_over") and not run.get("reaped")
                and getattr(run.get("inp"), "continuous", False) is True)


def transient(exc):
    if isinstance(exc, (httpx.NetworkError, httpx.TimeoutException, httpx.RemoteProtocolError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (408, 425, 429, 500, 502, 503, 504)
    # Native reads use OSError without errno. Permission, missing files, full
    # disks and invalid local data keep their original bounded failure path.
    return (isinstance(exc, OSError) and not isinstance(exc, (PermissionError, FileNotFoundError,
             IsADirectoryError, NotADirectoryError)) and exc.errno in {
        None, errno.EAGAIN, errno.EBUSY, errno.EINTR, errno.ETIMEDOUT,
        errno.ECONNRESET, errno.ECONNREFUSED, errno.EPIPE,
        errno.ENETDOWN, errno.ENETRESET, errno.ENETUNREACH, errno.EHOSTUNREACH})


class TransientRecovery:
    def __init__(self, *, enabled, stopped, release, invalidate, wait, stats):
        self.enabled, self.stopped = enabled, stopped
        self.release, self.invalidate, self.wait, self.stats = release, invalidate, wait, stats
        self.attempts = 0
        self.waiting = False

    def pause(self, exc, source):
        if self.stopped() or not self.enabled() or not transient(exc):
            return False
        self.invalidate()
        try:
            self.release()
        except Exception as error:
            raise Unsupported("PSO recovery could not release both controllers; inputs remain stopped") from error
        self.waiting = True
        self.attempts += 1
        delay = min(30, 2 ** min(self.attempts - 1, 5))
        self.stats.update(recovery_state="waiting_for_fresh_observation", recovery_source=source,
                          recovery_attempts=self.attempts, recovery_backoff_s=delay,
                          recovery_last_error=f"{type(exc).__name__}: {exc}"[:400],
                          action="waiting_for_transient_recovery")
        # Each wait is bounded and Stop/takeover can interrupt it. This never
        # resets an emulator, opens a card, or renews a revoked autoplay intent.
        self.wait(delay, lambda: self.stopped() or not self.enabled())
        return True

    def observed(self):
        if self.waiting:
            self.stats.update(recovery_state="recovered_from_fresh_observation", recovery_backoff_s=0)
        self.waiting, self.attempts = False, 0
