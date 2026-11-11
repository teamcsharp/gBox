"""Doorway approach v2: strafe TOWARD the gap, and only count success when the character is past the wall.

The v1 loop alternated +/-90 degree strafes blindly and counted any 45 units of travel as success, so the adversarial simulation ended
46 units sideways with the character still on the near side of the wall. v2:
  * picks the strafe side that reduces the character's lateral offset from the target (it seeks the gap instead of guessing);
  * strafes further (40 units) before resuming the approach;
  * counts success only when the character has advanced at least `min_travel` along the APPROACH axis (lateral wandering does not count),
    or when the room id changes.
"""
import math
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")


def log(line):
    print(f"{time.strftime('%H:%M:%S')} {line}", flush=True)


def approach(deps, target, straight_steps=6, attempts=8, min_travel=45.0, strafe=40.0):
    """deps: object with read_pos, step_toward, hold, allowed, wait_until_ready, room_of."""
    start = deps.read_pos()
    if start is None:
        return False, None, "lost position"
    direction = (target[0] - start[0], target[1] - start[1])
    norm = math.hypot(*direction) or 1.0
    direction = (direction[0] / norm, direction[1] / norm)
    start_room = deps.room_of(start)

    def progressed(here):
        along = (here[0] - start[0]) * direction[0] + (here[1] - start[1]) * direction[1]
        return along >= min_travel

    for attempt in range(attempts):
        if not deps.allowed():
            log("  operator has the controller; waiting")
            if not deps.wait_until_ready(120.0):
                return False, deps.read_pos(), "operator kept control"
        here = deps.read_pos()
        if here is None:
            return False, None, "lost position"
        if progressed(here):
            return True, here, f"advanced {min_travel:.0f}+ along the approach"
        if deps.room_of(here) != start_room:
            return True, here, "room changed"
        arrived, steps, final, reason = deps.step_toward(target, tolerance=7.0, max_steps=straight_steps)
        here = deps.read_pos()
        if here is not None and (progressed(here) or deps.room_of(here) != start_room):
            return True, here, "through on the straight approach"
        if arrived:
            return True, here, "arrived at the target"
        # jammed: strafe along the wall toward the target's lateral offset to find the gap
        offset_x, offset_z = target[0] - here[0], target[1] - here[1]
        perp = (-direction[1], direction[0])
        side = 1.0 if (offset_x * perp[0] + offset_z * perp[1]) >= 0 else -1.0
        strafe_to = (here[0] + perp[0] * side * strafe, here[1] + perp[1] * side * strafe)
        log(f"  attempt {attempt}: jammed ({reason}, {final if final is None else round(final)} short); "
            f"strafing along the wall toward {tuple(round(v) for v in strafe_to)}")
        deps.step_toward(strafe_to, tolerance=9.0, max_steps=4)
    return False, deps.read_pos(), "attempts exhausted"


class GameDeps:
    """The live game, with every key press going through pso_input (operator lock honoured)."""

    def __init__(self):
        import map_exit as ME
        import pso_input
        import steer2 as STEER
        self._ME = ME
        self._input = pso_input
        self._steer = STEER

    def read_pos(self):
        return self._ME.read_pos()

    def step_toward(self, target, tolerance=8.0, max_steps=6):
        arrivals = self._steer.step_toward(self._input.hold, self.read_pos, target, tolerance=tolerance,
                                           max_steps=max_steps, log=None)
        return arrivals

    def allowed(self):
        return self._input.allowed()

    def wait_until_ready(self, timeout=120.0):
        return self._input.wait_until_ready(timeout)

    def room_of(self, point):
        import explore as E
        return E.room_of(point, E.rooms())


def main():
    deps = GameDeps()
    point = deps.read_pos()
    markers = deps._ME.exits_from_map()
    if not markers or point is None:
        log("no exit marker or no player")
        return 2
    marker = max(markers, key=lambda m: m["distance_px"])
    target = (point[0] + marker["dir"][0] * 50.0, point[1] + marker["dir"][1] * 50.0)
    log(f"player {tuple(round(v) for v in point)}, exit bearing {marker['bearing']:+.0f}; target "
        f"{tuple(round(v) for v in target)}")
    through, position, reason = approach(deps, target)
    log(f"through={through} at {None if position is None else tuple(round(v) for v in position)} ({reason})")
    return 0 if through else 3


if __name__ == "__main__":
    raise SystemExit(main())
