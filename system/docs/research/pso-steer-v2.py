"""Empirical steering v2: measure, stride, and LEARN from the result of the last stride.

v1 measured the four directions and strode with the best-aligned one, which arrived on a 123-unit leg but sometimes chose a direction that
increased the distance. v2 adds:
  * a regression guard - a direction that increased the distance on the previous stride is skipped this step;
  * stall re-planning - when nothing moves, probe again with longer holds and tap B (a menu or dialog freezes movement);
  * an arrival window that also stops when the distance is small and no longer improving.
Returns (arrived, steps, distance, reason) with reasons: arrived, step limit, stalled, lost position.
"""
import math


def _unit(dx, dz):
    length = math.hypot(dx, dz)
    return (dx / length, dz / length) if length > 1e-6 else (0.0, 0.0)


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def measure(hold, read_pos, seconds=0.3, keys=("up", "down", "left", "right")):
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


def step_toward(hold, read_pos, target, tolerance=9.0, max_steps=40, probe=0.3, log=None,
                on_stuck=None, stall_limit=3, stagnant_limit=4):
    position = read_pos()
    if position is None:
        return False, 0, None, "lost position"
    best_distance = distance(position, target)
    bad_directions = {}
    stalls = 0
    stagnant = 0
    for step in range(max_steps):
        position = read_pos()
        if position is None:
            return False, step, best_distance, "lost position"
        current = distance(position, target)
        if current <= tolerance:
            return True, step, current, "arrived"
        if current < best_distance - 1.0:
            best_distance = current
            stagnant = 0
            bad_directions.clear()
        else:
            stagnant += 1
            if stagnant >= stagnant_limit and current <= max(tolerance * 2.0, 18.0):
                return True, step, current, "arrived (stagnant near target)"
        bearing = _unit(target[0] - position[0], target[1] - position[1])
        vectors = measure(hold, read_pos, seconds=probe)
        chosen, chosen_align, chosen_length = None, -2.0, 0.0
        for key, (dx, dz) in vectors.items():
            length = math.hypot(dx, dz)
            if length < 1.0 or bad_directions.get(key):
                continue
            align = (dx / length) * bearing[0] + (dz / length) * bearing[1]
            if align > chosen_align:
                chosen, chosen_align, chosen_length = key, align, length
        if log is not None:
            log(f"  step {step}: {current:.0f} units, key={chosen} align={chosen_align:.2f} "
                f"moved={chosen_length:.0f} bad={sorted(bad_directions)}")
        if chosen is None:
            stalls += 1
            if on_stuck is not None and on_stuck(stalls):
                continue
            if stalls >= stall_limit:
                return False, step, current, "stalled"
            continue
        stalls = 0
        before = position
        stride = max(0.22, min(0.8, current / 70.0))
        if chosen_align < 0.35:                                    # poorly aligned: small corrective step
            stride = max(0.18, stride * 0.6)
        hold(chosen, stride)
        after = read_pos()
        if after is not None and distance(after, target) > current + 2.0:
            bad_directions[chosen] = True                          # this direction made it worse
    position = read_pos()
    return False, max_steps, (distance(position, target) if position else None), "step limit"


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
        if len(blob) != 12:
            return None
        x, y, z = struct.unpack(">fff", blob)
        return (x, z)

    import time as _time

    import game_input as G

    def hold(key, seconds):
        G.send([{"key": key, "down": True}])
        _time.sleep(seconds)
        G.send([{"key": key, "down": False}])
        _time.sleep(0.05)

    def tap_b(_stalls):
        G.send([{"key": "b", "down": True}, {"key": "b", "down": False}])
        _time.sleep(0.3)
        return True

    if len(sys.argv) > 2:
        target = (float(sys.argv[1]), float(sys.argv[2]))
        print("start:", read_pos(), "target:", target)
        result = step_toward(hold, read_pos, target, max_steps=18, log=print, on_stuck=tap_b)
        print("result:", result)
    else:
        # success-rate trial: four targets around the character, each about 45-55 units away
        start = read_pos()
        print("start:", tuple(round(v) for v in start))
        offsets = ((45, 10), (-40, 35), (-30, -45), (35, -40))
        wins = 0
        for index, (dx, dz) in enumerate(offsets):
            target = (start[0] + dx, start[1] + dz)
            print(f"\ntrial {index + 1}: target {tuple(round(v) for v in target)}")
            arrived, steps, final, reason = step_toward(hold, read_pos, target, tolerance=9.0, max_steps=12,
                                                        log=print, on_stuck=tap_b)
            print(f"  -> arrived={arrived} steps={steps} final={final:.0f} {reason}" if final else reason)
            wins += 1 if arrived else 0
            start = read_pos()
        print(f"\narrivals: {wins}/{len(offsets)}")
