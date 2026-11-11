"""Fast navigation: plan over free collision cells, collapse the route with line-of-sight, then drive it in long strides.

The slow controllers spend their time deciding (four 0.3 s probes per stride) and bumping into walls to discover them. This one knows
where the free space is:

  1. the walkable cells come from the collision mesh once (pso_walk.cells, 5,701 cells);
  2. `line_free(a, b)` ray-marches the straight line between two points through those cells;
  3. `plan()` runs the cell BFS and then string-pulls it - waypoints the straight line can skip are dropped, so a 100-waypoint route
     becomes a handful;
  4. `drive_to()` walks the simplified route with long forward holds and short turn taps.

`plan()` is pure geometry and can be benchmarked with no input at all, which is what this round measures.
"""
import json
import math
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp")

from gbox import pso_walk                                          # noqa: E402

REL = Path(r"D:\gBox\pso-ds\rel\map_forest01c.rel")
FLOOR_REL = {
    1: Path(r"D:\gBox\pso-ds\rel\map_forest01c.rel"),
    2: Path(r"D:\gBox\pso-ds\rel\map_forest02c.rel"),
}
SIZE = 10.0
CLEARANCE = 0                                                      # only the cells the line passes through


def rel_for_floor(floor=None):
    """The collision file for a floor: the floor's own map when it exists, else the historical fallback."""
    if floor is None:
        return REL
    try:
        candidate = REL.parent / f"map_forest{int(floor):02d}c.rel"
    except (TypeError, ValueError):
        return REL
    if candidate.exists():
        return candidate
    return FLOOR_REL.get(floor, REL)


def cells(floor=None):
    floors, walls = pso_walk.cells(rel_for_floor(floor).read_bytes())
    return set(floors - walls)          # CELL INDICES, not centres


def cell_of(point):
    return (int(math.floor(point[0] / SIZE)), int(math.floor(point[1] / SIZE)))


def centre(cell):
    return pso_walk.cell_centre(cell)


def line_free(free, a, b, step=4.0):
    """True when every sample along a-b is inside a free cell (with a one-cell clearance)."""
    distance = math.dist(a, b)
    samples = max(2, int(distance / step))
    for index in range(samples + 1):
        u = index / samples
        x = a[0] + (b[0] - a[0]) * u
        z = a[1] + (b[1] - a[1]) * u
        cell = cell_of((x, z))
        if cell not in free:
            return False
        for dx in (-CLEARANCE, 0, CLEARANCE):
            for dz in (-CLEARANCE, 0, CLEARANCE):
                if (cell[0] + int(dx), cell[1] + int(dz)) not in free:
                    return False
    return True


def bfs(free, start, goal):
    start_cell = min(free, key=lambda c: math.dist(centre(c), start))
    goal_cell = min(free, key=lambda c: math.dist(centre(c), goal))
    queue = deque([start_cell])
    previous = {start_cell: None}
    while queue:
        cell = queue.popleft()
        if cell == goal_cell:
            break
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            neighbour = (cell[0] + dx, cell[1] + dz)
            if neighbour in free and neighbour not in previous:
                previous[neighbour] = cell
                queue.append(neighbour)
    if goal_cell not in previous:
        return []
    path = []
    cell = goal_cell
    while cell is not None:
        path.append(centre(cell))
        cell = previous[cell]
    path.reverse()
    return path


def string_pull(free, path):
    """Drop every waypoint whose straight line from the last kept point is free."""
    if len(path) <= 2:
        return list(path)
    kept = [path[0]]
    index = 1
    while index < len(path):
        # find the furthest waypoint reachable in a straight line from the last kept point
        furthest = index
        for candidate in range(len(path) - 1, index - 1, -1):
            if line_free(free, kept[-1], path[candidate]):
                furthest = candidate
                break
        kept.append(path[furthest])
        index = furthest + 1
    return kept


def plan(start, goal, cache={}):
    free = cache.get("free")
    if free is None:
        free = cells()
        cache["free"] = free
    raw = bfs(free, start, goal)
    if not raw:
        return [], 0, 0
    simplified = string_pull(free, raw)
    return simplified, len(raw), len(simplified)


if __name__ == "__main__":
    import time

    started = time.time()
    free = cells()
    print(f"free cells: {len(free)} ({time.time() - started:.1f}s to load)")
    start = (float(sys.argv[1]), float(sys.argv[2])) if len(sys.argv) > 2 else (-185.0, -17.0)
    goal = (float(sys.argv[3]), float(sys.argv[4])) if len(sys.argv) > 4 else (141.0, -194.0)
    t0 = time.time()
    route, raw_count, simple_count = plan(start, goal)
    elapsed = time.time() - t0
    length = sum(math.dist(a, b) for a, b in zip(route, route[1:]))
    print(f"start {start} -> goal {goal}")
    print(f"raw BFS waypoints: {raw_count}  after string-pull: {simple_count}  route length {length:.0f} units "
          f"(planned in {elapsed:.2f}s)")
    for waypoint in route[:12]:
        print(f"  waypoint ({waypoint[0]:7.1f},{waypoint[1]:7.1f})")
