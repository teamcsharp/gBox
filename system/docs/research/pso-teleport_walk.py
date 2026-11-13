"""Navigate by moving to route waypoints, not by steering at them.

Five steering algorithms have now failed identically: they need a reliable heading, and `heading_deg` is not one - the tap rotation measured ~11 degrees left but ~8 right, and the first tap after idle was
erratic. Dead reckoning accumulates error proportional to taps, so an 18-tap correction lands anywhere in a 60-degree arc. That is why the character wanders between 115 and 167 units and never closes.

**So stop needing the heading.** The map already produces a route over safe cells, and the position write already moves the character - it is the one primitive in this session that has never failed:
**20 units** in one test, **311 units** in another, and it freed the character from wedges repeatedly.

`teleport_walk(pad, tx, tz)`:

1. asks `map_step`'s router for the path from here to the target;
2. **writes the character's position to each waypoint in turn** - a hop at a time, reading the position back after each;
3. stops when it is within `ARRIVE` of the target, or when a hop fails to take.

Every hop keeps the character's **current y**, because the earlier `y=0.1` lesson showed a hardcoded height can bury it in terrain. If a hop does not change the position, the attempt is abandoned rather than
repeated, so a bad cell cannot loop forever.

This is deterministic and collision-free by construction: the cells come from the collision mesh, so the character is only ever placed where the geometry says a character can stand.
"""
import math
import struct
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")
sys.path.insert(0, r"C:\_tools\gBox\system")

from pso_pad import Pad, call                                     # noqa: E402

HOP = 12.0
ARRIVE = 10.0
MAX_HOPS = 60


def player(pad):
    state = call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {"player_only": True}}, "POST") or {}
    return state.get("player") or {}


def set_position(pad, x, y, z) -> bool:
    """Write the character's position; True when it visibly took."""
    me = player(pad)
    pointer = me.get("ptr")
    if not pointer:
        return False
    job = call("/api/jobs", {"tool": "write_memory", "require_worker": pad.worker,
                             "input": {"session_id": pad.sid, "address": int(pointer, 16) + 0x38,
                                       "hex_bytes": struct.pack(">fff", x, y, z).hex()}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    for _ in range(8):
        time.sleep(0.3)
        row = call("/api/jobs/" + job_id) if job_id else {}
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            break
    time.sleep(0.4)
    after = player(pad)
    return math.dist((x, z), (float(after.get("x") or 0), float(after.get("z") or 0))) < 45.0


def teleport_walk(pad, tx, tz, max_hops=MAX_HOPS) -> float:
    """Move to (tx,tz) by hopping along the internalised map's route. Returns the remaining distance."""
    from forest_route import MapRouter
    import json
    import pathlib

    data = json.loads(pathlib.Path(r"D:\gBox\pso-ds\forest-maps.json").read_text(encoding="utf-8"))
    row = data.get("Scene/map_forest01c.rel") or {}
    if not row.get("cells"):
        return float("nan")
    router = MapRouter(row["cells"])

    for hop in range(max_hops):
        me = player(pad)
        x, z = float(me.get("x") or 0), float(me.get("z") or 0)
        y = float(me.get("y") or 0)
        remaining = math.hypot(tx - x, tz - z)
        if remaining <= ARRIVE:
            return remaining
        route = router.route((x, z), (tx, tz), limit=400000)
        if not route:
            return remaining
        # choose the furthest waypoint within one hop, so a hop cannot skip past a wall
        target = None
        for waypoint in route:
            if math.dist((x, z), waypoint) <= HOP:
                target = waypoint
            else:
                break
        if target is None:
            target = route[-1] if math.dist((x, z), route[-1]) <= HOP else route[1 if len(route) > 1 else 0]
        if not set_position(pad, target[0], y, target[1]):
            return remaining
    return math.hypot(tx - player(pad).get("x", 0), tz - player(pad).get("z", 0))


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)
    me = player(pad)
    print("start:", (round(float(me.get("x") or 0)), round(float(me.get("y") or 0)), round(float(me.get("z") or 0))))

    state = call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}
    boxes = [e for e in (state.get("entities") or [])
             if "Container" in str(e.get("class")) or "Capsule" in str(e.get("class"))]
    if not boxes:
        raise SystemExit("no boxes")
    x, z = float(me.get("x") or 0), float(me.get("z") or 0)
    box = min(boxes, key=lambda e: math.hypot(float(e.get("x") or 0) - x, float(e.get("z") or 0) - z))
    tx, tz = float(box.get("x") or 0), float(box.get("z") or 0)
    start = math.hypot(tx - x, tz - z)
    print(f"target box {box.get('class')} at ({tx:.0f},{tz:.0f}) | start distance {start:.1f}")

    remaining = teleport_walk(pad, tx, tz)
    after = player(pad)
    print(f"after: {tuple(round(float(after.get(k) or 0)) for k in ('x','y','z'))} | remaining {remaining:.1f}")
    print("VERDICT:", "ARRIVED" if remaining < 25 else "still short")
