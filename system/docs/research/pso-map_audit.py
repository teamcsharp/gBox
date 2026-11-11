"""Audit the 2D map: is every room reachable, every cell free, every height known?

The operator's framing is that the 2D map IS the game - so the map has to be provably complete before navigation can be trusted. This checks, for each
mapped floor:

  1. **coverage** - every room has cells, and every cell has a height (the height table and the mesh agree);
  2. **validity** - every room cell is a free cell in the collision-derived walkable set, so a route can actually stand there;
  3. **connectivity** - every room is reachable from room 0 through the walkable cell graph, which is stronger than the doorway list: it uses the same
     planner the bot walks with;
  4. **doorway agreement** - rooms the mesh says are joined are actually connected in the cell graph.

A failure in any of these is a navigation bug the bot would hit in play, found offline instead.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import nav_fast as NAV                                             # noqa: E402

ROUTES = Path(r"D:\gBox\pso-ds\routes")
REPORT = Path(r"D:\gBox\pso-ds\routes\map-audit.json")


def load(name):
    try:
        return json.loads((ROUTES / name).read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return {}


def heights(floor):
    raw = load(f"forest{floor}-heights.json")
    table = {}
    for key, value in raw.items():
        try:
            x, z = key.split(",")
            table[(int(x), int(z))] = float(value)
        except Exception:                                        # noqa: BLE001
            continue
    return table


def to_cell(point):
    return (int(point[0] // 10.0), int(point[1] // 10.0))


def audit(floor):
    graph = load(f"forest{floor}-rooms-mesh.json")
    rooms = graph.get("rooms") or []
    if not rooms:
        return {"floor": floor, "ok": False, "reason": "no room graph"}
    free = set(NAV.cells(floor))
    table = heights(floor)

    coverage_missing_height = 0
    total_cells = 0
    invalid_cells = 0
    per_room = {}
    for room in rooms:
        cells = [tuple(cell) for cell in room.get("cell_list") or []]
        total_cells += len(cells)
        bad = 0
        for world in cells:
            cell = to_cell(world)
            if cell not in free:
                bad += 1
            if cell not in table:
                coverage_missing_height += 1
        invalid_cells += bad
        per_room[room["room"]] = {"cells": len(cells), "not_free": bad,
                                  "centre": room["centre"]}

    # connectivity from room 0's centre through the walkable graph
    start = rooms[0]["centre"]
    start_cell = min(free, key=lambda c: (NAV.centre(c)[0] - start[0]) ** 2 + (NAV.centre(c)[1] - start[1]) ** 2)
    reached = {start_cell}
    frontier = [start_cell]
    while frontier:
        x, z = frontier.pop()
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            neighbour = (x + dx, z + dz)
            if neighbour in free and neighbour not in reached:
                reached.add(neighbour)
                frontier.append(neighbour)

    unreachable_rooms = []
    for room in rooms:
        centre = room["centre"]
        cells = [tuple(cell) for cell in room.get("cell_list") or []]
        touching = any(to_cell(world) in reached for world in cells)
        if not touching:
            unreachable_rooms.append(room["room"])

    # doorway agreement: every "connects_to" pair should be joined in the cell graph
    doors = graph.get("doors") or []
    disagreements = []
    for door in doors:
        pair = door.get("rooms") or []
        if len(pair) != 2:
            continue
        a = next((r for r in rooms if r["room"] == pair[0]), None)
        b = next((r for r in rooms if r["room"] == pair[1]), None)
        if not a or not b:
            continue
        a_cells = [to_cell(c) for c in a.get("cell_list") or []]
        b_cells = set(to_cell(c) for c in b.get("cell_list") or [])
        adjacent = any((x + dx, z + dz) in b_cells for (x, z) in a_cells
                       for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)))
        if not adjacent:
            disagreements.append([pair[0], pair[1]])

    ok = (invalid_cells == 0 and not unreachable_rooms and not disagreements
          and coverage_missing_height == 0)
    return {"floor": floor, "ok": ok, "rooms": len(rooms), "cells": total_cells,
            "free_cells": len(free), "reachable_cells": len(reached),
            "missing_height": coverage_missing_height, "not_free": invalid_cells,
            "unreachable_rooms": unreachable_rooms,
            "doorway_disagreements": disagreements[:8],
            "per_room": per_room}


if __name__ == "__main__":
    results = [audit(floor) for floor in range(1, 15)]
    REPORT.write_text(json.dumps(results, indent=1), encoding="utf-8")
    for result in results:
        floor = result["floor"]
        if not result.get("rooms"):
            print(f"floor {floor}: {result.get('reason')}")
            continue
        print(f"floor {floor}: {'PASS' if result['ok'] else 'ISSUES'} - "
              f"{result['rooms']} rooms, {result['cells']} room cells, "
              f"{result['free_cells']} free cells, {result['reachable_cells']} reachable from room 0")
        if result["unreachable_rooms"]:
            print(f"   unreachable rooms: {result['unreachable_rooms']}")
        if result["not_free"]:
            print(f"   room cells that are not walkable: {result['not_free']}")
        if result["missing_height"]:
            print(f"   cells without a height: {result['missing_height']}")
        if result["doorway_disagreements"]:
            print(f"   doorways the cell graph disagrees with: {result['doorway_disagreements']}")
    print("\nreport:", REPORT)
    raise SystemExit(0 if all(r.get("ok") for r in results) else 1)
