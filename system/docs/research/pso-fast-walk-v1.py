"""Fast walking: calibrate the four directions ONCE, stride long, and re-calibrate only when a stride contradicts the map.

The slow controller measures all four directions before every stride (~2 s of probing for every 0.7 s of walking, about 5 units/s). This
does the opposite:
  * one calibration pass (4 x 0.25 s) builds a key -> world-vector table;
  * each stride is long (1.2-1.6 s) and uses the table directly, no probing;
  * after a stride the actual displacement is compared with what the table predicted; if the character did not move anything like the
    prediction (the camera turned with the character, or terrain blocked it) the table is rebuilt once and the stride repeated.

Expected throughput is 20-30 units/s against the old ~5, and the correctness check keeps it honest: the caller gets the arrival result and
the achieved speed, so a fast run that lies about geometry cannot pass unnoticed.

Every key goes through pso_input (operator lock).
"""
import math
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import pso_input                                                   # noqa: E402


def unit(dx, dz):
    length = math.hypot(dx, dz)
    return (dx / length, dz / length) if length > 1e-6 else (0.0, 0.0)


def calibrate(read_pos, probe=0.25, keys=("up", "down", "left", "right")):
    table = {}
    for key in keys:
        before = read_pos()
        if before is None:
            continue
        if not pso_input.hold(key, probe):
            return table
        after = read_pos()
        if after is None:
            continue
        vector = (after[0] - before[0], after[1] - before[1])
        if math.hypot(*vector) > 1.0:
            table[key] = vector
    return table


def best_key(table, bearing):
    best, best_align = None, -2.0
    for key, (dx, dz) in table.items():
        length = math.hypot(dx, dz)
        if length < 1.0:
            continue
        align = (dx / length) * bearing[0] + (dz / length) * bearing[1]
        if align > best_align:
            best, best_align = key, align
    return best, best_align


def walk_to(read_pos, target, tolerance=9.0, max_seconds=60.0, log=None):
    """Fast walk. Returns (arrived, elapsed, distance, speed_units_per_s, recalibrations)."""
    started = time.time()
    travelled = 0.0
    last = read_pos()
    if last is None:
        return False, 0.0, None, 0.0, 0
    table = calibrate(read_pos)
    recalibrations = 0
    if log is not None:
        log(f"  calibrated {len(table)} directions: "
            f"{ {k: (round(v[0]), round(v[1])) for k, v in table.items()} }")
    while time.time() - started < max_seconds:
        point = read_pos()
        if point is None:
            break
        distance = math.dist(point, target)
        if distance <= tolerance:
            elapsed = time.time() - started
            return True, elapsed, distance, travelled / max(0.001, elapsed), recalibrations
        bearing = unit(target[0] - point[0], target[1] - point[1])
        if not table:
            table = calibrate(read_pos)
            recalibrations += 1
            if not table:
                break
        key, align = best_key(table, bearing)
        if key is None:
            break
        stride = 1.5 if distance > 40 else 1.0
        if align < 0.45:                                           # the table points poorly: step shorter and re-calibrate
            stride = 0.5
        before = point
        if not pso_input.hold(key, stride):
            time.sleep(0.2)
            continue
        after = read_pos()
        if after is None:
            break
        moved = math.dist(before, after)
        travelled += moved
        predicted = table[key]
        pred_norm = unit(*predicted)
        actual_norm = unit(after[0] - before[0], after[1] - before[1])
        divergence = math.degrees(math.acos(max(-1.0, min(1.0, pred_norm[0] * actual_norm[0] + pred_norm[1] * actual_norm[1])))) \
            if moved > 2 else 180.0
        if log is not None:
            log(f"  stride {key} {stride:.1f}s: {distance:.0f} -> {math.dist(after, target):.0f} units, "
                f"moved {moved:.0f}, divergence {divergence:.0f} deg")
        if moved < 2.0 or divergence > 50.0:
            table = calibrate(read_pos)
            recalibrations += 1
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
