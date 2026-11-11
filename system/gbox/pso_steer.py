"""CP17: from a world route to stick taps - the walker's second half.

`pso_walk.path` returns world waypoints. Walking them needs the inverse of "which way is forward": PSO moves the character
along the main stick relative to the camera, so a target direction becomes a stick direction only once the yaw convention is
known. This module keeps that convention an explicit argument, so the live calibration is one number, and the rest is
testable offline:

    keys = direction_taps((0.0, -1.0), 0.0, forward_at_zero=(0.0, -1.0))   # -> ("up",)

The stick names are the pad's own (`up`/`down`/`left`/`right`, which the controller config maps to the main stick), and a
diagonal is two of them.
"""
from __future__ import annotations

import math

STICKS = ("up", "down", "left", "right")


def _unit(direction: tuple[float, float]) -> tuple[float, float]:
    x, z = direction
    length = math.hypot(x, z)
    if length < 1e-9:
        return (0.0, 0.0)
    return x / length, z / length


def rotate(direction: tuple[float, float], degrees: float) -> tuple[float, float]:
    """Rotate a world (x, z) direction by `degrees` about +y (counter-clockwise looking down)."""
    radians = math.radians(degrees)
    cos, sin = math.cos(radians), math.sin(radians)
    x, z = direction
    return x * cos - z * sin, x * sin + z * cos


def direction_taps(target: tuple[float, float], yaw: float, *,
                   forward_at_zero: tuple[float, float] = (0.0, -1.0),
                   deadzone: float = 0.25) -> tuple[str, ...]:
    """The stick keys that push the character towards `target` when the camera/player yaw is `yaw` degrees.

    `forward_at_zero` is the world direction the stick's "up" means at yaw 0 - the one calibration number. A component below
    `deadzone` (after normalising) is dropped, so a mostly-forward diagonal is a single key and a 45-degree target is two.
    """
    forward = rotate(_unit(forward_at_zero), yaw)
    right = (-forward[1], forward[0])                  # forward rotated +90 degrees = screen right
    tx, tz = _unit(target)
    if tx == 0.0 and tz == 0.0:
        return ()
    along = tx * forward[0] + tz * forward[1]
    across = tx * right[0] + tz * right[1]
    keys = []
    if along > deadzone:
        keys.append("up")
    elif along < -deadzone:
        keys.append("down")
    if across > deadzone:
        keys.append("right")
    elif across < -deadzone:
        keys.append("left")
    return tuple(keys)


def route_taps(route: list[tuple[float, float]], position: tuple[float, float], yaw: float, *,
               forward_at_zero: tuple[float, float] = (0.0, -1.0), reach: float = 6.0) -> list[dict]:
    """The taps to follow `route` from `position`: [{to, direction, keys}], skipping waypoints already within `reach`.

    A tap segment is one waypoint's direction - the caller holds those keys for however long its own loop decides, then calls
    again with the new position, which is what a live walker does.
    """
    segments = []
    current = position
    for waypoint in route:
        dx, dz = waypoint[0] - current[0], waypoint[1] - current[1]
        if math.hypot(dx, dz) <= reach:
            current = waypoint          # already inside the reach: this leg is done, the next one starts here
            continue
        keys = direction_taps((dx, dz), yaw, forward_at_zero=forward_at_zero)
        if keys:
            segments.append({"to": waypoint, "direction": (dx, dz), "keys": keys})
        current = waypoint
    return segments


def describe(route: list[tuple[float, float]]) -> dict:
    """Length of a route in world units and how many waypoints it needs."""
    total = 0.0
    for (ax, az), (bx, bz) in zip(route, route[1:]):
        total += math.hypot(bx - ax, bz - az)
    return {"waypoints": len(route), "length": round(total, 2)}
