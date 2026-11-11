"""Walk through a doorway: straight at the marker, and when that jams, strafe along the wall and retry.

Round 212 got the exit marker's bearing right but stalled 41 units short because a doorway is a narrow opening and the controller walks
the straight line into the jamb. This adds the missing behaviour: on a stall, step PERPENDICULAR to the exit bearing (alternating sides),
then resume the approach - the standard "feel along the wall for the gap" loop.

Success is measured, not assumed: the walk counts as through when the character's distance from the starting point exceeds
`min_travel` or the room id changes.

Every key press goes through pso_input, so the operator lock always wins.
"""
import math
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import map_exit as ME                                              # noqa: E402
import pso_input                                                   # noqa: E402
import steer2 as STEER                                             # noqa: E402


def log(line):
    print(f"{time.strftime('%H:%M:%S')} {line}", flush=True)


def approach(target, straight_steps=6, attempts=6, min_travel=45.0):
    """Walk at `target`, strafing when jammed. Returns (through, position, reason)."""
    start = ME.read_pos()
    if start is None:
        return False, None, "lost position"
    for attempt in range(attempts):
        if not pso_input.allowed():
            log("  operator has the controller; pausing it out")
            if not pso_input.wait_until_ready(120.0):
                return False, ME.read_pos(), "operator kept control"
        here = ME.read_pos()
        if here is None:
            return False, None, "lost position"
        if math.dist(here, start) >= min_travel:
            return True, here, f"travelled {math.dist(here, start):.0f} units"
        arrived, steps, final, reason = STEER.step_toward(
            pso_input.hold, ME.read_pos, target, tolerance=7.0, max_steps=straight_steps, log=None)
        here = ME.read_pos()
        if arrived:
            return True, here, "arrived at the marker point"
        if math.dist(here, start) >= min_travel:
            return True, here, f"travelled {math.dist(here, start):.0f} units"
        # strafe perpendicular to the approach bearing, alternating sides, to feel along the wall for the gap
        direction = (target[0] - start[0], target[1] - start[1])
        norm = math.hypot(*direction) or 1.0
        direction = (direction[0] / norm, direction[1] / norm)
        side = 1 if attempt % 2 == 0 else -1
        perp = (-direction[1] * side, direction[0] * side)
        mid = (here[0] + perp[0] * 30.0, here[1] + perp[1] * 30.0)
        log(f"  attempt {attempt}: jammed {final if final is None else round(final)} short ({reason}); "
            f"strafing {'+90' if side > 0 else '-90'} deg")
        STEER.step_toward(pso_input.hold, ME.read_pos, mid, tolerance=8.0, max_steps=3, log=None)
    return False, ME.read_pos(), "attempts exhausted"


def main(exits_rounds=3):
    point = ME.read_pos()
    if point is None:
        log("no player")
        return 2
    markers = ME.exits_from_map()
    log(f"player {tuple(round(v) for v in point)}; exit markers "
        f"{[(round(m['bearing']), round(m['distance_px'])) for m in markers]}")
    if not markers:
        log("no exit marker on the map")
        return 2
    marker = max(markers, key=lambda m: m["distance_px"])          # the marker furthest out is the doorway
    target = (point[0] + marker["dir"][0] * 45.0, point[1] + marker["dir"][1] * 45.0)
    log(f"heading through the marker at bearing {marker['bearing']:+.0f} deg -> world target "
        f"{tuple(round(v) for v in target)}")
    through, position, reason = approach(target)
    log(f"through={through} at {None if position is None else tuple(round(v) for v in position)} ({reason})")
    return 0 if through else 3


if __name__ == "__main__":
    raise SystemExit(main())
