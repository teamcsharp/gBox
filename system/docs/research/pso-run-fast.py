"""Run: cover ground in long straight holds, never turn in place.

Measured: the character moves 35-50 units/s while a key is held, and my turn-based drivers spent most of their time turning because each
turn tap swings the heading tens of degrees. So this driver has NO turn step at all:

  * calibrate the four directions once (4 x 0.25 s);
  * pick the key whose measured vector points closest at the target and HOLD IT for 2.5 s - a long straight run;
  * the stride's own displacement is that key's new vector (free refresh), and the other keys rotate by the same delta;
  * when the best alignment drops below 0.6 the table is stale: calibrate again;
  * two blocked strides in a row: diagonal escape, then calibrate.

Expected throughput: about 110 units per 2.5 s hold with ~1 s of calibration per cycle, so 25-35 units/s sustained, against 3.4 u/s for the
turn-based driver.
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
    return math.atan2(vector[1], vector[0])


def rotate(vector, radians):
    cos, sin = math.cos(radians), math.sin(radians)
    return (vector[0] * cos - vector[1] * sin, vector[0] * sin + vector[1] * cos)


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


def run_to(read_pos, target, tolerance=14.0, budget=40.0, hold_seconds=2.5, log=None):
    started = time.time()
    travelled = 0.0
    calibrations = 0
    table = calibrate(read_pos)
    calibrations += 1
    blocked = 0
    while time.time() - started < budget:
        point = read_pos()
        if point is None:
            break
        distance = math.dist(point, target)
        if distance <= tolerance:
            break
        bearing = unit(target[0] - point[0], target[1] - point[1])
        key, align = best_key(table, bearing) if table else (None, -2.0)
        if key is None or align < 0.6:
            table = calibrate(read_pos)
            calibrations += 1
            key, align = best_key(table, bearing)
            if key is None:
                pso_input.hold2(["right", "up"], 1.0)
                blocked = 0
                continue
        before = read_pos()
        seconds = hold_seconds if distance > 60 else max(0.5, hold_seconds * distance / 60.0)
        if not pso_input.hold(key, seconds):
            time.sleep(0.2)
            continue
        after = read_pos()
        if before is None or after is None:
            break
        vector = (after[0] - before[0], after[1] - before[1])
        moved = math.hypot(*vector)
        travelled += moved
        if moved > 2.0:
            delta = heading_of(vector) - heading_of(table[key])
            table = {k: (vector if k == key else rotate(v, delta)) for k, v in table.items()}
            blocked = 0
        else:
            blocked += 1
            if blocked >= 2:
                pso_input.hold2(["left" if blocked % 2 else "right", "up"], 1.0)
                table = calibrate(read_pos)
                calibrations += 1
                blocked = 0
        if log is not None:
            log(f"  {key} {seconds:.1f}s: {distance:.0f} -> {math.dist(after, target):.0f} units, moved {moved:.0f}, "
                f"align {align:.2f}")
    elapsed = time.time() - started
    point = read_pos()
    final = math.dist(point, target) if point else None
    return (final is not None and final <= tolerance), elapsed, final, travelled, calibrations


def run_route(read_pos, goal, log=None):
    start = read_pos()
    route, raw_count, simple_count = NAV.plan(start, goal)
    if not route:
        return False, 0.0, 0.0
    if log is not None:
        log(f"route: {raw_count} cell waypoints -> {simple_count} legs")
    total_elapsed = 0.0
    total_travelled = 0.0
    for index, waypoint in enumerate(route[1:] or route):
        arrived, elapsed, final, travelled, calibrations = run_to(read_pos, waypoint, log=log)
        total_elapsed += elapsed
        total_travelled += travelled
        if log is not None:
            log(f"  leg {index + 1}/{len(route) - 1} -> {tuple(round(v) for v in waypoint)}: arrived={arrived} "
                f"{elapsed:.1f}s {travelled:.0f} units ({None if final is None else round(final)} left)")
    return True, total_elapsed, total_travelled / max(0.001, total_elapsed)


if __name__ == "__main__":
    import map_exit as ME
    point = ME.read_pos()
    goal = (float(sys.argv[1]), float(sys.argv[2])) if len(sys.argv) > 2 else (141.0, -194.0)
    print(f"start {tuple(round(v) for v in point)} -> goal {goal}")
    reached, elapsed, speed = run_route(ME.read_pos, goal, log=print)
    print(f"reached={reached} elapsed={elapsed:.1f}s speed={speed:.1f} units/s")
