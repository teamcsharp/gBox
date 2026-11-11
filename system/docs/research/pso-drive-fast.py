"""Hybrid driver: fast forward strides, with a full direction calibration only when forward fails twice.

Measured facts this session: the character moves 35-50 units/s while a key is held, and a calibrated direction table lets a stride use the
best key directly. So the driver should live on the fast path (long forward holds, short turn taps) and pay for a 4-direction calibration
ONLY at a wall - which is what `drive_leg` does here:

  * normal travel: hold up for 1.1-1.7 s, correct the heading with short turn taps, take the heading free from each stride;
  * two failed forward strides: calibrate all four directions (about 1.2 s), stride long with the best one, keep that table for the next
    decision;
  * a failed calibrated stride: diagonal escape (forces travel, which also turns the camera).

Returns elapsed seconds, units travelled, units per second and the number of calibrations, so speed claims are measurable.
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


def calibrate(read_pos, probe=0.25):
    table = {}
    for key in ("up", "down", "left", "right"):
        before = read_pos()
        if before is None or not pso_input.hold(key, probe):
            continue
        after = read_pos()
        if after is None:
            continue
        vector = (after[0] - before[0], after[1] - before[1])
        if math.hypot(*vector) > 1.5:
            table[key] = vector
    return table


def best_key(table, bearing):
    best, best_align = None, -2.0
    for key, vector in table.items():
        length = math.hypot(*vector)
        if length < 1.0:
            continue
        align = (vector[0] / length) * bearing[0] + (vector[1] / length) * bearing[1]
        if align > best_align:
            best, best_align = key, align
    return best, best_align


def drive_leg(read_pos, target, tolerance=12.0, budget=25.0, log=None):
    started = time.time()
    travelled = 0.0
    calibrations = 0
    heading = None
    table = {}
    blocked = 0
    while time.time() - started < budget:
        point = read_pos()
        if point is None:
            break
        distance = math.dist(point, target)
        if distance <= tolerance:
            break
        want = unit(target[0] - point[0], target[1] - point[1])
        want_bearing = heading_of(want)

        if heading is None or blocked >= 2:
            table = calibrate(read_pos)
            calibrations += 1
            key, align = best_key(table, want)
            if key is None:
                pso_input.hold2(["right", "up"], 1.0)
                blocked = 0
                continue
            stride = 1.5 if distance > 50 else 0.8
            before = read_pos()
            pso_input.hold(key, stride)
            after = read_pos()
            if before is None or after is None:
                break
            vector = (after[0] - before[0], after[1] - before[1])
            moved = math.hypot(*vector)
            travelled += moved
            if moved > 1.5:
                heading = heading_of(vector)
                table[key] = vector
                blocked = 0
            else:
                blocked += 1
                pso_input.hold2(["left" if blocked % 2 else "right", "up"], 0.9)
            if log is not None:
                log(f"  calibrated stride {key} {stride:.1f}s: {distance:.0f} -> {math.dist(after, target):.0f}, "
                    f"moved {moved:.0f}, keys {sorted(table)}")
            continue

        error = angle_between(heading, want_bearing)
        if abs(error) > 25.0:
            side = "right" if error > 0 else "left"
            pso_input.hold(side, max(0.08, min(0.4, abs(error) / 150.0)))
            probe = read_pos()
            pso_input.hold("up", 0.2)
            after = read_pos()
            if probe is not None and after is not None and math.dist(probe, after) > 1.5:
                heading = heading_of((after[0] - probe[0], after[1] - probe[1]))
            if log is not None:
                log(f"  turn {side}: error was {error:+.0f} deg, heading {None if heading is None else round(heading)}")
            continue

        stride = 1.7 if distance > 70 else (1.1 if distance > 30 else 0.6)
        before = read_pos()
        if not pso_input.hold("up", stride):
            time.sleep(0.2)
            continue
        after = read_pos()
        if before is None or after is None:
            break
        vector = (after[0] - before[0], after[1] - before[1])
        moved = math.hypot(*vector)
        travelled += moved
        if moved > 1.5:
            heading = heading_of(vector)
            blocked = 0
        else:
            blocked += 1
        if log is not None:
            log(f"  forward {stride:.1f}s: {distance:.0f} -> {math.dist(after, target):.0f}, moved {moved:.0f}, "
                f"blocked {blocked}")
    elapsed = time.time() - started
    point = read_pos()
    final = math.dist(point, target) if point else None
    return (final is not None and final <= tolerance), elapsed, final, travelled, calibrations


def drive_route(read_pos, goal, log=None):
    start = read_pos()
    route, raw_count, simple_count = NAV.plan(start, goal)
    if not route:
        return False, 0.0, 0.0, 0
    if log is not None:
        log(f"route: {raw_count} cell waypoints -> {simple_count} legs, from "
            f"{tuple(round(v) for v in start)} to {goal}")
    total_elapsed = 0.0
    total_travelled = 0.0
    total_calibrations = 0
    for index, waypoint in enumerate(route[1:] or route):
        arrived, elapsed, final, travelled, calibrations = drive_leg(read_pos, waypoint, log=log)
        total_elapsed += elapsed
        total_travelled += travelled
        total_calibrations += calibrations
        if log is not None:
            log(f"  leg {index + 1}/{len(route) - 1} -> {tuple(round(v) for v in waypoint)}: "
                f"arrived={arrived} {elapsed:.1f}s {travelled:.0f} units "
                f"({None if final is None else round(final)} left)")
        if not arrived:
            continue
    speed = total_travelled / max(0.001, total_elapsed)
    return True, total_elapsed, speed, total_calibrations


if __name__ == "__main__":
    import map_exit as ME
    point = ME.read_pos()
    goal = (float(sys.argv[1]), float(sys.argv[2])) if len(sys.argv) > 2 else (141.0, -194.0)
    print(f"start {tuple(round(v) for v in point)} -> goal {goal}")
    reached, elapsed, speed, calibrations = drive_route(ME.read_pos, goal, log=print)
    print(f"reached={reached} elapsed={elapsed:.1f}s speed={speed:.1f} units/s calibrations={calibrations}")
