"""Route only over FLAT collision cells, so the walker never walks onto a slope it cannot leave.

psomap.walkable_cells computes a floor height per cell but returns only sets. This recomputes the same heights, measures each cell's
steepest step to a walkable neighbour, keeps cells whose worst step is small, and BFS-routes the spawn -> key door over those cells.
Usage: flat_route.py [--spawn X Z] [--door X Z]
"""
import argparse
import json
import math
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import psomap, pso_walk                                   # noqa: E402

REL = Path(r"D:\gBox\pso-ds\rel\map_forest01c.rel")
SIZE = 10.0
STEP_LIMIT = 2.5                                                    # units of height change allowed between neighbours


def floor_heights(tris, size=SIZE):
    heights = {}
    for (a, b, c, flags, normal) in tris:
        if flags & psomap.TRIGGER_FLAG or normal[1] <= 0.6:
            continue
        xs, zs = (a[0], b[0], c[0]), (a[2], b[2], c[2])
        for i in range(int(math.floor(min(xs) / size)), int(math.floor(max(xs) / size)) + 1):
            for j in range(int(math.floor(min(zs) / size)), int(math.floor(max(zs) / size)) + 1):
                px, pz = (i + 0.5) * size, (j + 0.5) * size
                if psomap._inside(px, pz, a, b, c):
                    y = psomap._height(px, pz, a, b, c)
                    heights[(i, j)] = max(heights.get((i, j), -1e9), y)
    return heights


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spawn", nargs=2, type=float, default=[532.7, 483.3])
    ap.add_argument("--door", nargs=2, type=float, default=[201.0, -18.0])
    args = ap.parse_args()
    tris = psomap.collision(REL.read_bytes())
    floors, walls = pso_walk.cells(REL.read_bytes())
    walkable = floors - walls
    heights = floor_heights(tris)
    flat = set()
    for cell in walkable:
        x, z = cell
        height = heights.get(cell)
        if height is None:
            continue
        worst = 0.0
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            neighbour = (x + dx, z + dz)
            if neighbour not in walkable:
                continue
            other = heights.get(neighbour)
            if other is None:
                continue
            worst = max(worst, abs(other - height))
        if worst <= STEP_LIMIT:
            flat.add(cell)
    print(f"walkable {len(walkable)}, flat {len(flat)} ({100.0 * len(flat) / max(1, len(walkable)):.1f}%)")

    def nearest_flat(point):
        candidates = min(flat, key=lambda c: math.dist(pso_walk.cell_centre(c), point), default=None)
        return candidates

    start = nearest_flat(tuple(args.spawn))
    goal = nearest_flat(tuple(args.door))
    print("start cell:", start, tuple(round(v, 1) for v in pso_walk.cell_centre(start)))
    print("goal cell:", goal, tuple(round(v, 1) for v in pso_walk.cell_centre(goal)))
    if start is None or goal is None:
        print("no flat cells")
        return 1
    queue = deque([start])
    previous = {start: None}
    while queue:
        cell = queue.popleft()
        if cell == goal:
            break
        x, z = cell
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            neighbour = (x + dx, z + dz)
            if neighbour in flat and neighbour not in previous:
                previous[neighbour] = cell
                queue.append(neighbour)
    if goal not in previous:
        print("NO flat route to the door")
        return 2
    route = []
    cell = goal
    while cell is not None:
        route.append(cell)
        cell = previous[cell]
    route.reverse()
    waypoints = [pso_walk.cell_centre(cell) for cell in route]
    length = sum(math.dist(a, b) for a, b in zip(waypoints, waypoints[1:]))
    print(f"flat route: {len(waypoints)} waypoints, {length:.0f} units")
    out = Path(r"D:\gBox\pso-ds\routes\forest1-flat-route.json")
    out.write_text(json.dumps({"spawn": args.spawn, "door": args.door, "waypoints": waypoints,
                               "flat_cells": len(flat)}, indent=1), encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
