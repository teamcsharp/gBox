"""Put the character inside the corridor region with a memory write, then plan the A* route.

The character is pinned in a corridor at `z -316`, room 40, moving only along x - a wall on the z axis that a reactive walker cannot escape without the room's geometry.
The corridor covers x 180-380, z 5-290, and an earlier write to the warp `(254, 0, 25)` was corrected by the game to `(232.4, -5.7)`: inside the x range and just below the
z range. So writes do place the character, they are merely corrected to a legal spot.

This tries a point well inside the region - `(260, 0, 120)` - reads where the game actually put it, and if that is a safe corridor cell, plans the route to the platform
and reports the waypoints. No walking here: the point is to prove the map-based route can be planned from a real in-game position.
"""
import math
import struct
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\system")

DISC = r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz"
CANDIDATES = [(260.0, 0.0, 120.0), (240.0, 0.0, 60.0), (300.0, 0.0, 80.0), (254.0, 0.0, 40.0)]


def build():
    from gbox.gcdisc import GCDisc
    from gbox.psomap import collision
    from gbox import pso_coop_town as town
    disc = GCDisc(DISC)
    try:
        data = disc.read(town.REL)
    finally:
        disc.f.close()
    return town.Corridor(collision(data))


def me(pad):
    from pso_pad import call
    state = call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}
    return state.get("player") or {}


def write_position(pad, point) -> str:
    from pso_pad import call
    player = me(pad)
    pointer = player.get("ptr")
    if not pointer:
        return "no player pointer"
    address = int(pointer, 16) + 0x38
    job = call("/api/jobs", {"tool": "write_memory", "require_worker": pad.worker,
                             "input": {"session_id": pad.sid, "address": address,
                                       "hex_bytes": struct.pack(">fff", *point).hex()}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    for _ in range(15):
        time.sleep(1)
        row = call("/api/jobs/" + job_id) if job_id else {}
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            return str(row.get("state"))
    return "timeout"


if __name__ == "__main__":
    from pso_pad import Pad
    corridor = build()
    pad = Pad()
    print("session:", pad.sid)

    for point in CANDIDATES:
        status = write_position(pad, point)
        time.sleep(1.5)
        player = me(pad)
        now = (float(player.get("x") or 0), float(player.get("z") or 0))
        cell = corridor.cell(now)
        safe = cell in corridor.safe
        print(f"  write {point} -> {status} | landed ({now[0]:7.1f},{now[1]:7.1f}) cell {cell} safe={safe}")
        if not safe:
            continue
        route = corridor.route(now)
        if not route:
            print("    no route from there")
            continue
        total = sum(math.dist(a, b) for a, b in zip(route, route[1:]))
        print(f"\nROUTE FROM THE DISC'S OWN MESH: {len(route)} waypoints, {total:.1f} units")
        for index, waypoint in enumerate(route[:12]):
            print(f"   {index:2d}: ({waypoint[0]:8.2f},{waypoint[1]:8.2f})")
        if len(route) > 12:
            print(f"   ... to the platform ({route[-1][0]:.2f},{route[-1][1]:.2f})")
        print("\nshot:", pad.shot("on_corridor_route"))
        break
    else:
        print("\nno candidate landed on a safe corridor cell")
        print("shot:", pad.shot("no_corridor_landing"))
