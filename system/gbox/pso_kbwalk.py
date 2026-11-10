"""Walk a character with PSO's keyboard bindings -- the only input path that moves anyone (round 19).

Why this exists rather than using `pso_move.Walker`
---------------------------------------------------
`Walker` holds a *direction token* and trusts it to mean a world direction. On this build it does not: the keyboard
bindings are camera-relative and the camera turns with the character, so the same key moves a different way before and
after a turn. Measured with P1 in the Pioneer 2 lobby:

===========================================  ==========================================================
``up`` held 1.4 s                            ``(229.0, 254.0) -> (175.0, 254.0)`` -- world **-x**
``down`` held 1.4 s                          ``(222.1, 234.0)`` -- mostly **-z**
===========================================  ==========================================================

So this module **calibrates** first: it holds each key briefly, measures the world delta it produced, and then walks by
repeatedly picking the key whose calibrated vector best reduces the remaining distance. That makes it robust to the
camera rotating, to a stick being inverted, and to a title whose axes are not what its manual says.

The loop is closed: every step re-reads the position from RAM, so a step that does not help is visible immediately and
the walk stops instead of grinding into a wall.
"""
from __future__ import annotations

import math

KEYS = ("up", "down", "left", "right")


def _norm(dx: float, dz: float) -> tuple[float, float]:
    d = math.hypot(dx, dz)
    return (0.0, 0.0) if d < 1e-6 else (dx / d, dz / d)


def calibrate(read_pos, hold, *, seconds=0.7, keys=KEYS) -> dict:
    """Measure each key's world direction. ``hold(key, seconds)`` presses it for that long.

    Returns ``{key: (dx, dz)}`` of unit vectors (plus ``"scale"``: world units per second observed). Keys that produced no
    movement are kept with a zero vector so a caller can see that the binding is dead rather than guess.
    """
    origin = read_pos()
    if origin is None:
        raise RuntimeError("calibrate needs a live player position")
    out = {}
    total = 0.0
    measured = 0
    for key in keys:
        dx, dz, speed = _measure(key, hold, read_pos, seconds)
        if speed < 0.5:
            # Pressed against a wall, a key reads as dead even though its binding is fine: measure the opposite and
            # negate it, which is what the geometry actually is (i9-NUC: `left` calibrated to (0,0,0) against the
            # plaza railing and the walker then reported "no key points at the target").
            opposite = OPPOSITE.get(key)
            if opposite:
                odx, odz, ospeed = _measure(opposite, hold, read_pos, seconds)
                if ospeed >= 0.5:
                    dx, dz, speed = -odx, -odz, ospeed
        total += speed * seconds
        measured += 1
        ux, uz = _norm(dx, dz)
        out[key] = (ux, uz, speed)
    out["scale"] = total / max(measured * seconds, 1e-6)
    out["source"] = origin
    return out


OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}


def _measure(key, hold, read_pos, seconds) -> tuple[float, float, float]:
    """Hold one key and return (dx, dz, world units per second)."""
    before = read_pos()
    if before is None:
        raise RuntimeError("the player disappeared during calibration")
    hold(key, seconds)
    after = read_pos()
    if after is None:
        raise RuntimeError("the player disappeared during calibration")
    dx, dz = after[0] - before[0], after[1] - before[1]
    return dx, dz, math.hypot(dx, dz) / max(seconds, 1e-6)



def best_key(cal: dict, dx: float, dz: float) -> tuple[str | None, float]:
    """The calibrated key that moves furthest toward (dx, dz), with its alignment in [-1, 1]."""
    ux, uz = _norm(dx, dz)
    if ux == 0.0 and uz == 0.0:
        return None, 0.0
    best, best_dot = None, -2.0
    for key in KEYS:
        kx, kz, _speed = cal.get(key, (0.0, 0.0, 0.0))
        if kx == 0.0 and kz == 0.0:
            continue
        dot = kx * ux + kz * uz
        if dot > best_dot:
            best, best_dot = key, dot
    return best, best_dot


def best_keys(cal: dict, dx: float, dz: float, *, min_alignment: float = 0.35, max_keys: int = 2) -> list[str]:
    """The one or two calibrated keys to press together for (dx, dz).

    One key is rarely enough when the axes are camera-relative: on this build ``up`` is world -x and ``down`` is almost
    world -z, so a target diagonally away needs both or the walk zig-zags and never converges. Keys whose directions
    oppose each other are never combined.
    """
    ux, uz = _norm(dx, dz)
    if ux == 0.0 and uz == 0.0:
        return []
    scored = []
    for key in KEYS:
        kx, kz, _speed = cal.get(key, (0.0, 0.0, 0.0))
        if kx == 0.0 and kz == 0.0:
            continue
        scored.append((kx * ux + kz * uz, key, (kx, kz)))
    scored.sort(reverse=True)
    if not scored or scored[0][0] < min_alignment:
        return []
    chosen = [scored[0][1]]
    if len(scored) > 1 and scored[1][0] >= min_alignment:
        if scored[0][2][0] * scored[1][2][0] + scored[0][2][1] * scored[1][2][1] > -0.5:
            chosen.append(scored[1][1])
    return chosen[:max_keys]

