"""Adversarial simulation of doorway crossing for door_pass2, with no game input.

A wall at x=-40 blocks westward travel except through a gap spanning z in [-10,+10]; the character starts at (0,40), outside the gap, so it
must feel along the wall to find the opening. Success means the character ends up on the far side of the wall, which the simulation checks
directly instead of trusting the planner's own verdict.
"""
import math
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import door_pass2                                                   # noqa: E402

GAP_Z = 10.0
WALL_X = -40.0
STATE = {"x": 0.0, "z": 40.0}
STEP = 14.0


class SimDeps:
    def __init__(self):
        self.room = "near"

    def read_pos(self):
        return (STATE["x"], STATE["z"])

    def allowed(self):
        return True

    def wait_until_ready(self, timeout=120.0):
        return True

    def room_of(self, point):
        return "far" if point[0] < WALL_X else "near"

    def _move(self, key, seconds):
        speed = STEP * max(0.2, seconds)
        moves = {"up": (0.0, -speed), "down": (0.0, speed), "left": (-speed, 0.0), "right": (speed, 0.0)}
        dx, dz = moves.get(key, (0.0, 0.0))
        nx, nz = STATE["x"] + dx, STATE["z"] + dz
        crossing_west = nx < WALL_X <= STATE["x"]
        crossing_east = STATE["x"] < WALL_X <= nx
        if (crossing_west or crossing_east) and abs(STATE["z"]) > GAP_Z:
            nx = WALL_X if crossing_west else WALL_X
        STATE["x"], STATE["z"] = nx, nz

    def step_toward(self, target, tolerance=8.0, max_steps=6):
        """A simplified version of the empirical controller: probe, then take the best-aligned direction."""
        for step in range(max_steps):
            here = self.read_pos()
            distance = math.hypot(here[0] - target[0], here[1] - target[1])
            if distance <= tolerance:
                return True, step, distance, "arrived"
            vectors = {}
            for key in ("up", "down", "left", "right"):
                before = self.read_pos()
                self._move(key, 0.3)
                after = self.read_pos()
                vectors[key] = (after[0] - before[0], after[1] - before[1])
                STATE["x"], STATE["z"] = before
            bearing = ((target[0] - here[0]) / (distance or 1.0), (target[1] - here[1]) / (distance or 1.0))
            best, best_align = None, -2.0
            for key, (dx, dz) in vectors.items():
                length = math.hypot(dx, dz)
                if length < 1.0:
                    continue
                align = (dx / length) * bearing[0] + (dz / length) * bearing[1]
                if align > best_align:
                    best, best_align = key, align
            if best is None:
                return False, step, distance, "no direction moves"
            self._move(best, max(0.25, min(1.4, distance / 45.0)))
        here = self.read_pos()
        return False, max_steps, math.hypot(here[0] - target[0], here[1] - target[1]), "step limit"


def main():
    deps = SimDeps()
    target = (WALL_X - 40.0, 0.0)
    print(f"simulating: start (0,40), wall x={WALL_X}, gap z in [-{GAP_Z},{GAP_Z}], target {target}")
    through, position, reason = door_pass2.approach(deps, target, straight_steps=6, attempts=10, min_travel=45.0,
                                                   strafe=40.0)
    crossed = position[0] < WALL_X
    print(f"result: through={through} at ({position[0]:.1f},{position[1]:.1f}) reason={reason}")
    print(f"actually on the far side of the wall: {crossed}")
    return 0 if crossed else 2


if __name__ == "__main__":
    raise SystemExit(main())
