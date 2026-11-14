"""Plan a walkable route on the LIVE collision grid and print the waypoints.

The route is A* over the cells dumped by `pso-live-map.py` (2.5-unit forest_route.MapRouter grid, so the same
`pso-bounded.py walk --route-file` replays it and `--map` routes the policy over it). Read-only: it never sends
input; it answers "which way would the character have to walk from here to that door/switch/room".

    python pso-route-plan.py --near door            # route to the nearest door object
    python pso-route-plan.py --to 95.2,755.5        # route to a coordinate
    python pso-route-plan.py --near switch --json
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp")

BASE = "http://127.0.0.1:18765"
TOKEN = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token").read_text(encoding="utf-8").strip()
ROUTES = pathlib.Path(r"D:\gBox\pso-ds\routes")
DOORISH = ("TODoor", "TObjDoor", "LazerFence", "Barrier", "Fence")
SWITCHISH = ("TLazerFenceSw", "TObjDoorKey", "TODoorSw")


class Session:
    def __init__(self):
        rows = self.call("/api/sessions")
        rows = rows if isinstance(rows, list) else (rows.get("items") or [])
        live = [row for row in rows if row.get("state") in ("running", "starting") and row.get("adapter") == "dolphin"]
        if not live:
            raise SystemExit("no live dolphin session")
        self.sid = live[0]["session_id"]

    def call(self, path, payload=None, method="GET", timeout=60):
        request = urllib.request.Request(
            BASE + path,
            data=json.dumps(payload).encode() if payload is not None else None, method=method,
            headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                     "content-type": "application/json"})
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")

    def state(self):
        return self.call(f"/api/sessions/{self.sid}/rpc", {"op": "state", "args": {}}, "POST")


def latest_map(floor):
    candidates = sorted(ROUTES.glob(f"live-map-floor{floor}-*.json"), key=lambda path: path.stat().st_mtime)
    if not candidates:
        raise SystemExit(f"no live map for floor {floor} - run pso-live-map.py first")
    return candidates[-1]


def load_router(path, key=None):
    from forest_route import MapRouter
    data = json.loads(path.read_text(encoding="utf-8"))
    key = key or next(iter(data))
    return MapRouter(sorted(data[key]["cells"])), key, len(data[key]["cells"])


def main(argv=None):
    parser = argparse.ArgumentParser(description="A* route plan on the live collision grid")
    parser.add_argument("--map", type=pathlib.Path)
    parser.add_argument("--to", help="x,z target")
    parser.add_argument("--near", choices=("door", "switch", "enemy", "warp"), default="door")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--max-waypoints", type=int, default=40)
    args = parser.parse_args(argv)
    session = Session()
    state = session.state()
    player = state.get("player") or {}
    raw = session.call(f"/api/sessions/{session.sid}/rpc", {"op": "read_memory",
                                                            "args": {"address": 0x805D5FC0, "length": 4}}, "POST")
    floor = int(raw, 16) if isinstance(raw, str) else 0
    path = args.map or latest_map(floor)
    router, key, cells = load_router(path)
    start = (float(player["x"]), float(player["z"]))
    if args.to:
        goal = tuple(float(part) for part in args.to.replace(",", " ").split())
        label = f"coordinate {goal}"
    else:
        words = {"door": DOORISH, "switch": SWITCHISH, "enemy": ("Ene",), "warp": ("Warp",)}[args.near]
        candidates = []
        for entity in (state.get("entities") or [])[:700]:
            cls = str(entity.get("class") or "")
            if not any(word in cls for word in words):
                continue
            if entity.get("x") is None or entity.get("z") is None:
                continue
            distance = math.hypot(float(entity["x"]) - start[0], float(entity["z"]) - start[1])
            candidates.append((distance, cls, float(entity["x"]), float(entity["z"]), entity.get("ptr")))
        if not candidates:
            raise SystemExit(f"no {args.near} entity in the live state")
        candidates.sort()
        distance, cls, goal_x, goal_z, ptr = candidates[0]
        goal = (goal_x, goal_z)
        label = f"{cls} at ({goal_x:.0f},{goal_z:.0f}) ptr {ptr} d={distance:.0f}"
    route = router.route(start, goal)
    if route is None:
        raise SystemExit(f"no route from {tuple(round(v) for v in start)} to {tuple(round(v) for v in goal)}")
    straight = math.dist(start, goal)
    walked = sum(math.dist(a, b) for a, b in zip(route, route[1:]))
    step = max(1, len(route) // args.max_waypoints)
    waypoints = route[::step]
    if waypoints[-1] != route[-1]:
        waypoints.append(route[-1])
    summary = {"map": str(path), "key": key, "cells": cells, "floor": floor, "player": [round(v, 1) for v in start],
               "room": player.get("room"), "target": [round(v, 1) for v in goal], "label": label,
               "waypoints": len(waypoints), "route_cells": len(route),
               "straight_distance": round(straight, 1), "walk_distance": round(walked, 1),
               "path": [[round(x, 1), round(z, 1)] for x, z in waypoints]}
    if args.json:
        print(json.dumps(summary))
    else:
        print(f"target {label}: route {len(waypoints)} waypoints ({len(route)} cells), "
              f"straight {straight:.0f} vs walk {walked:.0f} units")
        for index, (x, z) in enumerate(waypoints):
            print(f"  {index:2d}: ({x:7.1f},{z:7.1f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
