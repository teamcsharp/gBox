"""Learned menu cadence: how fast a title's menus can be pressed and still confirm in RAM.

The Navigator's cursor knobs (stable_s, retry_s, poll_s) were tuned once per title by hand. This turns them into a
measured, adaptive profile: every confirmed screen change records how long the press took to show in RAM, and the
profile is nudged toward the fastest cadence that still confirms - faster after a confirmed step (x0.92), slower after a
missed confirmation (x1.45), bounded so a bad frame can never make it press faster than the ROM accepts. The profile
persists per title under the bot's data dir, so a reload keeps what earlier rounds learned, and `stats["menu_speed"]`
carries the live numbers (steps, confirm_ms, cadence_s, fast_steps) for the receipts.

Measured for reference (RE5 PS3, 2026-10-26): ~1.1 s per cursor step with the hand-set values; the target here is
0.1-0.3 s a step once a screen's confirmation latency is known.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

MIN_STABLE_S, MAX_STABLE_S = 0.04, 0.45
MIN_RETRY_S, MAX_RETRY_S = 0.18, 1.20
MIN_POLL_S, MAX_POLL_S = 0.02, 0.25
FAST, SLOW = 0.92, 1.45


def default_profile() -> dict:
    return {"stable_s": 0.10, "retry_s": 0.30, "poll_s": 0.05,
            "confirm_ms": None, "steps": 0, "fast_steps": 0, "misses": 0, "runs": 0}


class Speed:
    """One title's menu cadence: `stable_s`/`retry_s`/`poll_s` in the Navigator's NAV_CURSOR shape, learned."""

    def __init__(self, profile: dict | None = None, path: Path | None = None, clock=time.monotonic):
        self.data = default_profile() | dict(profile or {})
        # the live dict the Navigator holds: updated in place so learning applies to the steps that follow
        self.live = {key: self.data[key] for key in ("stable_s", "retry_s", "poll_s")}
        self.path = Path(path) if path else None
        self.clock = clock
        self.pressed_at: float | None = None
        self.pressed_where: str | None = None
        self.last_where: str | None = None
        self.initialized = False

    # --- the Navigator reads these through the module's NAV_CURSOR ---
    def profile(self) -> dict:
        return self.live

    def _sync(self) -> None:
        self.live.update({key: self.data[key] for key in ("stable_s", "retry_s", "poll_s")})

    def pressed(self, where: str | None) -> None:
        """A press went in on `where`: the next confirmed screen change measures its latency."""
        self.pressed_at, self.pressed_where = self.clock(), where

    def observed(self, where: str | None, now: float | None = None) -> None:
        """The RAM now names `where`: if that is a change after a press, learn from how long it took."""
        now = self.clock() if now is None else now
        if not self.initialized:
            self.initialized, self.last_where = True, where
            return
        if where == self.last_where:
            return
        self.data["steps"] += 1
        if self.pressed_at is not None:
            latency = max(0.0, now - self.pressed_at)
            if latency <= MAX_STABLE_S * 3:
                self.data["fast_steps"] += 1
                previous = self.data.get("confirm_ms")
                self.data["confirm_ms"] = round(latency * 1000) if previous is None else round(
                    0.7 * previous + 0.3 * latency * 1000)
                self.data["stable_s"] = _clamp(self.data["stable_s"] * FAST, MIN_STABLE_S, MAX_STABLE_S)
                self.data["retry_s"] = _clamp(self.data["retry_s"] * FAST, MIN_RETRY_S, MAX_RETRY_S)
                self.data["poll_s"] = _clamp(self.data["poll_s"] * FAST, MIN_POLL_S, MAX_POLL_S)
            else:
                self.data["misses"] += 1
                self.data["stable_s"] = _clamp(self.data["stable_s"] * SLOW, MIN_STABLE_S, MAX_STABLE_S)
                self.data["retry_s"] = _clamp(self.data["retry_s"] * SLOW, MIN_RETRY_S, MAX_RETRY_S)
                self.data["poll_s"] = _clamp(self.data["poll_s"] * SLOW, MIN_POLL_S, MAX_POLL_S)
        self.pressed_at = None
        self.last_where = where
        self._sync()
        self.save()

    def stats(self) -> dict:
        return {"cadence_s": round(self.data["stable_s"], 3), "confirm_ms": self.data["confirm_ms"],
                "steps": self.data["steps"], "fast_steps": self.data["fast_steps"], "misses": self.data["misses"]}

    # --- persistence ---
    def save(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
        except OSError:
            pass

    @classmethod
    def load(cls, path: Path | None, **kwargs) -> "Speed":
        profile = None
        if path and Path(path).is_file():
            try:
                profile = json.loads(Path(path).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                profile = None
        return cls(profile, path=path, **kwargs)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


_CACHE: dict[str, Speed] = {}


def for_title(map_id: str, data_dir: str | Path | None = None) -> Speed:
    """The title's learned cadence (one per process), persisted under <data dir>/mercs/learned/<map_id>/menu_speed.json."""
    if map_id in _CACHE:
        return _CACHE[map_id]
    path = None
    if data_dir:
        path = Path(data_dir) / "mercs" / "learned" / map_id / "menu_speed.json"
    _CACHE[map_id] = Speed.load(path)
    return _CACHE[map_id]
