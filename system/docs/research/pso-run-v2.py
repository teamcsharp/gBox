"""Run v2: a cheap calibration before every stride, so the direction is always right.

v1 kept the key table across strides and rotated it by each stride's own displacement. That drifts: measured strides chosen with align 0.80
moved the character AWAY from the target (79 -> 174 units), because the rotation derived from one key's actual displacement is wrong for the
others when the character slides.

v2 stops trying to reuse the table. Four probes of 0.12 s (half a second total) establish the directions freshly, then one long stride of
2.0-2.5 s covers 80-95 units. The cycle is about 3 s for 90 units - roughly 30 units/s, with a correct heading every time and no
oscillation.
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


def calibrate(read_pos, probe=0.12):
    table = {}
    for key in ("up", "down", "left", "right"):
        before = read_pos()
        if before is None or not pso_input.hold(key, probe):
            continue
        after = read_pos()
        if after is None:
            continue
        vector = (after[0] - before[0], after[1] - before[1])
        if math.hypot(*vector) > 0.8:
            table[key] = vector
    return table


def best_key(table, bearing):
    best, best_align = None, -2.0
    for key, vector in table.items():
        length = math.hypot(*vector)
        if length < 0.5:
            continue
        align = (vector[0] / length) * bearing[0] + (vector[1] / length) * bearing[1]
        if align > best_align:
            best, best_align = key, align
    return best, best_align


def run_to(read_pos, target, tolerance=13.0, budget=25.0, log=None):
    started = time.time()
    travelled = 0.0
    cycles = 0
    while time.time() - started < budget:
        point = read_pos()
        if point is None:
            break
        distance = math.dist(point, target)
        if distance <= tolerance:
            break
        bearing = unit(target[0] - point[0], target[1] - point[1])
        table = calibrate(read_pos)
        cycles += 1
        key, align = best_key(table, bearing)
        if key is None:
            pso_input.hold2(["right", "up"], 1.0)
            continue
        before = read_pos()
        if align < 0.5:
            # no key points at the target: a short step rotates the camera instead of running the wrong way
            pso_input.hold(key, 0.3)
            if log is not None:
                log(f"  short corrective {key} (align {align:.2f})")
            continue
        seconds = max(0.35, min(0.9, distance / 30.0))            # short holds: the camera swings during long ones, so long holds arc
        pso_input.hold(key, seconds)
        after = read_pos()
        if before is None or after is None:
            break
        moved = math.dist(before, after)
        travelled += moved
        if log is not None:
            log(f"  {key} {seconds:.1f}s align {align:.2f}: {distance:.0f} -> "
                f"{math.dist(after, target):.0f} units, moved {moved:.0f}")
        if moved < 2.0:
            pso_input.hold2(["left", "up"], 0.9)
    elapsed = time.time() - started
    point = read_pos()
    final = math.dist(point, target) if point else None
    return (final is not None and final <= tolerance), elapsed, final, travelled, cycles


def run_route(read_pos, goal, log=None, replans=3):
    total_elapsed = 0.0
    total_travelled = 0.0
    reached = False
    for attempt in range(replans + 1):
        start = read_pos()
        if start is None:
            break
        route, raw_count, simple_count = NAV.plan(start, goal)
        if not route:
            break
        if log is not None:
            log(f"  route {attempt}: {raw_count} cells -> {simple_count} legs")
        stalled = False
        for index, waypoint in enumerate(route[1:] or route):
            arrived, elapsed, final, travelled, cycles = run_to(read_pos, waypoint, log=log)
            total_elapsed += elapsed
            total_travelled += travelled
            if log is not None:
                log(f"    leg {index + 1}/{max(1, len(route) - 1)} -> {tuple(round(v) for v in waypoint)}: "
                    f"arrived={arrived} {elapsed:.1f}s {travelled:.0f} units "
                    f"({None if final is None else round(final)} left)")
            if not arrived:
                stalled = True
                break
        point = read_pos()
        if point is not None and math.dist(point, goal) <= 16.0:
            reached = True
            break
        if not stalled:
            break
    speed = total_travelled / max(0.001, total_elapsed)
    return reached, total_elapsed, speed


if __name__ == "__main__":
    import map_exit as ME
    point = ME.read_pos()
    goal = (float(sys.argv[1]), float(sys.argv[2])) if len(sys.argv) > 2 else (-125.0, 15.0)
    print(f"start {tuple(round(v) for v in point)} -> goal {goal}")
    reached, elapsed, speed = run_route(ME.read_pos, goal, log=print)
    print(f"reached={reached} elapsed={elapsed:.1f}s speed={speed:.1f} units/s")
