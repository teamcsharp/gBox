"""Empirical steering: walk to a point by measuring what each direction actually does right now.

The calibrated walkers drift because a key->world table goes stale as the camera turns with the character. This measures each of the four
directions with a short hold immediately before choosing, then strides with the key whose measured displacement points closest at the
target. The measurement is taken in the same breath as the stride, so it cannot be stale.

Public API:
    measure(hold, read_pos, seconds)            -> {"up": (dx, dz), ...}
    step_toward(hold, read_pos, target, ...)    -> (arrived, steps, distance, reason)
"""
import math


def _unit(dx, dz):
    length = math.hypot(dx, dz)
    return (dx / length, dz / length) if length > 1e-6 else (0.0, 0.0)


def distance(point, target):
    return math.hypot(point[0] - target[0], point[1] - target[1])


def measure(hold, read_pos, seconds=0.3, keys=("up", "down", "left", "right")):
    """Displacement produced by each direction right now, as {(key): (dx, dz)}."""
    vectors = {}
    for key in keys:
        before = read_pos()
        if before is None:
            continue
        hold(key, seconds)
        after = read_pos()
        if after is None:
            continue
        vectors[key] = (after[0] - before[0], after[1] - before[1])
    return vectors


def step_toward(hold, read_pos, target, tolerance=9.0, max_steps=40, probe=0.3, stride=0.7,
                on_stuck=None, log=None):
    """Walk to `target` with per-step measurement. Returns (arrived, steps, distance, reason)."""
    started_distance = None
    best = None
    for step_index in range(max_steps):
        point = read_pos()
        if point is None:
            return False, step_index, None, "no position"
        current = distance(point, target)
        if started_distance is None:
            started_distance = current
        if best is None or current < best:
            best = current
        if current <= tolerance:
            return True, step_index, current, "arrived"
        bearing = _unit(target[0] - point[0], target[1] - point[1])
        vectors = measure(hold, read_pos, seconds=probe)
        best_key, best_align, best_length = None, -2.0, 0.0
        for key, (dx, dz) in vectors.items():
            length = math.hypot(dx, dz)
            if length < 1.0:
                continue
            align = (dx / length) * bearing[0] + (dz / length) * bearing[1]
            if align > best_align:
                best_key, best_align, best_length = key, align, length
        if log is not None:
            log(f"  step {step_index}: {current:.0f} units, key={best_key} align={best_align:.2f} "
                f"moved={best_length:.0f}")
        if best_key is None:
            if on_stuck is not None and on_stuck():
                continue
            return False, step_index, current, "no direction moves"
        hold(best_key, max(0.22, min(0.8, current / 70.0)))       # shorter strides as the gap closes
    point = read_pos()
    return False, max_steps, (distance(point, target) if point else None), "step limit"


if __name__ == "__main__":
    import sys

    sys.path.insert(0, r"C:\_tools\gBox\.tmp")
    import session as S

    def read_pos():
        import struct
        pointer = int.from_bytes(S.read_memory(0x8050EA10, 4), "big")
        if not pointer:
            return None
        blob = S.read_memory(pointer + 0x38, 12)
        return (struct.unpack(">fff", blob)[0], struct.unpack(">fff", blob)[2]) if len(blob) == 12 else None

    import game_input as G

    def hold(key, seconds):
        G.send([{"key": key, "down": True}])
        import time
        time.sleep(seconds)
        G.send([{"key": key, "down": False}])
        import time as t
        t.sleep(0.05)

    target = (float(sys.argv[1]), float(sys.argv[2])) if len(sys.argv) > 2 else (-60.0, 210.0)
    print("start:", read_pos(), "target:", target)
    arrived, steps, final, reason = step_toward(hold, read_pos, target, max_steps=12, log=print)
    print(f"arrived={arrived} steps={steps} final={final:.0f} reason={reason}" if final else reason)
