"""Build Forest 1's room graph: rooms are connected components of the flat floor AFTER cutting at each door, and doors are the edges.

This is the "understand the level intimately and go to the exit linearly" structure: the level is a chain of rooms joined by doors, so the
route from the current position to any destination is a sequence of (room -> door -> room -> door ...). The bot then only ever has to
walk to the next door and push through it - never explore.

Output: D:\\gBox\\pso-ds\\routes\\forest1-rooms.json with rooms (centre, size, cells) and door edges (which rooms a door joins).
"""
import json
import math
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp")

from gbox import psomap, pso_walk                                  # noqa: E402

import pso_doors                                                   # noqa: E402

REL = Path(r"D:\gBox\pso-ds\rel\map_forest01c.rel")
SIZE = 10.0
STEP_LIMIT = 2.5
CUT_RADIUS = 22.0
OUT = Path(r"D:\gBox\pso-ds\routes\forest1-rooms.json")

DOORS = [  # (index, class, x, z) from the entity table, states change at runtime so only geometry is baked in
    (17, "TObjDoor", -147.0, -363.9), (27, "TObjDoor", 517.8, -349.5), (31, "TObjDoor", -537.9, 180.5),
    (32, "TObjDoor", -492.8, -336.3), (47, "TObjDoorKey", 200.6, -17.6), (52, "TObjDoor", 224.0, -424.2),
    (58, "TObjDoor", -133.8, 271.7), (63, "TObjDoor", -193.2, 100.0), (66, "TObjDoor", 252.8, 91.9),
    (67, "TObjDoor", 53.2, 290.5),
]


def read_memory(address, length):
    import time
    import urllib.request
    token = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
    body = json.dumps({"op": "read_memory", "args": {"address": address, "length": length}}).encode()
    for _ in range(3):
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:8765/api/sessions/e731ee594dde4a89-cae9dad929a34d17/rpc", data=body, method="POST",
                headers={"authorization": "Bearer " + token, "x-gbox-actor": "agent",
                         "content-type": "application/json"})
            return bytes.fromhex(json.loads(urllib.request.urlopen(req, timeout=10).read() or b'""'))
        except Exception:                                        # noqa: BLE001
            time.sleep(0.1)
    return b""


def floor_heights(tris):
    heights = {}
    for (a, b, c, flags, normal) in tris:
        if flags & psomap.TRIGGER_FLAG or normal[1] <= 0.6:
            continue
        xs, zs = (a[0], b[0], c[0]), (a[2], b[2], c[2])
        for i in range(int(math.floor(min(xs) / SIZE)), int(math.floor(max(xs) / SIZE)) + 1):
            for j in range(int(math.floor(min(zs) / SIZE)), int(math.floor(max(zs) / SIZE)) + 1):
                px, pz = (i + 0.5) * SIZE, (j + 0.5) * SIZE
                if psomap._inside(px, pz, a, b, c):
                    y = psomap._height(px, pz, a, b, c)
                    heights[(i, j)] = max(heights.get((i, j), -1e9), y)
    return heights


def flat_cells():
    collision = REL.read_bytes()
    tris = psomap.collision(collision)
    floors, walls = pso_walk.cells(collision)
    walkable = floors - walls
    heights = floor_heights(tris)
    flat = set()
    for cell in walkable:
        height = heights.get(cell)
        if height is None:
            continue
        worst = 0.0
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            neighbour = (cell[0] + dx, cell[1] + dz)
            if neighbour in walkable:
                other = heights.get(neighbour)
                if other is not None:
                    worst = max(worst, abs(other - height))
        if worst <= STEP_LIMIT:
            flat.add(cell)
    return flat


def components(cells):
    seen, groups = set(), []
    for cell in cells:
        if cell in seen:
            continue
        queue = deque([cell])
        seen.add(cell)
        group = []
        while queue:
            cx, cz = queue.popleft()
            group.append((cx, cz))
            for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nxt = (cx + dx, cz + dz)
                if nxt in cells and nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        groups.append(group)
    groups.sort(key=len, reverse=True)
    return groups


def main():
    flat = flat_cells()
    print(f"flat cells {len(flat)}")
    doors = []
    for index, name, x, z in DOORS:
        doors.append({"index": index, "class": name, "x": x, "z": z})
    # live states if the game is reachable
    try:
        live = {d["index"]: d for d in pso_doors.read(read_memory)}
        for door in doors:
            if door["index"] in live:
                door["state"] = live[door["index"]]["state"]
    except Exception as exc:                                     # noqa: BLE001
        print("live door states unavailable:", str(exc)[:80])
    cut = set()
    for door in doors:
        for cell in flat:
            cx, cz = pso_walk.cell_centre(cell)
            if math.dist((cx, cz), (door["x"], door["z"])) <= CUT_RADIUS:
                cut.add(cell)
    rooms = components(flat - cut)
    rooms = [room for room in rooms if len(room) >= 12]
    print(f"rooms after cutting at doors (r={CUT_RADIUS}): {len(rooms)}")
    description = []
    for number, room in enumerate(rooms):
        xs = [pso_walk.cell_centre(c)[0] for c in room]
        zs = [pso_walk.cell_centre(c)[1] for c in room]
        description.append({"room": number, "cells": len(room),
                            "centre": [round(sum(xs) / len(xs), 1), round(sum(zs) / len(zs), 1)],
                            "bounds": [round(min(xs)), round(max(xs)), round(min(zs)), round(max(zs))],
                            "cell_list": [[round(pso_walk.cell_centre(c)[0]), round(pso_walk.cell_centre(c)[1])]
                                          for c in room]})
        print(f"  room {number}: {len(room):5d} cells centre ({description[-1]['centre'][0]:7.1f},"
              f"{description[-1]['centre'][1]:7.1f}) x {description[-1]['bounds'][0]}..{description[-1]['bounds'][1]} "
              f"z {description[-1]['bounds'][2]}..{description[-1]['bounds'][3]}")
    # which rooms does each door join? look at the rooms whose cells are nearest the door
    edges = []
    for door in doors:
        near = sorted(range(len(rooms)),
                      key=lambda n: min(math.dist(pso_walk.cell_centre(c), (door["x"], door["z"])) for c in rooms[n]))
        joined = near[:2]
        edges.append({"door": door["index"], "class": door["class"], "x": door["x"], "z": door["z"],
                      "state": door.get("state"), "rooms": joined})
        print(f"  door {door['index']:3d} {door['class']:<16} ({door['x']:7.1f},{door['z']:7.1f}) "
              f"state={door.get('state')} joins rooms {joined}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"cut_radius": CUT_RADIUS, "rooms": description, "doors": edges}, indent=1),
                   encoding="utf-8")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
