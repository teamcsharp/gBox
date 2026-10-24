"""Reusable item placement cadence. Adapters own inventory, input, and confirmation.

An attempted press is never a placement: only the adapter's acknowledgement advances
the schedule. Prompts and recovery suspend optional placement without consuming it.
"""
from __future__ import annotations

import math


class Cadence:
    def __init__(self, interval=60., only=False, enabled=True):
        self.configure(interval, only, enabled)
        self.last = None
        self.position = None
        self.entrance = False

    def configure(self, interval=60., only=False, enabled=True):
        interval = float(interval)
        if not math.isfinite(interval) or not 2 <= interval <= 300:
            raise ValueError("placement interval must be 2–300 seconds")
        self.interval, self.only, self.enabled = interval, bool(only), bool(enabled)

    def due(self, now, position, *, busy=False):
        if not self.enabled or busy:
            return False
        if self.last is None:
            self.last = now
            return self.only
        elapsed = now - self.last
        moved = self.position is None or math.dist(position, self.position) >= 250
        # Waiting longer never substitutes for leaving the last verified site.
        return moved and (elapsed >= (max(2., min(5., self.interval)) if self.only else self.interval)
                          or self.entrance and elapsed >= 5)

    def acknowledge(self, now, position):
        self.last, self.position, self.entrance = now, tuple(position), False
