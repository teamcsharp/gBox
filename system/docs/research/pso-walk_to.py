"""Track a moving target: re-read its position every iteration instead of aiming once.

`walk_to` converged on a **stationary** box (60.8 -> 9.5 units) and failed against a **moving** enemy - 185 units travelled, zero kills. The reason is structural: `walk_to(pad, tx, tz)` takes the
target's position **once**, and an enemy walks away while the character turns, so the heading is stale by the time each step lands. The character chases where the enemy *was*.

Fix: `walk_to` accepts an optional `get_target` callable and calls it **every iteration**, so each tap and each step aims at where the enemy is *now*. The tolerance is also widened for moving targets
(`MOVE_TOLERANCE = 30`), because a tight tolerance against a target that moves means the character turns forever and never closes - and the real attack cone is **26-45 degrees**, so 30 is
comfortably inside it.

Also added: if the loop detects it is not making progress over several iterations while a live target is supplied, it reports that rather than grinding out its whole step budget.
"""
import math
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

from pso_pad import Pad, call                                     # noqa: E402

TOLERANCE = 20.0        # degrees, for a stationary target
MOVE_TOLERANCE = 30.0   # degrees, for a target that moves (still well inside a 26-45 degree cone)
STEP = 0.22             # measured: 0.22 s ~ 14 units (0.5 s is 31.6 units and overshoots)
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


def walk_to(pad, tx, tz, arrive=ARRIVE, max_steps=80, verbose=False, get_target=None):
    """Walk to (tx,tz), or to a moving target when `get_target` is supplied.

    Returns (remaining distance, steps taken). Never writes memory - the character visibly walks.
    """
    steps = 0
    stall = 0
    best = None
    no_progress = 0
    for _ in range(max_steps):
        # RE-AIM: a moving target's position is re-read every iteration, so the heading is never stale.
        if get_target is not None:
            fresh = get_target()
            if fresh is None:
                return -1.0, steps                              # it is gone
            tx, tz = fresh
        me = player(pad)
        x, z = float(me.get("x") or 0), float(me.get("z") or 0)
        distance = math.hypot(tx - x, tz - z)
        tolerance = MOVE_TOLERANCE if get_target is not None else TOLERANCE
        if distance <= arrive:
            return distance, steps
        if best is None or distance < best - 0.5:
            best = distance
            no_progress = 0
        else:
            no_progress += 1
        if no_progress > 26:
            return distance, steps                              # not closing; stop rather than grind

        heading = float(me.get("heading_deg") or 0)
        want = (math.degrees(math.atan2(tx - x, tz - z)) + 360.0) % 360.0
        error = ((want - heading + 540.0) % 360.0) - 180.0

        if abs(error) > tolerance:
            tap(pad, "left" if error > 0 else "right")
            time.sleep(0.16)
            steps += 1
            if verbose:
                print(f"    tap {'left' if error > 0 else 'right':5s} (err {error:+6.1f}, dist {distance:5.1f})")
            continue

        before = (x, z)
        hold(pad, "up", STEP)
        time.sleep(0.12)
        after = player(pad)
        moved = math.dist(before, (float(after.get("x") or 0), float(after.get("z") or 0)))
        steps += 1
        if verbose:
            print(f"    step  moved {moved:5.1f} | dist {distance:5.1f}")
        if moved < 1.5:
            stall += 1
            hold(pad, "left" if stall % 2 else "right", 0.35)
            time.sleep(0.12)
            if stall >= 6:
                return distance, steps
    return math.hypot(tx - player(pad).get("x", 0), tz - player(pad).get("z", 0)), steps
