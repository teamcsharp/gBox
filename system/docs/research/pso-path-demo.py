"""Path over the real Forest 1 collision from the bot's live position, converted to stick taps.

Demonstrates the CP17 halves end to end on live data: pso_walk builds the cell graph from the disc's own map_forest01c.rel, path()
finds a route from the actor's RAM position to a target, and pso_steer turns the first waypoints into stick directions.
"""
import json
import math
import struct
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import pso_steer, pso_walk                                 # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "75cf966f35164149-4ec5d512e3484b02"
REL = Path(r"D:\gBox\pso-ds\rel\map_forest01c.rel")
ROUTE = Path(r"D:\gBox\pso-ds\routes\route-20261110-235419.json")


def read(address, length):
    body = json.dumps({"op": "read_memory", "args": {"address": address, "length": length}}).encode()
    req = urllib.request.Request(f"{API}/api/sessions/{SID}/rpc", data=body, method="POST",
                                 headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                          "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=15).read() or b'""')


def main():
    actor = int(read(0x8050EA10, 4), 16)
    if not actor:
        print("no actor")
        return 1
    pos = struct.unpack(">fff", bytes.fromhex(read(actor + 0x38, 12)))
    here = (pos[0], pos[2])
    print("actor:", hex(actor), "position:", tuple(round(v, 1) for v in pos))
    collision = REL.read_bytes()
    print("graph:", pso_walk.describe(collision))
    rows = json.loads(ROUTE.read_text(encoding="utf-8"))
    rows = rows.get("rows") if isinstance(rows, dict) else rows
    points = [(r["x"], r["z"]) for r in rows if r.get("floor") == 1]
    if not points:
        print("no floor-1 samples in the route")
        return 2
    # target: the recorded point furthest from where the actor stands now (a real cross-room walk)
    target = max(points, key=lambda p: math.dist(p, here))
    print("target:", tuple(round(v, 1) for v in target),
          f"({math.dist(target, here):.0f} units away, straight line)")
    route = pso_walk.path(collision, here, target)
    if not route:
        print("no path (target not on walkable cells?)")
        return 3
    print("path waypoints:", len(route), "length:",
          round(sum(math.dist(a, b) for a, b in zip([here] + route, route)), 1), "units")
    taps = pso_steer.route_taps(route, here, yaw=0.0)
    print("first taps:", json.dumps(taps[:6], default=str))
    out = Path(r"D:\gBox\pso-ds\routes\forest1-path.json")
    out.write_text(json.dumps({"from": here, "to": target, "waypoints": route,
                               "taps": taps, "source": str(REL)}, indent=1), encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
