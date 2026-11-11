"""Fast walking v2: keep the direction table fresh for free by rotating it after every stride.

v1 calibrated once and went stale - after a long stride the camera had turned with the character, so the cached "down" vector pointed where
the character no longer faced and a 1.5 s stride went 130 degrees wrong.

v2 uses the stride itself as the calibration: the displacement a stride actually produced is the true current vector for the key that was
held, and every other key rotates by the same angle (the camera is rigid with the character). No extra probing, so the table stays exact
for free, and only a blocked stride (no movement) triggers a full re-calibration.

Measured target: long strides when far, short when correcting, everything else unchanged from v1's interface
(arrived, elapsed, distance, units_per_second, recalibrations).
"""
import math
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import pso_input                                                   # noqa: E402


def unit(dx, dz):
    length = math.hypot(dx, dz)
    return (dx / length, dz / length) if length > 1e-6 else (0.0, 0.0)


def angle_of(vector):
    return math.atan2(vector[1], vector[0])


def rotate(vector, radians):
    cos, sin = math.cos(radians), math.sin(radians)
    return (vector[0] * cos - vector[1] * sin, vector[0] * sin + vector[1] * cos)


def calibrate(read_pos, probe=0.22, keys=("up", "down", "left", "right")):
    table = {}
    for key in keys:
        before = read_pos()
        if before is None or not pso_input.hold(key, probe):
            continue
        after = read_pos()
        if after is None:
            continue
        vector = (after[0] - before[0], after[1] - before[1])
        if math.hypot(*vector) > 1.0:
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


def walk_to(read_pos, target, tolerance=9.0, max_seconds=60.0, log=None):
    started = time.time()
    travelled = 0.0
    recalibrations = 0
    table = calibrate(read_pos)
    if log is not None:
        log(f"  calibrated {len(table)}: { {k: (round(v[0]), round(v[1])) for k, v in table.items()} }")
    if not table:
        return False, 0.0, None, 0.0, 1
    while time.time() - started < max_seconds:
        point = read_pos()
        if point is None:
            break
        distance = math.dist(point, target)
        if distance <= tolerance:
            elapsed = time.time() - started
            return True, elapsed, distance, travelled / max(0.001, elapsed), recalibrations
        bearing = unit(target[0] - point[0], target[1] - point[1])
        key, align = best_key(table, bearing)
        if key is None:
            break
        stride = 1.6 if distance > 60 else (1.1 if distance > 25 else 0.6)
        if align < 0.5:
            stride = min(stride, 0.45)                             # poorly aligned: short corrective step
        predicted = table[key]
        before = point
        if not pso_input.hold(key, stride):
            time.sleep(0.2)
            continue
        after = read_pos()
        if after is None:
            break
        actual = (after[0] - before[0], after[1] - before[1])
        moved = math.hypot(*actual)
        travelled += moved
        if moved < 2.0:                                            # blocked: the table tells us nothing
            table = calibrate(read_pos)
            recalibrations += 1
            if log is not None:
                log(f"  stride {key} blocked; re-calibrated")
            continue
        # free calibration: the stride's own displacement is the key's true vector, everything else rotates with it
        delta = angle_of(actual) - angle_of(predicted)
        table = {k: (actual if k == key else rotate(v, delta)) for k, v in table.items()}
        if log is not None:
            log(f"  stride {key} {stride:.1f}s: {distance:.0f} -> {math.dist(after, target):.0f} units, "
                f"moved {moved:.0f} (table refreshed, delta {math.degrees(delta):+.0f} deg)")
    elapsed = time.time() - started
    point = read_pos()
    final = math.dist(point, target) if point else None
    return False, elapsed, final, travelled / max(0.001, elapsed), recalibrations


if __name__ == "__main__":
    import map_exit as ME
    start = ME.read_pos()
    print("start:", tuple(round(v) for v in start))
    target = (float(sys.argv[1]), float(sys.argv[2])) if len(sys.argv) > 2 else (start[0] - 60, start[1])
    arrived, elapsed, final, speed, recal = walk_to(ME.read_pos, target, log=print)
    print(f"arrived={arrived} elapsed={elapsed:.1f}s final={None if final is None else round(final)} "
          f"speed={speed:.1f} units/s recalibrations={recal}")
