"""Drive like a player: hold forward in long strides and correct the heading with short turn taps.

The measurement-per-stride controllers spend most of their time deciding. PSO moves the character at roughly 45 units/s while "up" is held,
so the fast way to travel is to hold up for long stretches and steer with brief left/right taps - exactly how a person plays.

How the heading stays known for free: holding up moves the character in the direction it faces, so every forward stride's displacement IS
the current heading. A turn tap changes it by a measured amount, learned once and rescaled after each turn (the tap's effect is linear
enough at these short durations).

Interface: `drive_to(read_pos, target, ...)` -> (arrived, elapsed, distance, units_per_second, turns)
All keys through pso_input, so the operator lock always wins.
"""
import math
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import pso_input                                                   # noqa: E402


def unit(dx, dz):
    length = math.hypot(dx, dz)
    return (dx / length, dz / length) if length > 1e-6 else (0.0, 0.0)


def heading_of(vector):
    return math.degrees(math.atan2(vector[1], vector[0]))


def angle_between(a, b):
    return (b - a + 180.0) % 360.0 - 180.0


def forward(read_pos, seconds):
    """Hold up and return the displacement it produced."""
    before = read_pos()
    if before is None or not pso_input.hold("up", seconds):
        return None, None
    after = read_pos()
    if after is None:
        return None, None
    return (after[0] - before[0], after[1] - before[1]), after


def turn(read_pos, side, seconds):
    before = read_pos()
    if before is None or not pso_input.hold(side, seconds):
        return None
    after = read_pos()
    if after is None:
        return None
    return (after[0] - before[0], after[1] - before[1])


def drive_to(read_pos, target, tolerance=9.0, max_seconds=45.0, log=None):
    started = time.time()
    travelled = 0.0
    turns = 0
    degrees_per_second = 120.0                                     # learned below, then refined
    learned = False
    vector, point = forward(read_pos, 0.35)
    if vector is None:
        return False, 0.0, None, 0.0, 0
    heading = heading_of(vector)
    while time.time() - started < max_seconds:
        point = read_pos()
        if point is None:
            break
        distance = math.dist(point, target)
        if distance <= tolerance:
            elapsed = time.time() - started
            return True, elapsed, distance, travelled / max(0.001, elapsed), turns
        want = heading_of((target[0] - point[0], target[1] - point[1]))
        error = angle_between(heading, want)
        if abs(error) <= 18.0:
            seconds = 1.7 if distance > 70 else (1.2 if distance > 30 else 0.6)
            vector, after = forward(read_pos, seconds)
            if vector is None:
                break
            moved = math.hypot(*vector)
            travelled += moved
            if moved > 2.0:
                new_heading = heading_of(vector)
                drift = angle_between(heading, new_heading)
                heading = new_heading
                if log is not None:
                    log(f"  forward {seconds:.1f}s: {distance:.0f} -> "
                        f"{math.dist(after, target):.0f} units, moved {moved:.0f}, drift {drift:+.0f} deg")
                if abs(drift) > 25.0:                               # the character slid along something: correct next loop
                    heading = new_heading
            else:
                time.sleep(0.15)
            continue
        side = "right" if error > 0 else "left"
        seconds = max(0.08, min(0.45, abs(error) / degrees_per_second))
        vector = turn(read_pos, side, seconds)
        turns += 1
        if vector is not None and math.hypot(*vector) > 0.5:
            # a turn moves the character on a small arc; its direction change is close to the arc's tangent, so estimate
            # the rotation from the direction we end up facing after the next forward probe instead of from the arc
            pass
        probe, _ = forward(read_pos, 0.22)
        if probe is not None and math.hypot(*probe) > 1.0:
            new_heading = heading_of(probe)
            changed = abs(angle_between(heading, new_heading))
            if seconds > 0.05 and changed > 1.0 and not learned:
                degrees_per_second = changed / seconds
                learned = True
            elif seconds > 0.05 and changed > 1.0:
                degrees_per_second = 0.7 * degrees_per_second + 0.3 * (changed / seconds)
            heading = new_heading
        if log is not None:
            log(f"  turn {side} {seconds:.2f}s for {error:+.0f} deg; heading now {heading:+.0f}")
    elapsed = time.time() - started
    point = read_pos()
    final = math.dist(point, target) if point else None
    return False, elapsed, final, travelled / max(0.001, elapsed), turns


if __name__ == "__main__":
    import map_exit as ME
    start = ME.read_pos()
    print("start:", tuple(round(v) for v in start))
    target = (float(sys.argv[1]), float(sys.argv[2])) if len(sys.argv) > 2 else (start[0] - 60, start[1])
    arrived, elapsed, final, speed, turns = drive_to(ME.read_pos, target, log=print)
    print(f"arrived={arrived} elapsed={elapsed:.1f}s final={None if final is None else round(final)} "
          f"speed={speed:.1f} units/s turns={turns}")
