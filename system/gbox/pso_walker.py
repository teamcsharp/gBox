"""CP17's control loop: walk a world route with stick taps, calibrated from the game itself.

The planner (`pso_steer`) needs to know which world direction the stick's "up" means. Rather than find the yaw field in the
actor struct, the walker **calibrates** it: tap `up` briefly and measure how the player moved - the displacement is the
forward direction, and its perpendicular is screen-right. Everything after that is geometry.

    walker = Walker(read_position=lambda: pso_ram.position(reader, actor),
                    press=lambda keys, seconds: pad.apply(taps(keys, seconds)),
                    read_floor=lambda: pso_ram.floor(reader))
    walker.calibrate()
    result = walker.walk_to((x, z), stop_on_floor_change=True)

The read/press callables are injected, so the loop is testable against a simulated world - which is what `tests/test_pso_walker.py`
does (a straight corridor, an L corner, a floor change, an unreachable target).
"""
from __future__ import annotations

import math

from . import pso_steer


class Walker:
    """A position-readable, pad-driven walker for one player."""

    def __init__(self, read_position, press, *, read_floor=None, forward=None,
                 reach: float = 8.0, leg_seconds: float = 0.25, max_legs: int = 240):
        self.read_position = read_position
        self.press = press
        self.read_floor = read_floor
        self.forward = forward
        self.reach = reach
        self.leg_seconds = leg_seconds
        self.max_legs = max_legs
        self.legs = 0

    # -- calibration ------------------------------------------------------
    def calibrate(self, seconds: float = 0.35, *, min_move: float = 0.5) -> tuple[float, float] | None:
        """Tap `up` and take the displacement as the world forward direction; None when the player did not move."""
        start = self.read_position()
        self.press(("up",), seconds)
        end = self.read_position()
        dx, dz = end[0] - start[0], end[2] - start[2]
        length = math.hypot(dx, dz)
        if length < min_move:
            return None
        self.forward = (dx / length, dz / length)
        return self.forward

    # -- walking ----------------------------------------------------------
    def walk_to(self, target: tuple[float, float], *, stop_on_floor_change: bool = True,
                progress=None) -> dict:
        """Walk to a world (x, z) target. -> {arrived, why, legs, position, floor}."""
        if self.forward is None:
            calibrated = self.calibrate()
            if calibrated is None:
                return {"arrived": False, "why": "calibration failed (the player did not move on a forward tap)",
                        "legs": 0, "position": self.read_position(), "floor": self._floor()}
        start_floor = self._floor() if stop_on_floor_change else None
        for leg in range(self.max_legs):
            position = self.read_position()
            floor = self._floor()
            if stop_on_floor_change and start_floor is not None and floor != start_floor:
                return {"arrived": False, "why": f"the floor changed ({start_floor} -> {floor})",
                        "legs": leg, "position": position, "floor": floor}
            dx, dz = target[0] - position[0], target[1] - position[2]
            if math.hypot(dx, dz) <= self.reach:
                return {"arrived": True, "why": "within reach", "legs": leg, "position": position, "floor": floor}
            keys = pso_steer.direction_taps((dx, dz), 0.0, forward_at_zero=self.forward)
            if not keys:
                return {"arrived": False, "why": "no stick direction for the target", "legs": leg,
                        "position": position, "floor": floor}
            self.press(keys, self.leg_seconds)
            self.legs = leg + 1
            if progress:
                progress({"leg": leg, "position": position, "keys": keys})
        return {"arrived": False, "why": f"gave up after {self.max_legs} legs",
                "legs": self.max_legs, "position": self.read_position(), "floor": self._floor()}

    def _floor(self):
        return self.read_floor() if self.read_floor else None
