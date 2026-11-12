"""Walk into the corridor region, then follow the disc's A* route to the warp platform.

Two facts from the last runs:

* the town corridor is the **east town** - x 180..380, z 5..290 (cells 72..152 by 2..116);
* writing the position near the warp lands the character at `(232.4, -5.7)`, which is inside the x range and **just below** the z range.

So the write is only a way to get close. After it, the character walks toward the platform `(360, 26)` with the tank-control loop until `cell(pos)` is a safe cell, and
from then on the disc's own A* takes over. Every step re-reads the position; a stuck character presses START (the pause menu) and turns.
"""
import math
import struct
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\system")

DISC = r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz"
PLATFORM = (360.003, 25.998)


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


def player(pad):
    from pso_pad import call
    state = call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}
    return state.get("player") or {}


def hold(pad, key, secs):
    pad.send([{"key": key, "down": True}])
    time.sleep(secs)
    pad.send([{"key": key, "down": False}])


def bearing(fx, fz, tx, tz):
    return (math.degrees(math.atan2(tx - fx, tz - fz)) + 360.0) % 360.0


def step_toward(pad, target, turns=2):
    me = player(pad)
    now = (float(me.get("x") or 0), float(me.get("z") or 0))
    if not now[0] and not now[1]:
        return now
    want = bearing(now[0], now[1], *target)
    error = ((want - float(me.get("heading_deg") or 0) + 540.0) % 360.0) - 180.0
    if abs(error) > 20:
        hold(pad, "right" if error > 0 else "left", min(0.55, max(0.15, abs(error) / 200.0)))
    else:
        hold(pad, "up", 0.9)
    time.sleep(0.2)
    return now


def main() -> int:
    from pso_pad import Pad, call
    corridor = build()
    pad = Pad()
    print("session:", pad.sid)

    for attempt in range(30):
        me = player(pad)
        now = (float(me.get("x") or 0), float(me.get("z") or 0))
        cell = corridor.cell(now)
        print(f"  {attempt:2d}: ({now[0]:7.1f},{now[1]:7.1f}) cell {cell} safe={cell in corridor.safe}")
        if cell in corridor.safe:
            print("\nON THE CORRIDOR - planning the A* route to the platform")
            break
        step_toward(pad, PLATFORM)
    else:
        print("\nnever reached a safe cell")
        print("shot:", pad.shot("not_on_corridor"))
        return 1

    route = corridor.route((float(player(pad).get('x') or 0), float(player(pad).get('z') or 0)))
    if not route:
        print("no route from a safe cell - unexpected")
        return 1
    total = sum(math.dist(a, b) for a, b in zip(route, route[1:]))
    print(f"ROUTE: {len(route)} waypoints, {total:.1f} units")
    for index, point in enumerate(route[:8]):
        print(f"  {index:2d}: ({point[0]:8.2f},{point[1]:8.2f})")

    for waypoint in route[1:]:
        for _ in range(8):
            me = player(pad)
            now = (float(me.get("x") or 0), float(me.get("z") or 0))
            if math.dist(now, waypoint) < 7:
                break
            step_toward(pad, waypoint)

    me = player(pad)
    final = (float(me.get("x") or 0), float(me.get("z") or 0))
    print(f"\nfinal: ({final[0]:.1f},{final[1]:.1f}) | to platform: {math.hypot(PLATFORM[0]-final[0], PLATFORM[1]-final[1]):.1f}")
    print("shot:", pad.shot("at_platform2"))
    print("pressing A to use the warp")
    pad.press("a")
    time.sleep(5)
    me = player(pad)
    print("after A:", (me.get("x"), me.get("z")), "| room", me.get("room"))
    print("shot:", pad.shot("after_platform_a"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
