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


# --- greedy walking: the controller that works with a camera that follows the character -------------------------
#
# Two fixed models were tried live and both failed (2026-11-10): treating each key as a constant world direction, and
# treating left/right as turns. The reason is the same -- PSO's camera follows the character, so the mapping from key to
# world direction changes while the character moves, and any calibration is stale within a second.
#
# `greedy_walk` models nothing. It keeps the LAST OBSERVED world delta for each key, presses whichever key's most recent
# delta best points at the target, and replaces that estimate with what actually happened. A rotating camera is then just
# a change in the estimates, absorbed on the next press.

def greedy_walk(read_pos, hold, target, *, keys=KEYS, tolerance=7.0, max_steps=40, step=0.55, log=None,
                push_through=False, pushes=2, push_distance=30.0, overshoot=0.0) -> dict:
    """Reach `target` by pressing one key at a time and re-measuring what each press did.

    Two options exist for doorways, because a door fails in two different ways:

    * ``overshoot`` -- after arriving at the target, keep walking that many units past it along the approach direction.
      Needed when the walk *succeeds* at the door's coordinate and therefore stops beside it (a doorway is a volume).
    * ``push_through=True`` -- when the walk is *stuck* (no key moves), re-aim ``push_distance`` past the goal and keep
      going, ``pushes`` times. Needed when the door's collision stops the character before the coordinate.
    """
    """Reach `target` by pressing one key at a time and re-measuring what each press did."""
    log = log or (lambda _m: None)
    effects = {}
    trail = []
    pushes_left = pushes
    overshoot_left = float(overshoot or 0.0)
    origin = read_pos() or (0.0, 0.0)
    for key in keys:                                   # bootstrap: every key gets a measured effect
        before = read_pos()
        hold(key, step)
        after = read_pos()
        if before is None or after is None:
            return {"ok": False, "why": "player disappeared", "steps": trail}
        dx, dz = after[0] - before[0], after[1] - before[1]
        if math.hypot(dx, dz) > 0.5:
            effects[key] = (dx, dz)
    if not effects:
        return {"ok": False, "why": "no key moved the character", "steps": trail}
    for _ in range(max_steps):
        pos = read_pos()
        if pos is None:
            return {"ok": False, "why": "player disappeared", "steps": trail}
        dx, dz = target[0] - pos[0], target[1] - pos[1]
        remaining = math.hypot(dx, dz)
        trail.append({"at": (round(pos[0], 1), round(pos[1], 1)), "remaining": round(remaining, 1)})
        if remaining <= tolerance:
            if overshoot_left:
                # arrived at the door's coordinate: a doorway is a volume, so keep going through it
                ux0, uz0 = _norm(target[0] - origin[0], target[1] - origin[1])
                if ux0 == 0.0 and uz0 == 0.0:
                    ux0, uz0 = _norm(pos[0] - origin[0], pos[1] - origin[1])
                if ux0 == 0.0 and uz0 == 0.0:
                    ux0, uz0 = 1.0, 0.0
                target = (target[0] + ux0 * overshoot_left, target[1] + uz0 * overshoot_left)
                trail[-1]["overshoot_to"] = (round(target[0], 1), round(target[1], 1))
                log(f"arrived at the door; overshooting to {trail[-1]['overshoot_to']}")
                overshoot_left = 0.0
                continue
            return {"ok": True, "why": "arrived", "steps": trail, "end": pos}
        ux, uz = _norm(dx, dz)
        order = sorted(effects.items(), key=lambda kv: -(kv[1][0] * ux + kv[1][1] * uz))
        moved = False
        for key, (ex, ez) in order:
            if ex * ux + ez * uz <= 0 and len(order) > 1:
                continue                               # this key last moved us away from the target
            seconds = max(0.2, min(0.8, remaining / max(math.hypot(ex, ez) / max(step, 1e-6), 1.0)))
            before = pos
            hold(key, seconds)
            after = read_pos()
            if after is None:
                return {"ok": False, "why": "player disappeared", "steps": trail}
            ddx, ddz = after[0] - before[0], after[1] - before[1]
            if math.hypot(ddx, ddz) > 0.5:
                effects[key] = (ddx, ddz)
                moved = True
                break
            effects[key] = (0.0, 0.0)                  # blocked just now: stop trusting it until it works
        if not moved:
            # A doorway in PSO is a volume you cross, not a point you stand on: a walk that stops *at* a door's
            # coordinates just stands next to it (round 26 walked through one only after being told to keep going past
            # the coordinate). So instead of failing, re-aim past the goal and keep walking.
            if push_through and pushes_left > 0 and effects:
                pushes_left -= 1
                ux0, uz0 = _norm(target[0] - origin[0], target[1] - origin[1])
                if ux0 == 0.0 and uz0 == 0.0:
                    ux0, uz0 = 1.0, 0.0
                beyond = (target[0] + ux0 * push_distance, target[1] + uz0 * push_distance)
                log(f"stuck: pushing through toward {tuple(round(v, 1) for v in beyond)}")
                trail.append({"at": (round(pos[0], 1), round(pos[1], 1)), "push_to":
                              (round(beyond[0], 1), round(beyond[1], 1))})
                # the effects are still valid directionally; keep them and walk to the point beyond the door
                target = beyond
                effect_keys = list(effects)
                effects = {k: effects[k] for k in effect_keys if effects[k] != (0.0, 0.0)} or effects
                continue
            log("every key failed to move the character")
            return {"ok": False, "why": "stuck: no key moved the character", "steps": trail, "end": read_pos()}
    return {"ok": False, "why": f"gave up after {max_steps} steps", "steps": trail, "end": read_pos()}
