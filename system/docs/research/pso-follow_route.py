"""Get the player onto the corridor, then follow its A* route to the warp platform.

The corridor is the **east town** (`i` in 72..152, `j` in 2..116 -> x 180..380, z 5..290), and the wandering bot took the character to `(-340.8, -153.5)`, outside it, so
`route()` had nothing to say.

But writing the position to the warp `(254, 0, 25)` was earlier **corrected by the game's collision to `(184.7, 53.3)`** - which is inside the corridor. So the write is
used as a way to re-enter the region, not as a teleport: write, then read where the game actually put the character, and only then plan.

From there the route is the disc's own A*: follow waypoint by waypoint, turning to the bearing and walking, re-reading the position after each leg, with a stuck check
that presses START (the pause menu) and turns.
"""
import json
import math
import struct
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\system")

DISC = r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz"
PLATFORM = (360.003, 25.998)


def build_corridor():
    from gbox.gcdisc import GCDisc
    from gbox.psomap import collision
    from gbox import pso_coop_town as town
    disc = GCDisc(DISC)
    try:
        data = disc.read(town.REL)
    finally:
        disc.f.close()
    return town.Corridor(collision(data)), town


def player(pad) -> dict:
    from pso_pad import call
    state = call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}
    return state.get("player") or {}


def hold(pad, key: str, secs: float) -> None:
    pad.send([{"key": key, "down": True}])
    time.sleep(secs)
    pad.send([{"key": key, "down": False}])


def bearing(fx: float, fz: float, tx: float, tz: float) -> float:
    return (math.degrees(math.atan2(tx - fx, tz - fz)) + 360.0) % 360.0


def main() -> int:
    from pso_pad import Pad, call
    corridor, town = build_corridor()
    pad = Pad()
    print("session:", pad.sid)

    me = player(pad)
    start = (float(me.get("x") or 0), float(me.get("z") or 0))
    print("player:", start, "| cell", corridor.cell(start), "| in safe:", corridor.cell(start) in corridor.safe)

    if corridor.cell(start) not in corridor.safe:
        print("\noutside the corridor - writing the warp position so collision re-places the character")
        pointer = me.get("ptr")
        address = int(pointer, 16) + 0x38
        payload = struct.pack(">fff", 254.0, 0.0, 25.0).hex()
        job = call("/api/jobs", {"tool": "write_memory", "require_worker": pad.worker,
                                 "input": {"session_id": pad.sid, "address": address,
                                           "hex_bytes": payload}}, "POST")
        job_id = job.get("id") if isinstance(job, dict) else None
        for _ in range(10):
            time.sleep(1.5)
            row = call("/api/jobs/" + job_id) if job_id else {}
            if row.get("state") in ("succeeded", "failed", "cancelled"):
                print("  write:", row.get("state"), str(row.get("error"))[:80])
                break
        time.sleep(2)
        me = player(pad)
        start = (float(me.get("x") or 0), float(me.get("z") or 0))
        print("  now at:", start, "| cell", corridor.cell(start), "| in safe:", corridor.cell(start) in corridor.safe)

    if corridor.cell(start) not in corridor.safe:
        recovered = corridor.recover(start)
        print("  recovery:", recovered[:2] if recovered else None)
        if recovered:
            start = recovered[-1]
        else:
            print("\nstill outside the corridor; a walk-in is needed first")
            return 1

    route = corridor.route(start)
    if not route:
        print("\nno A* route from", start)
        return 1
    print(f"\nROUTE: {len(route)} waypoints, {sum(math.dist(a, b) for a, b in zip(route, route[1:])):.1f} units")
    for index, point in enumerate(route[:10]):
        print(f"  {index:2d}: ({point[0]:8.2f}, {point[1]:8.2f})")

    # follow it
    for waypoint in route[1:]:
        for attempt in range(6):
            me = player(pad)
            now = (float(me.get("x") or 0), float(me.get("z") or 0))
            dx, dz = waypoint[0] - now[0], waypoint[1] - now[1]
            distance = math.hypot(dx, dz)
            if distance < 6:
                break
            target_heading = bearing(now[0], now[1], *waypoint)
            error = ((target_heading - float(me.get("heading_deg") or 0) + 540.0) % 360.0) - 180.0
            if abs(error) > 20:
                hold(pad, "right" if error > 0 else "left", min(0.5, max(0.15, abs(error) / 220.0)))
            else:
                hold(pad, "up", min(1.2, max(0.3, distance / 140.0)))
            time.sleep(0.2)
        else:
            print("  could not reach", waypoint, "- pressing START to clear any menu")
            pad.send([{"key": "start", "down": True}, {"key": "start", "down": False}])
            time.sleep(1)

    me = player(pad)
    final = (float(me.get("x") or 0), float(me.get("z") or 0))
    print("\nfinal:", final, "| distance to platform:", round(math.hypot(PLATFORM[0] - final[0], PLATFORM[1] - final[1]), 1))
    print("shot:", pad.shot("at_platform"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
