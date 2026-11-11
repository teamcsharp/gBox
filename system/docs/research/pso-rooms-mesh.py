"""Segment a floor into rooms by eroding the free space and growing the cores back.

The neck test failed (only 5 cells on Forest 1) because PSO corridors are two to three cells wide, so almost no cell has as few as two free
neighbours. The standard shape-based method works instead:

  1. free cells from the floor's collision;
  2. **erode** once: keep only cells whose eight neighbours are all free - this removes every one-cell-thick wall of a corridor and leaves the
     room interiors as cores;
  3. take connected components of the eroded set (dropping specks) as room cores;
  4. **flood** every free cell to its nearest core, which assigns the corridors to the rooms they serve;
  5. a cell with a neighbour assigned to a different room is a **boundary** - those boundaries are the doorways.

Verified against Forest 1, whose room graph is already known (9 rooms), then applied to Forest 2, which has never been segmented.
"""
import json
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp")

from gbox import pso_walk                                          # noqa: E402

import nav_fast                                                    # noqa: E402

OUT_DIR = Path(r"D:\gBox\pso-ds\routes")
NEIGHBOURS = ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1))
MIN_CORE = 6
MIN_ROOM = 30


def free_cells(floor):
    floors, walls = pso_walk.cells(nav_fast.rel_for_floor(floor).read_bytes())
    return set(floors - walls)


def neighbours(cell):
    return [(cell[0] + dx, cell[1] + dy) for dx, dy in NEIGHBOURS]


def erode(free):
    return {cell for cell in free if all(n in free for n in neighbours(cell))}


def components(cells):
    seen = set()
    out = []
    for start in cells:
        if start in seen:
            continue
        queue = deque([start])
        seen.add(start)
        room = []
        while queue:
            cell = queue.popleft()
            room.append(cell)
            for neighbour in neighbours(cell):
                if neighbour in cells and neighbour not in seen:
                    seen.add(neighbour)
                    queue.append(neighbour)
        out.append(room)
    return out


def centre(cell):
    return pso_walk.cell_centre(cell)


def main(floor=1):
    free = free_cells(floor)
    cores = erode(free)
    print(f"floor {floor}: {len(free)} free cells, {len(cores)} after one erosion")
    parts = [part for part in components(cores) if len(part) >= MIN_CORE]
    parts.sort(key=len, reverse=True)
    print(f"room cores: {len(parts)}")
    assignment = {}
    queue = deque()
    for number, part in enumerate(parts):
        for cell in part:
            assignment[cell] = number
            queue.append(cell)
    while queue:
        cell = queue.popleft()
        for neighbour in neighbours(cell):
            if neighbour in free and neighbour not in assignment:
                assignment[neighbour] = assignment[cell]
                queue.append(neighbour)
    counts = {}
    for cell, room in assignment.items():
        counts[room] = counts.get(room, 0) + 1
    keep = {room for room, count in counts.items() if count >= MIN_ROOM}
    rooms = []
    for number in sorted(keep):
        cells = [cell for cell, room in assignment.items() if room == number]
        xs = [centre(c)[0] for c in cells]
        zs = [centre(c)[1] for c in cells]
        rooms.append((number, cells, [round(sum(xs) / len(xs), 1), round(sum(zs) / len(zs), 1)]))
    print(f"rooms after growing the cores back: {len(rooms)}")
    description = []
    for index, (number, cells, point) in enumerate(rooms):
        xs = [centre(c)[0] for c in cells]
        zs = [centre(c)[1] for c in cells]
        description.append({"room": index, "cells": len(cells), "centre": point,
                            "bounds": [round(min(xs)), round(max(xs)), round(min(zs)), round(max(zs))],
                            "cell_list": [[round(centre(c)[0]), round(centre(c)[1])] for c in cells]})
        print(f"  room {index}: {len(cells):5d} cells centre ({point[0]:7.1f},{point[1]:7.1f})")
    doors = []
    for cell in free:
        room = assignment.get(cell)
        if room is None or room not in keep:
            continue
        touching = {assignment[n] for n in neighbours(cell)
                    if n in assignment and assignment[n] in keep and assignment[n] != room}
        if touching:
            x, z = centre(cell)
            doors.append({"class": "boundary", "x": round(x, 1), "z": round(z, 1),
                          "rooms": sorted({room} | touching)})
    print(f"boundary cells (doorways): {len(doors)}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUT_DIR / f"forest{floor}-rooms-mesh.json"
    target.write_text(json.dumps({"floor": floor, "method": "erode + grow", "rooms": description,
                                  "doors": doors}, indent=1), encoding="utf-8")
    print("wrote", target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 1))