def walk_to(read_pos, hold, target, *, cal=None, tolerance=8.0, max_steps=40,
            step_seconds=0.8, min_alignment=0.35) -> dict:
    """Walk to ``target`` (x, z) with closed-loop steps. Returns a report of every step.

    Stops on arrival, on a step that does not get closer (a wall, or the camera having turned the whole basis), or when
    the best key is misaligned with the target by more than ``min_alignment`` -- which is the signal to recalibrate
    rather than to keep pushing.
    """
    cal = cal or calibrate(read_pos, hold)
    start = read_pos()
    trail = []
    stuck = 0
    recalibrations = 0
    for i in range(max_steps):
        pos = read_pos()
        if pos is None:
            return {"ok": False, "why": "player disappeared", "steps": trail}
        dx, dz = target[0] - pos[0], target[1] - pos[1]
        remaining = math.hypot(dx, dz)
        trail.append({"at": (round(pos[0], 1), round(pos[1], 1)), "remaining": round(remaining, 1)})
        if remaining <= tolerance:
            return {"ok": True, "why": "arrived", "steps": trail, "start": start, "end": pos}
        keys = best_keys(cal, dx, dz, min_alignment=min_alignment)
        if not keys:
            return {"ok": False, "why": "no key points at the target; recalibrate",
                    "steps": trail, "start": start, "end": pos}
        # cover at most half the remaining distance per step, so the last steps are short and do not overshoot
        hold(keys, max(0.2, min(step_seconds, remaining / max(2.0 * cal.get("scale", 10.0), 1.0))))
        moved = read_pos()
        if moved is not None and distance(pos, moved) < 1.0:
            # a wall, a counter or a railing: step sideways before pushing again, and give up after a few tries
            stuck += 1
            trail[-1]["stuck"] = stuck
            if stuck == 2 and recalibrations < 2:
                # learn the axes again from where the character actually is: the camera turns with the character, so a
                # calibration taken a leg ago can be pointing the wrong way
                cal = calibrate(read_pos, hold)
                recalibrations += 1
                trail[-1]["recalibrated"] = recalibrations
                stuck = 0
                continue
            if stuck > 3:
                return {"ok": False, "why": f"stuck at {tuple(round(v, 1) for v in pos)}; a wall is in the way",
                        "steps": trail, "start": start, "end": pos}
            sideways = [k for k in KEYS if k not in keys][:2]
            if sideways:
                hold(sideways, 0.6)
        else:
            stuck = 0
    pos = read_pos()
    return {"ok": False, "why": f"gave up after {max_steps} steps", "steps": trail, "start": start, "end": pos}


def distance(a, b) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def walk_path(read_pos, hold, waypoints, *, tolerance=8.0, log=None, room_of=None, expect_room=None) -> dict:
    """Walk through ``waypoints`` in order, recalibrating between legs.

    The Pioneer 2 lobby is not an open field: its four doors are all in room 10 but the plaza railing sits between them,
    so one straight line stops halfway (round 20 walked 33 units and stalled on it). A route is a list of points the
    character has actually been seen to reach, and each leg is an ordinary closed-loop walk.

    ``room_of`` is a callable returning the character's current room id. Walking into a door changes it **with no button
    press** (round 21: room 10 -> 20 -> 10, the same coordinates working both ways), so every leg records the room
    before and after and a change is reported as a ``transition`` rather than treated as a stall. ``expect_room`` makes
    the route refuse to continue in a room it was not written for -- entity coordinates are per-room, so a waypoint from
    another room is meaningless.
    """
    log = log or (lambda _m: None)
    legs = []
    for i, point in enumerate(waypoints):
        if expect_room is not None and room_of is not None:
            room = room_of()
            if room is not None and room != expect_room:
                return {"ok": False, "why": f"leg {i + 1}: in room {room}, route expects {expect_room}", "legs": legs}
        room_before = room_of() if room_of else None
        cal = calibrate(read_pos, hold)
        leg = walk_to(read_pos, hold, point, cal=cal, tolerance=tolerance)
        room_after = room_of() if room_of else None
        entry = {"to": point, "ok": leg["ok"], "why": leg["why"], "end": leg["end"],
                 "room_before": room_before, "room_after": room_after}
        if room_before != room_after:
            entry["transition"] = True                 # a door was walked through, not a failure
        legs.append(entry)
        log(f"leg {i + 1} -> {point}: {'ok' if leg['ok'] else leg['why']}"
            + (f" [room {room_before} -> {room_after}]" if room_before != room_after else ""))
        if not leg["ok"]:
            return {"ok": False, "why": f"leg {i + 1}: {leg['why']}", "legs": legs}
    return {"ok": True, "why": "arrived", "legs": legs}
