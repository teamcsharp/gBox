"""Pure logic behind the operator's live controls: the turbo chord and route-to-mission conversion.

Kept separate from the scripts that talk to the pad and the plane so both can be tested without a controller or a game:

* `decide` - what the turbo chord should do for a given pad state (`on`, `off` or nothing), including the R1 mapping the INI implies;
* `simplify` - Douglas-Peucker over `(x, z)` waypoints;
* `route_mission` - a recorded walk as an `autoplay` mission of `navigate` steps, with its provenance.
"""
from __future__ import annotations

# Dolphin's GCPad1 binds `Buttons/Z = Shoulder R`, so the operator's R1 arrives as XInput's right bumper.
RIGHT_BUMPER = 0x0200
DPAD_UP = 0x0001
DPAD_DOWN = 0x0002
DPAD_LEFT = 0x0004
DPAD_RIGHT = 0x0008

TURBO_ON = "on"
TURBO_OFF = "off"


def decide(buttons: int, rt: float, turbo: bool, *, rt_threshold: float = 0.35) -> str | None:
    """The chord's action for this pad state: R1 (right bumper or analog trigger) plus a D-pad press.

    A rising edge is the caller's job: this returns `TURBO_OFF` only when the pad is already in turbo, so a held D-pad cannot flap.
    """
    r_held = bool(int(buttons) & RIGHT_BUMPER) or float(rt) / 255.0 >= rt_threshold
    if not r_held:
        return None
    up, down = bool(int(buttons) & DPAD_UP), bool(int(buttons) & DPAD_DOWN)
    if up and not turbo:
        return TURBO_ON
    if down and turbo:
        return TURBO_OFF
    return None


def simplify(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    """Douglas-Peucker on `(x, z)`; returns the endpoints unchanged for fewer than three points."""
    if len(points) < 3:
        return list(points)
    (x1, z1), (x2, z2) = points[0], points[-1]
    dx, dz = x2 - x1, z2 - z1
    norm = (dx * dx + dz * dz) ** 0.5 or 1.0
    worst, index = -1.0, 0
    for i in range(1, len(points) - 1):
        px, pz = points[i]
        distance = abs(dz * (px - x1) - dx * (pz - z1)) / norm
        if distance > worst:
            worst, index = distance, i
    if worst <= tolerance:
        return [points[0], points[-1]]
    return simplify(points[: index + 1], tolerance)[:-1] + simplify(points[index:], tolerance)


def route_mission(rows: list[dict], *, game_id: str, name: str, tolerance: float = 8.0,
                  source: str = "", radius: float = 12.0) -> dict:
    """A recorded walk as an autoplay mission: one `navigate` step per simplified waypoint, after the start point."""
    usable = [row for row in rows if row.get("x") is not None and row.get("z") is not None]
    if len(usable) < 4:
        raise ValueError("route too short to convert")
    waypoints = simplify([(float(r["x"]), float(r["z"])) for r in usable], tolerance)
    floors = sorted({int(r["floor"]) for r in usable if r.get("floor") is not None})
    steps = [{"op": "navigate", "to": [round(x, 1), round(z, 1)], "radius": radius} for x, z in waypoints[1:]]
    return {"name": name, "game_id": game_id,
            "objective": "Walk the route the operator walked (recorded from their own play)",
            "policy": "learned-from-operator-route",
            "provenance": {"source": source, "samples": len(usable), "waypoints": len(waypoints),
                           "tolerance": tolerance, "floors": floors},
            "steps": steps}