# --- the steering model (2026-11-10) ------------------------------------------------------------------------------
# PSO's keyboard bindings do not strafe: `left`/`right` TURN the character (and the camera), `up`/`down` move along
# the facing. A walker therefore points and advances, and it must re-measure the facing from what the last press
# actually did, because a turn overshoots and a wall can stop a leg. Tests: test_pso_steer.py.

STEER_PROBE_S = 0.25            # a forward probe: a nudge long enough to measure a direction
STEER_TURN_S = 0.5              # the left hold that measures the turn rate
STEER_MIN_SPEED = 0.5           # world units per second below which the forward binding is dead
STEER_MIN_TURN = 0.15           # rad/s below which a left/right hold is not a turn


def _signed_angle(a: tuple[float, float], b: tuple[float, float]) -> float:
    """The angle from facing `a` to `b` in radians, positive toward `left`."""
    dot = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1]))
    cross = a[0] * b[1] - a[1] * b[0]
    return math.atan2(cross, dot)


def _forward_probe(read_pos, hold, seconds: float) -> dict:
    """Hold `up` for `seconds`: the displacement's direction is the facing, its length over time the speed."""
    before = read_pos()
    if before is None:
        raise RuntimeError("the player disappeared while steering")
    hold("up", seconds)
    after = read_pos()
    if after is None:
        raise RuntimeError("the player disappeared while steering")
    dx, dz = after[0] - before[0], after[1] - before[1]
    return {"facing": _norm(dx, dz), "speed": math.hypot(dx, dz) / max(seconds, 1e-6),
            "moved": math.hypot(dx, dz), "pos": (after[0], after[1])}


def steer_calibrate(read_pos, hold, *, probe_s: float = STEER_PROBE_S, turn_s: float = STEER_TURN_S) -> dict:
    """Measure the steering model: forward speed, the facing, and the turn rate of a left hold.

    Returns {speed, turn_rate, facing, probe_s, turn_s}. Raises RuntimeError when the forward binding is dead or a
    left/right hold does not rotate the character - the tests pin both refusals, so a caller never walks blind.
    """
    first = _forward_probe(read_pos, hold, probe_s)
    if first["speed"] < STEER_MIN_SPEED:
        raise RuntimeError("the forward binding is dead: nothing moved when `up` was held")
    hold("left", turn_s)
    second = _forward_probe(read_pos, hold, probe_s)
    turn_rate = _signed_angle(first["facing"], second["facing"]) / max(turn_s, 1e-6)
    if abs(turn_rate) < STEER_MIN_TURN:
        raise RuntimeError("a left/right hold does not turn the character: this is not the steering model")
    return {"speed": second["speed"] if second["speed"] >= STEER_MIN_SPEED else first["speed"],
            "turn_rate": turn_rate, "facing": second["facing"], "probe_s": probe_s, "turn_s": turn_s,
            "source": first["pos"]}


def steer_walk(read_pos, hold, target, *, tolerance: float = 7.0, max_steps: int = 25,
               max_leg_s: float = 0.4, turn_threshold: float = 0.12, cal: dict | None = None) -> dict:
    """Point at the target and advance, re-measuring the facing after every press (the steering model).

    `left`/`right` turn toward the bearing to `target`, `up` advances by the remaining distance (capped at
    `max_leg_s`), and the next facing comes from the travel itself, so a turn overshoot or a blocked leg is corrected
    on the next step instead of pushed through. Returns {ok, end, steps, distance, facing, speed, turn_rate, trail}.
    """
    cal = cal or steer_calibrate(read_pos, hold)
    speed = max(float(cal["speed"]), STEER_MIN_SPEED)
    turn_rate = float(cal["turn_rate"])
    facing = tuple(cal["facing"])
    pos = read_pos()
    if pos is None:
        raise RuntimeError("steer_walk needs a live player position")
    trail = []
    for step in range(max_steps):
        pos = (pos[0], pos[1])
        remaining = distance(pos, target)
        if remaining <= tolerance:
            return {"ok": True, "end": pos, "steps": step, "distance": round(remaining, 1), "facing": facing,
                    "speed": round(speed, 1), "turn_rate": round(turn_rate, 2), "trail": trail}
        bearing = _norm(target[0] - pos[0], target[1] - pos[1])
        delta = _signed_angle(facing, bearing)
        if abs(delta) > turn_threshold:
            key = "left" if delta > 0 else "right"
            seconds = min(abs(delta) / max(abs(turn_rate), 1e-3), 3.0)
            hold(key, seconds)
            probe = _forward_probe(read_pos, hold, min(STEER_PROBE_S, max_leg_s))
            facing = probe["facing"] if probe["moved"] > 0.5 else facing
            pos = probe["pos"]
            trail.append({"step": step, "turn": key, "turn_s": round(seconds, 2), "pos": _round2(pos)})
            continue
        leg = min(remaining / speed, max_leg_s)
        before = read_pos()
        hold("up", leg)
        after = read_pos()
        if after is not None and before is not None:
            moved = _norm(after[0] - before[0], after[1] - before[1])
            if moved != (0.0, 0.0):
                facing = moved                       # the facing the press actually produced
            pos = (after[0], after[1])
        trail.append({"step": step, "forward_s": round(leg, 2), "pos": _round2(pos)})
    return {"ok": False, "why": f"gave up after {max_steps} steps", "end": _round2(pos), "trail": trail,
            "facing": facing, "speed": round(speed, 1), "turn_rate": round(turn_rate, 2),
            "distance": round(distance(pos, target), 1)}


def _round2(pos) -> tuple[float, float]:
    return (round(pos[0], 1), round(pos[1], 1))