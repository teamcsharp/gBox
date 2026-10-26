"""Bounded pauses for transient native reads; never substitutes game state."""
from __future__ import annotations

import errno
import math

TRANSIENT = frozenset({errno.EIO, errno.EFAULT, errno.EAGAIN, errno.EINTR})
RETRY_S, RETRY_INTERVAL_S = 2.0, 0.25


class NativeReadRetry:
    def __init__(self, stats, context):
        self.stats, self.context = stats, context
        self.started, self.failures = None, 0

    def failed(self, error, now):
        """Return the next pause, or None when the original error must surface."""
        self.stats.update(native_read_context=self.context, native_read_error=str(error)[:200])
        if error.errno not in TRANSIENT:
            self.stats['native_read_status'] = 'failed'
            return None
        if self.started is None:
            self.started = now
        self.failures += 1
        waited = max(0., now-self.started)
        self.stats.update(native_read_wait_s=round(waited, 3), native_read_status='waiting')
        # A paused/adjusted clock cannot turn the recovery into an endless wait.
        if waited >= RETRY_S or self.failures > math.ceil(RETRY_S/RETRY_INTERVAL_S):
            self.stats['native_read_status'] = 'timeout'
            return None
        self.stats['native_read_retries'] = self.stats.get('native_read_retries', 0)+1
        return min(RETRY_INTERVAL_S, RETRY_S-waited)

    def recovered(self, now):
        if self.started is not None:
            self.stats.update(native_read_status='ready', native_read_wait_s=round(max(0., now-self.started), 3))
            self.stats['native_read_recoveries'] = self.stats.get('native_read_recoveries', 0)+1
            self.started, self.failures = None, 0

    def stopped(self):
        if self.started is not None and self.stats.get('native_read_status') == 'waiting':
            self.stats['native_read_status'] = 'stopped'
