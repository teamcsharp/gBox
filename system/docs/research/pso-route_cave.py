"""Route across a real decoded Cave 1 room, avoiding the walls the disc actually defines.

`RoomMap(size=10)` uses the same cell indices `walkable_cells` produced, so the decoded walls drop straight in. The previous attempt picked bounding-box
corners, which are inside geometry - this picks two confirmed-open cells far apart inside the same connected area, then checks every step of the result
against the wall set.

A route that ends near the goal and never enters a wall cell is the goal's "map internalised and used for pathguiding", demonstrated on the room the operator
is standing in.
"""
import json
import math
import pathlib
import sys

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import pso_coop_nav                                    # noqa: E402

ROUTES = pathlib.Path(r"D:\gBox\pso-ds\routes")


def open_cells(record):
    """Every cell in the bounds that is not a wall - reconstructed from the blocked set and the bound box."""
    walls = {tuple(cell) for cell in record["blocked"]}
    (low, high) = record["bounds"]
    x0, z0 = math.floor(low[0] / 10), math.floor(low[1] / 10)
    x1, z1 = math.floor(high[0] / 10), math.floor(high[1] / 10)
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            if (x, z) not in walls:
                yield (x, z)


def connected_component(start, walkable, cap=60000):
    """Flood fill on 4-neighbours, so the two endpoints are genuinely reachable."""
    seen, frontier = {start}, [start]
    while frontier and len(seen) < cap:
        x, z = frontier.pop()
        for step in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            cell = (x + step[0], z + step[1])
            if cell in walkable and cell not in seen:
                seen.add(cell)
                frontier.append(cell)
    return seen


if __name__ == "__main__":
    sample = ROUTES / "map_cave01_00c-mesh.json"
    record = json.loads(sample.read_text(encoding="utf-8"))
    walls = {tuple(cell) for cell in record["blocked"]}
    walkable = set(open_cells(record))
    print("room:", record["floor"], "| triangles:", record["triangles"])
    print("  walkable cells:", len(walkable), "| wall cells:", len(walls))

    seed = next(iter(walkable))
    component = connected_component(seed, walkable)
    print("  largest reachable component from the first open cell:", len(component))

    ordered = sorted(component)
    start_cell = ordered[0]
    goal_cell = max(component, key=lambda c: abs(c[0] - start_cell[0]) + abs(c[1] - start_cell[1]))
    print("  start cell:", start_cell, "-> goal cell:", goal_cell,
          "| manhattan:", abs(goal_cell[0] - start_cell[0]) + abs(goal_cell[1] - start_cell[1]))

    room = pso_coop_nav.RoomMap(path=ROUTES / "cave01_00-grid.json", size=10.0, walls=walls)
    start = room.center(start_cell)
    goal = room.center(goal_cell)
    route = room.route(start, goal)
    if not route:
        raise SystemExit("no route between two cells of the same component")

    entering = [p for p in route if room.cell(p) in walls]
    # every consecutive pair must be a legal move
    bad = []
    for a, b in zip(route, route[1:]):
        if not room.allowed(room.cell(a), room.cell(b)):
            bad.append((room.cell(a), room.cell(b)))

    print("\nroute:", len(route), "points")
    print("  first:", route[0], "last:", route[-1])
    print("  points inside a wall:", len(entering))
    print("  illegal transitions:", len(bad))
    length = sum(math.dist(a, b) for a, b in zip(route, route[1:]))
    straight = math.dist(start, goal)
    print(f"  path {length:.0f} units vs {straight:.0f} straight ({length / max(straight, 1):.2f}x)")
    print("\nVERDICT:", "the decoded map guides a legal route" if not entering and not bad
          else "route is not clean")
