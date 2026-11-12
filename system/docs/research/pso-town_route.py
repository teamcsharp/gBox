"""Build the city corridor from the disc's own collision and route the player to the warp platform.

`pso_coop_town` already carries everything needed, and it is all derived from the disc rather than from observations:

* `REL = 'Scene/map_city00_00c.rel'`, 70144 bytes, fingerprinted by sha256 (`REL_SHA`);
* `LANDMARKS` naming the doors at their exact positions - `TObjCityDoor_Warp (254.001, 0, 25.002)`;
* `PLATFORM = (360.003, 25.998)`, the warp platform the route aims at;
* `Corridor`, a height-filtered walkable grid (2.5-unit cells, three-by-three erosion) built from those triangles;
* `Corridor.route(start, end=PLATFORM)`, an A* over the safe cells that also verifies every leg is `clear()`.

`load_corridor(ad)` needs a live adapter only to reach `ad.memory_card_rom`; the work it does is disc reads, so it is reproduced here from the disc path. The result is
the map analysis this task asked for, used for exactly what it was asked to do: path-guiding the bot to the warp so it can leave the city for a field with enemies.
"""
import hashlib
import json
import math
import sys

sys.path.insert(0, r"C:\_tools\gBox\system")

DISC = r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz"
OUT = r"D:\gBox\pso-ds\town_route.json"


def main() -> int:
    from gbox.gcdisc import GCDisc
    from gbox.psomap import collision
    from gbox import pso_coop_town as town
    from pso_pad import Pad, call

    print("disc:", DISC)
    disc = GCDisc(DISC)
    try:
        print("disc id:", disc._r(0, 8))
        entry = disc.files.get(town.REL, (0, 0))
        print("file entry:", entry, "| expected size: 70144")
        data = disc.read(town.REL)
    finally:
        disc.f.close()

    digest = hashlib.sha256(data).hexdigest()
    print("size:", len(data), "| sha256:", digest)
    print("matches the fingerprint the module requires:", digest == town.REL_SHA)
    if len(data) != 70144 or digest != town.REL_SHA:
        print("REFUSING: the disc's town collision is not the one this corridor was built for")
        return 1

    triangle_rows = collision(data)
    print("triangles:", len(triangle_rows))
    corridor = town.Corridor(triangle_rows)
    print("walkable cells (base):", len(corridor.base), "| safe cells:", len(corridor.safe))
    print("platform:", town.PLATFORM)

    pad = Pad()
    state = call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}
    me = (state.get("player") or {})
    print("\nplayer:", (me.get("x"), me.get("z")), "| room", me.get("room"))
    if not me:
        print("no player")
        return 1

    start = (float(me.get("x") or 0.0), float(me.get("z") or 0.0))
    print("start cell:", corridor.cell(start), "in safe:", corridor.cell(start) in corridor.safe)

    route = corridor.route(start)
    if not route:
        print("no route from here - trying the static-margin recovery")
        route = corridor.recover(start)
        if route:
            print("recovered a connector:", route[:3], "...")
            route = corridor.route(route[-1]) or None

    if not route:
        print("\nNO ROUTE: the player is not on a safe cell of this exact mesh")
        return 1

    length = sum(math.dist(a, b) for a, b in zip(route, route[1:]))
    print(f"\nROUTE: {len(route)} waypoints, {length:.1f} units")
    for index, point in enumerate(route[:12]):
        print(f"  {index:2d}: ({point[0]:8.2f}, {point[1]:8.2f})")
    if len(route) > 12:
        print(f"  ... {len(route) - 12} more -> ({route[-1][0]:.2f}, {route[-1][1]:.2f})")

    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump({"start": start, "platform": list(town.PLATFORM),
                   "route": [list(point) for point in route], "length": length}, handle)
    print("\nwrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
