"""Find the ways out of a room by walking a grid and watching the room id.

Pioneer 2's sub-areas are entered through **archways in the level**, not through door objects: only room 10 has
`TObjCityDoor_*` entities, and rooms 20/30/40/41 have none (docs/research/pso-gc-pioneer2-rooms.md). So the only way to
learn where the archways are is to walk and watch the `u16` at actor `+0x28`, which changes the instant the game moves the
character into another room.

This module is that probe, and it is deliberately boring: a list of points, a bounded walk to each, and a record of the
room the character ended in. A point that changes the room is an exit; the walk stops there, because continuing would be
stepping into a room the caller has not planned for.
"""
from __future__ import annotations


def grid(centre, *, spacing=60.0, rings=2) -> list[tuple[float, float]]:
    """Points around ``centre`` on a square grid, nearest first (so a probe finds close exits before far ones)."""
    cx, cz = centre
    out = []
    for ring in range(1, rings + 1):
        step = spacing * ring
        for dx in (-step, 0.0, step):
            for dz in (-step, 0.0, step):
                if dx == 0.0 and dz == 0.0:
                    continue
                out.append((cx + dx, cz + dz))
    out.sort(key=lambda p: (p[0] - cx) ** 2 + (p[1] - cz) ** 2)
    return out


def probe(read_pos, hold, room_of, points, *, walk_to=None, tolerance=8.0, max_steps=10) -> dict:
    """Walk each point and record the room it ended in; stop at the first room change.

    ``walk_to`` defaults to :func:`gbox.pso_kbwalk.greedy_walk`, which is the only walker that has worked live: it
    re-measures each key's last world effect instead of assuming a camera model. Passing a calibration-based walker here
    produces grid results that are noise (round 25: 16 points, none reached).

    Returns ``{ok, start_room, transitions: [...], visited: [...], why}``. ``ok`` means at least one exit was found --
    a probe that finds nothing is a result, not an error, so the caller gets both cases without an exception.
    """
    if walk_to is None:
        from .pso_kbwalk import greedy_walk as _greedy
        walk_to = _greedy
    start_room = room_of()
    visited, transitions = [], []
    for point in points:
        room_before = room_of()
        out = walk_to(read_pos, hold, point, tolerance=tolerance, max_steps=max_steps)
        room_after = room_of()
        entry = {"to": tuple(round(v, 1) for v in point), "why": out["why"],
                 "end": tuple(round(v, 1) for v in out["end"]) if out.get("end") else None,
                 "room_before": room_before, "room_after": room_after}
        visited.append(entry)
        if room_after != room_before:
            transitions.append(entry)
            return {"ok": True, "start_room": start_room, "transitions": transitions,
                    "visited": visited, "why": f"exit at {entry['to']}: room {room_before} -> {room_after}"}
    return {"ok": False, "start_room": start_room, "transitions": [], "visited": visited,
            "why": f"no exit found among {len(points)} points in room {start_room}"}
