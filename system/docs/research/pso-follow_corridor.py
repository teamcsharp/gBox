"""Follow the corridor's route to the warp platform and press A.

The route is the disc's own: 29 waypoints over 67.3 units, every leg checked against `Scene/map_city00_00c.rel`. The two things needed to drive it correctly were measured
rather than assumed:

* holding **left increases `heading_deg`** and **right decreases it** (measured -37 for right, +120 for left in half a second) - the opposite of the obvious mapping, and
  what drove the character to z -316 while aiming at z +26;
* `up` walks along the facing, and when it moves nothing the character is against something, so it backs off with `down` before turning.

Only after the platform is reached is A pressed, and the result is read from `room` and the position.
"""
import math
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


def me(pad):
    from pso_pad import call
    state = call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}
    return state.get("player") or {}


def hold(pad, key, secs):
    pad.send([{"key": key, "down": True}])
    time.sleep(secs)
    pad.send([{"key": key, "down": False}])


def bearing(fx, fz, tx, tz):
    return (math.degrees(math.atan2(tx - fx, tz - fz)) + 360.0) % 360.0


def go(pad, target, tolerance=5.0):
    """Turn then walk toward target, with the measured turn polarity."""
    for _ in range(6):
        player = me(pad)
        now = (float(player.get("x") or 0), float(player.get("z") or 0))
        distance = math.hypot(target[0] - now[0], target[1] - now[1])
        if distance < tolerance:
            return now, True
        want = bearing(now[0], now[1], *target)
        error = ((want - float(player.get("heading_deg") or 0) + 540.0) % 360.0) - 180.0
        if abs(error) > 15:
            hold(pad, "left" if error > 0 else "right", min(0.45, max(0.1, abs(error) / 240.0)))
        else:
            before = now
            hold(pad, "up", min(0.8, max(0.25, distance / 180.0)))
            time.sleep(0.15)
            after = me(pad)
            moved = (float(after.get("x") or 0), float(after.get("z") or 0))
            if math.dist(before, moved) < 0.6:
                hold(pad, "down", 0.25)
                hold(pad, "left" if error > 0 else "right", 0.4)
        time.sleep(0.15)
    player = me(pad)
    return (float(player.get("x") or 0), float(player.get("z") or 0)), False


if __name__ == "__main__":
    from pso_pad import Pad, call
    corridor = build()
    pad = Pad()
    print("session:", pad.sid)
    player = me(pad)
    start = (float(player.get("x") or 0), float(player.get("z") or 0))
    print("start:", start, "| safe:", corridor.cell(start) in corridor.safe)

    route = corridor.route(start)
    if not route:
        print("no route from", start)
        raise SystemExit(1)
    print(f"route: {len(route)} waypoints, {sum(math.dist(a, b) for a, b in zip(route, route[1:])):.1f} units")

    reached = 0
    for index, waypoint in enumerate(route[1:], 1):
        now, ok = go(pad, waypoint)
        if ok:
            reached += 1
        if index % 6 == 0:
            print(f"  {index:2d}/{len(route)} ({now[0]:.1f},{now[1]:.1f}) reached={reached}")

    player = me(pad)
    final = (float(player.get("x") or 0), float(player.get("z") or 0))
    distance = math.hypot(PLATFORM[0] - final[0], PLATFORM[1] - final[1])
    print(f"\nfinal ({final[0]:.1f},{final[1]:.1f}) | platform distance {distance:.1f} | waypoints reached {reached}/{len(route) - 1}")
    print("shot:", pad.shot("at_warp_platform"))

    if distance < 30:
        print("pressing A at the platform")
        pad.send([{"key": "a", "down": True}, {"key": "a", "down": False}])
        time.sleep(6)
        player = me(pad)
        print("after A: pos", (player.get("x"), player.get("z")), "| room", player.get("room"))
        print("shot:", pad.shot("after_warp"))
