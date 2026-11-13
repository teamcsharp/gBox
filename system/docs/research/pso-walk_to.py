"""Walk to a target: one tap at a time, measuring after every single tap.

The operator requires the character to **visibly walk** - no position writes - so teleport-walking is out and steering has to work.

Every previous steering attempt failed for the same reason, and it is now precisely understood:

* a direction press is a **fixed rotation, not a rate** - about **11° per tap left, ~8° right**, ~46° for a 0.15-0.45 s hold;
* a forward hold of **0.5 s walks ~10 units**; a **1.0 s hold walks 0**.

The fatal flaw was **batching**: `taps = round(|error| / 10)` then sending them all blind. Each tap is 8-11° rather than exactly 10°, so an 18-tap batch lands up to 60° off and the next correction
overshoots the other way - which is exactly the observed zigzag between 115 and 167 units.

**`walk_to` never batches.** It taps **once**, re-reads `heading_deg`, re-computes the error, and repeats. Each step is small and the error is re-measured, so nothing accumulates. When the heading is
within `TOLERANCE` it takes **one 0.5 s forward step** and re-measures position. A blocked forward step (measured 0 movement) triggers a short sidestep, which the freeze probe showed is the correct
response - `left` alone covered 90 units when `up` was blocked.

The loop reports its own progress so a failure is visible as a number rather than as "it wandered".
"""
import math
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

from pso_pad import Pad, call                                     # noqa: E402

TOLERANCE = 20.0        # degrees; taps settle at ~10 deg so inside this we can step
STEP = 0.22             # measured: 0.5s walks 31.6 units, so 0.22s is ~14 units - short enough not to overshoot
ARRIVE = 12.0           # units; the real PMT reach is 13-30, so this is inside attack range
DIRECTIONS = ("up", "down", "left", "right")


def state(pad):
    return call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {"player_only": True}}, "POST") or {}


def player(pad):
    return state(pad).get("player") or {}


def tap(pad, key):
    pad.send([{"key": key, "down": True}, {"key": key, "down": False}])


def hold(pad, key, seconds):
    pad.send([{"key": key, "down": True}])
    time.sleep(seconds)
    pad.send([{"key": k, "down": False} for k in DIRECTIONS])


def walk_to(pad, tx, tz, arrive=ARRIVE, max_steps=80, verbose=False):
    """Walk to (tx,tz). Returns (remaining distance, steps taken). Never writes memory."""
    steps = 0
    stall = 0
    for _ in range(max_steps):
        me = player(pad)
        x, z = float(me.get("x") or 0), float(me.get("z") or 0)
        distance = math.hypot(tx - x, tz - z)
        if distance <= arrive:
            return distance, steps
        heading = float(me.get("heading_deg") or 0)
        want = (math.degrees(math.atan2(tx - x, tz - z)) + 360.0) % 360.0
        error = ((want - heading + 540.0) % 360.0) - 180.0

        if abs(error) > TOLERANCE:
            # ONE tap, then measure again. Batching was the bug.
            tap(pad, "left" if error > 0 else "right")
            time.sleep(0.16)
            steps += 1
            if verbose:
                print(f"    tap {'left' if error > 0 else 'right':5s} (err {error:+6.1f})")
            continue

        before = (x, z)
        hold(pad, "up", STEP)
        time.sleep(0.12)
        after = player(pad)
        moved = math.dist(before, (float(after.get("x") or 0), float(after.get("z") or 0)))
        steps += 1
        if verbose:
            print(f"    step  moved {moved:5.1f} | dist {math.hypot(tx - float(after.get('x') or 0), tz - float(after.get('z') or 0)):5.1f}")
        if moved < 1.5:
            # forward is blocked - sidestep, which the freeze probe proved is the right answer
            stall += 1
            hold(pad, "left" if stall % 2 else "right", 0.35)
            time.sleep(0.12)
            if stall >= 6:
                return distance, steps
    return math.hypot(tx - player(pad).get("x", 0), tz - player(pad).get("z", 0)), steps


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)
    me = player(pad)
    print("start:", (round(float(me.get("x") or 0)), round(float(me.get("z") or 0))), "| heading", round(float(me.get("heading_deg") or 0)))

    full = call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}
    boxes = [e for e in (full.get("entities") or [])
             if "Container" in str(e.get("class")) or "Capsule" in str(e.get("class"))]
    if not boxes:
        raise SystemExit("no boxes to walk to")
    x, z = float(me.get("x") or 0), float(me.get("z") or 0)
    box = min(boxes, key=lambda e: math.hypot(float(e.get("x") or 0) - x, float(e.get("z") or 0) - z))
    tx, tz = float(box.get("x") or 0), float(box.get("z") or 0)
    start = math.hypot(tx - x, tz - z)
    print(f"target box at ({tx:.0f},{tz:.0f}) | distance {start:.1f}\n")

    remaining, steps = walk_to(pad, tx, tz, verbose=True)
    print(f"\nafter: {tuple(round(float(player(pad).get(k) or 0)) for k in ('x','z'))} | remaining {remaining:.1f} | steps {steps}")
    print("VERDICT:", "WALKED INTO RANGE" if remaining <= ARRIVE + 6 else "did not arrive")
