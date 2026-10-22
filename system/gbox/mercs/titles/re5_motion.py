"""RE5 bot motion quality (#3045): heading hysteresis for the walk and a per-round turn-rate / idle-spin meter.

Operator 2026-10-22: the bot "stands still and turns rapidly in random directions". Two pieces:
 * HeadingHold: a committed walk heading that only changes when the new one differs by more than HOLD (hysteresis)
   or has persisted for DWELL seconds, so a target flip-flopping between near-equal candidates cannot spin the stick.
 * MotionMeter: yaw rate variance and seconds spent turning in place (idle spin) from the player's own pos/rot.
Pure functions of (now, pos, rot); no RAM fields are read here (pos/rot come from the existing snapshot)."""
from __future__ import annotations

import math

HOLD = math.radians(25)        # a new heading closer than this to the committed one is ignored
DWELL = 0.6                    # ... unless the new heading has been asked for this long (s)
SPIN_RATE = math.radians(40)   # turning faster than this (rad/s) ...
SPIN_MOVE = 40.0               # ... while moving less than this (cm/s) is an idle spin
MAX_DT = 1.0                   # a longer gap between samples is a pause, not motion


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


class HeadingHold:
    def __init__(self, hold=HOLD, dwell=DWELL):
        self.hold, self.dwell = hold, dwell
        self.heading = None
        self._cand = None          # (heading, since)
        self.flips_suppressed = 0

    def reset(self):
        self.heading = self._cand = None

    def pick(self, want: float, now: float) -> float:
        if self.heading is None:
            self.heading = want
            return want
        if abs(wrap(want - self.heading)) <= self.hold:
            self._cand = None
            return self.heading                          # inside the deadband: keep the committed heading
        if self._cand is None or abs(wrap(want - self._cand[0])) > self.hold:
            self._cand = (want, now)
        if now - self._cand[1] >= self.dwell:
            self.heading, self._cand = want, None
            return want
        self.flips_suppressed += 1
        return self.heading


class MotionMeter:
    def __init__(self):
        self.last = None
        self.rates = []
        self.idle_spin_s = 0.0
        self.time_s = 0.0

    def observe(self, now: float, pos, rot: float):
        if self.last is not None:
            t0, p0, r0 = self.last
            dt = now - t0
            if 0 < dt <= MAX_DT:
                rate = wrap(rot - r0) / dt
                speed = math.hypot(pos[0] - p0[0], pos[2] - p0[2]) / dt
                self.rates.append(rate)
                self.time_s += dt
                if abs(rate) >= SPIN_RATE and speed < SPIN_MOVE:
                    self.idle_spin_s += dt
        self.last = (now, tuple(pos), rot)

    def summary(self) -> dict:
        n = len(self.rates)
        mean = sum(self.rates) / n if n else 0.0
        var = sum((r - mean) ** 2 for r in self.rates) / n if n else 0.0
        return {"turn_rate_var": round(var, 4), "idle_spin_s": round(self.idle_spin_s, 2),
                "motion_s": round(self.time_s, 2), "samples": n}
