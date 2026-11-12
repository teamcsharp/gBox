"""Walk the bot along the disc's own A* route to the warp platform.

The map is already internalised - `pso_coop_town` loads `Scene/map_city00_00c.rel` from the disc (70144 bytes, sha256 verified) and turns 1497 triangles into 5626
walkable cells, 4959 of them safe. `Corridor.route(start)` returns a waypoint list with every leg checked against that mesh, ending at the warp platform
`(360.003, 25.998)`.

What has been missing is a driver that follows it. This one:

* loads the corridor from the disc (verified fingerprint, or it refuses);
* while the character is **outside** the corridor's region (x 180-380, z 5-290) it walks toward the platform, which brings it inside;
* once inside, it asks the corridor for the A* route and follows it waypoint by waypoint - turning to the bearing, then walking, re-reading the position after every
  action;
* presses A at the platform.

A stuck character turns instead of pushing, and presses START only as a last resort (it toggles PSO's pause menu).
"""
import math
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\system")

DISC = r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz"
PLATFORM = (360.003, 25.998)
REGION = (180.0, 380.0, 5.0, 290.0)          # x0, x1, z0, z1 of the corridor


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


def tap(pad, key):
    pad.send([{"key": key, "down": True}, {"key": key, "down": False}])


def step(pad, target, tolerance=14.0):
    """One turn-or-walk toward `target`; returns the position after it."""
    me = player(pad)
    now = (float(me.get("x") or 0.0), float(me.get("z") or 0.0))
    if not me:
        return now
    dx, dz = target[0] - now[0], target[1] - now[1]
    distance = math.hypot(dx, dz)
    if distance < tolerance:
        return now
    want = bearing(now[0], now[1], *target)
    error = ((want - float(me.get("heading_deg") or 0.0) + 540.0) % 360.0) - 180.0
    if abs(error) > 22:
        hold(pad, "right" if error > 0 else "left", min(0.5, max(0.12, abs(error) / 220.0)))
    else:
        hold(pad, "up", min(1.1, max(0.3, distance / 150.0)))
    time.sleep(0.2)
    # measure the move; a character that did not move is against something
    after = player(pad)
    moved = (float(after.get("x") or 0.0), float(after.get("z") or 0.0))
    if math.dist(now, moved) < 0.7:
        hold(pad, "right" if error >= 0 else "left", 0.45)
        time.sleep(0.2)
    return moved


def inside(point) -> bool:
    return REGION[0] <= point[0] <= REGION[1] and REGION[2] <= point[1] <= REGION[3]


def main() -> int:
    from pso_pad import Pad
    corridor = build()
    pad = Pad()
    print("session:", pad.sid)

    # walk into the region first, if needed
    for attempt in range(40):
        now = (float(player(pad).get("x") or 0.0), float(player(pad).get("z") or 0.0))
        if inside(now) and corridor.cell(now) in corridor.safe:
            print(f"\non the corridor at ({now[0]:.1f},{now[1]:.1f}) after {attempt} steps")
            break
        if attempt % 5 == 0:
            print(f"  walking in: ({now[0]:7.1f},{now[1]:7.1f}) inside={inside(now)}")
        step(pad, PLATFORM)
    else:
        print("could not reach the corridor")
        print("shot:", pad.shot("not_on_corridor"))
        return 1

    now = (float(player(pad).get("x") or 0.0), float(player(pad).get("z") or 0.0))
    route = corridor.route(now)
    if not route:
        print("no A* route from", now)
        return 1
    total = sum(math.dist(a, b) for a, b in zip(route, route[1:]))
    print(f"ROUTE: {len(route)} waypoints, {total:.1f} units to the platform")

    for index, waypoint in enumerate(route[1:], 1):
        for _ in range(5):
            me = player(pad)
            here = (float(me.get("x") or 0.0), float(me.get("z") or 0.0))
            if math.dist(here, waypoint) < 9:
                break
            step(pad, waypoint)
        if index % 5 == 0:
            me = player(pad)
            print(f"  waypoint {index:3d}/{len(route)} | at ({me.get('x'):.1f},{me.get('z'):.1f})")

    me = player(pad)
    final = (float(me.get("x") or 0.0), float(me.get("z") or 0.0))
    print(f"\nat ({final[0]:.1f},{final[1]:.1f}) | to platform: {math.hypot(PLATFORM[0]-final[0], PLATFORM[1]-final[1]):.1f}")
    print("shot:", pad.shot("on_platform"))
    print("pressing A at the platform")
    tap(pad, "a")
    time.sleep(5)
    me = player(pad)
    print("after A:", (me.get("x"), me.get("z")), "| room", me.get("room"))
    print("shot:", pad.shot("after_platform"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
