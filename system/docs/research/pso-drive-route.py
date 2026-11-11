"""Drive a planned route in long forward holds, turning only when the heading error is large.

`nav_fast.plan()` collapses a 149-waypoint cell route into 9 straight legs (1230 units, planned in 0.15 s). Each leg is a clear line, so
the driver can hold forward for 1.5-2 s stretches and correct with short turn taps - no per-stride probing at all.

The heading comes free from each forward stride's displacement (holding up moves the character where it faces). When a forward stride is
blocked, the driver turns 60 degrees and retries, which is how it gets around a jamb without measuring the four directions.

Returns the measurement the operator cares about: elapsed seconds, units per second and how many turns it took.
"""
import math
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import nav_fast as NAV                                             # noqa: E402
import pso_input                                                   # noqa: E402


def unit(dx, dz):
    length = math.hypot(dx, dz)
    return (dx / length, dz / length) if length > 1e-6 else (0.0, 0.0)


def heading_of(vector):
    return math.degrees(math.atan2(vector[1], vector[0]))


def angle_between(a, b):
    return (b - a + 180.0) % 360.0 - 180.0


def forward(read_pos, seconds):
    before = read_pos()
    if before is None or not pso_input.hold("up", seconds):
        return None, None
    after = read_pos()
    if after is None:
        return None, None
    return (after[0] - before[0], after[1] - before[1]), after


def drive_leg(read_pos, target, tolerance=12.0, budget=20.0, log=None):
    """Drive to one waypoint. Returns (arrived, elapsed, distance, travelled, turns)."""
    started = time.time()
    travelled = 0.0
    turns = 0
    heading = None
    blocked = 0
    escapes = 0
    while time.time() - started < budget:
        point = read_pos()
        if point is None:
            break
        distance = math.dist(point, target)
        if distance <= tolerance:
            break
        want = heading_of((target[0] - point[0], target[1] - point[1]))
        if heading is None:
            vector, after = forward(read_pos, 0.3)
            if vector is None:
                break
            moved = math.hypot(*vector)
            travelled += moved
            if moved > 1.5:
                heading = heading_of(vector)
                continue
            blocked += 1
            side = "right" if blocked % 2 else "left"
            pso_input.hold(side, 0.35)
            turns += 1
            continue
        error = angle_between(heading, want)
        if abs(error) > 22.0:
            side = "right" if error > 0 else "left"
            seconds = max(0.08, min(0.4, abs(error) / 150.0))
            pso_input.hold(side, seconds)
            turns += 1
            # a turn's own displacement gives the new heading cheaply
            vector, _ = forward(read_pos, 0.2)
            if vector is not None and math.hypot(*vector) > 1.0:
                heading = heading_of(vector)
            continue
        seconds = 1.7 if distance > 70 else (1.1 if distance > 30 else 0.6)
        vector, after = forward(read_pos, seconds)
        if vector is None:
            break
        moved = math.hypot(*vector)
        travelled += moved
        if moved > 1.5:
            heading = heading_of(vector)
            blocked = 0
        else:
            blocked += 1
            if blocked >= 2:
                # pressing against a wall: a diagonal forces travel, which also turns the camera and gives a new heading
                side = "right" if escapes % 2 else "left"
                pso_input.hold2([side, "up"], 1.0)
                escapes += 1
                vector, after = forward(read_pos, 0.3)
                if vector is not None and math.hypot(*vector) > 1.5:
                    heading = heading_of(vector)
                blocked = 0
            else:
                side = "right" if blocked % 2 else "left"
                pso_input.hold(side, 0.45)
                turns += 1
        if log is not None:
            log(f"    leg step: {distance:.0f} units left, moved {moved:.0f}, heading {heading if heading is None else round(heading)}")
    elapsed = time.time() - started
    point = read_pos()
    final = math.dist(point, target) if point else None
    return (final is not None and final <= tolerance), elapsed, final, travelled, turns


def drive_route(read_pos, start, goal, log=None):
    route, raw_count, simple_count = NAV.plan(start, goal)
    if not route:
        return False, 0.0, 0.0, 0
    if log is not None:
        log(f"route: {raw_count} cell waypoints -> {simple_count} legs")
    total_elapsed = 0.0
    total_travelled = 0.0
    total_turns = 0
    position = start
    for index, waypoint in enumerate(route[1:] or route):
        arrived, elapsed, final, travelled, turns = drive_leg(read_pos, waypoint, log=log)
        total_elapsed += elapsed
        total_travelled += travelled
        total_turns += turns
        if log is not None:
            log(f"  leg {index + 1}/{len(route) - 1} -> {tuple(round(v) for v in waypoint)}: "
                f"arrived={arrived} {elapsed:.1f}s {travelled:.0f} units ({final:.0f} left)")
        if not arrived:
            break
        position = waypoint
    speed = total_travelled / max(0.001, total_elapsed)
    return True, total_elapsed, speed, total_turns


if __name__ == "__main__":
    import map_exit as ME
    point = ME.read_pos()
    goal = (float(sys.argv[1]), float(sys.argv[2])) if len(sys.argv) > 2 else (141.0, -194.0)
    print(f"start {tuple(round(v) for v in point)} -> goal {goal}")
    reached, elapsed, speed, turns = drive_route(ME.read_pos, point, goal, log=print)
    print(f"reached_goal={reached} elapsed={elapsed:.1f}s speed={speed:.1f} units/s turns={turns}")
