"""Title-independent navigation/combat pieces of the Mercenaries engine (docs/mercenaries_engine.md).

Titles supply RAM maps and input; the logic here takes plain (x, y, z) tuples and a clock value:

    StuckDetector   position not changing while moving -> stuck (the caller re-routes)
    PortalMemory    doors / windows / ledges / ladders remembered per stage
    height_cost     height-aware target distance (a bonus above / below costs more than its flat distance)
    sight_gate      the line-of-sight gate before firing (a blocked view must be walked to, not shot at)
    bonus_priority  time-bonus-first ordering of targets (S rank)
"""
from __future__ import annotations

import math

PORTAL_KINDS = ("door", "window", "ledge", "ladder")


class StuckDetector:
    """Feed update(now, x, z, moving) each tick. Returns True once, when the player has been moving (pushing forward)
    for `window_s` without covering `min_move` of ground; the window then restarts. Not moving (turning in place,
    a prompt) clears the samples: standing still on purpose is never stuck."""

    def __init__(self, window_s: float = 1.2, min_move: float = 80.0):
        self.window_s, self.min_move = window_s, min_move
        self.hist: list = []
        self.count = 0

    def reset(self) -> None:
        self.hist = []

    def update(self, now: float, x: float, z: float, moving: bool = True) -> bool:
        if not moving:
            self.hist = []
            return False
        self.hist = [h for h in self.hist if now - h[0] < self.window_s + 0.3] + [(now, x, z)]
        t0, x0, z0 = self.hist[0]
        if now - t0 >= self.window_s and math.hypot(x - x0, z - z0) < self.min_move:
            self.hist = []
            self.count += 1
            return True
        return False


class PortalMemory:
    """Portals seen per stage: {stage: [(kind, (x, y, z))]}. A portal within `merge_r` of a known one of the same kind
    is the same portal."""

    def __init__(self, merge_r: float = 40.0):
        self.merge_r = merge_r
        self.by_stage: dict = {}

    def remember(self, stage, kind: str, pos) -> bool:
        if kind not in PORTAL_KINDS:
            raise ValueError(f"unknown portal kind {kind!r}")
        pos = tuple(pos)
        items = self.by_stage.setdefault(stage, [])
        if any(k == kind and math.dist(p, pos) < self.merge_r for k, p in items):
            return False
        items.append((kind, pos))
        return True

    def portals(self, stage, kind: str | None = None) -> list:
        return [(k, p) for k, p in self.by_stage.get(stage, []) if kind is None or k == kind]

    def nearest(self, stage, pos, kind: str | None = None):
        c = self.portals(stage, kind)
        return min(c, key=lambda kp: math.dist(kp[1], tuple(pos)), default=None)

    def forget(self, stage) -> None:
        self.by_stage.pop(stage, None)


def height_cost(src, dst, per_unit: float = 2.0, level: float = 150.0) -> float:
    """Ground distance plus a penalty for height difference beyond `level` (a bonus a floor up needs a stair or
    ladder, so it is farther than the flat distance says). Points are (x, y, z), y up."""
    flat = math.hypot(dst[0] - src[0], dst[2] - src[2])
    dy = abs(dst[1] - src[1])
    return flat + max(0.0, dy - level) * per_unit


def sight_gate(view: str, blocked_for: float, hold_s: float = 0.3) -> str:
    """'fire' when the aim ray reaches the target; 'wait' while a block is younger than hold_s (the gun coming up);
    'pursue' once a wall / short view has lasted hold_s. view: 'on' | 'wall' | 'short' | 'none'."""
    if view == "on":
        return "fire"
    if view in ("wall", "short"):
        return "pursue" if blocked_for >= hold_s else "wait"
    return "wait"


def bonus_priority(targets, pos, time_left_s: float | None = None, s_rank: bool = True) -> list:
    """Order targets [{kind, pos, ...}] nearest-first by height_cost; for S rank, kind=='time' bonuses come first.
    When time_left_s is given and positive-ish low (< 30), time bonuses lead even without s_rank."""
    urgent = s_rank or (time_left_s is not None and time_left_s < 30.0)
    return sorted(targets, key=lambda t: (0 if urgent and t.get("kind") == "time" else 1,
                                          height_cost(pos, t["pos"])))
