"""Route over the internalised Forest map - the "used for path-guiding" half of the objective.

The map is decoded and internalised (`Scene/map_forest01c.rel`: 1455 triangles -> 98,380 walkable / 90,986 safe cells; `forest02c`: 1475 -> 108,984 / 98,671). What that buys is a walkable grid,
and this turns the grid into routes.

It mirrors `pso_coop_town.Corridor.route` so the loop can use either:

* snap the start and goal to the nearest **safe** cell, since a raw position can sit a fraction outside the eroded margin;
* **A*** with 8-neighbour moves, cost = true distance, heuristic = octile distance (admissible, so the route is optimal on the grid);
* every leg is a pair of adjacent safe cells, so a returned route is walkable by construction.

Pure geometry - no session needed - so it is testable while the operator has the controller.
"""
import heapq
import json
import math
import pathlib
import sys

sys.path.insert(0, r"C:\_tools\gBox\system")

MAPS = pathlib.Path(r"D:\gBox\pso-ds\forest-maps.json")
SIZE = 2.5
NEIGHBOURS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


class MapRouter:
    """A* over one map's safe cells."""

    def __init__(self, safe_cells):
        self.safe = {(int(cell[0]), int(cell[1])) for cell in safe_cells}

    def cell(self, point):
        return (math.floor(point[0] / SIZE), math.floor(point[1] / SIZE))

    def center(self, cell):
        return ((cell[0] + 0.5) * SIZE, (cell[1] + 0.5) * SIZE)

    def nearest(self, cell):
        """The closest safe cell, expanding rings - a raw position can be just outside the margin."""
        if cell in self.safe:
            return cell
        for radius in range(1, 25):
            best = None
            for dx in range(-radius, radius + 1):
                for dz in (-radius, radius):
                    for candidate in ((cell[0] + dx, cell[1] + dz), (cell[0] + dz, cell[1] + dx)):
                        if candidate in self.safe:
                            distance = math.hypot(candidate[0] - cell[0], candidate[1] - cell[1])
                            if best is None or distance < best[0]:
                                best = (distance, candidate)
            if best:
                return best[1]
        return None

    def route(self, start_point, goal_point, limit=20000):
        start = self.nearest(self.cell(start_point))
        goal = self.nearest(self.cell(goal_point))
        if start is None or goal is None:
            return None
        if start == goal:
            return [self.center(start)]
        open_heap = [(0.0, start)]
        came = {start: None}
        cost = {start: 0.0}
        expanded = 0
        while open_heap and expanded < limit:
            _, current = heapq.heappop(open_heap)
            expanded += 1
            if current == goal:
                path = []
                node = current
                while node is not None:
                    path.append(self.center(node))
                    node = came[node]
                return list(reversed(path))
            for dx, dz in NEIGHBOURS:
                neighbour = (current[0] + dx, current[1] + dz)
                if neighbour not in self.safe:
                    continue
                step = math.hypot(dx, dz)
                if (dx and dz) and ((current[0] + dx, current[1]) not in self.safe
                                    or (current[0], current[1] + dz) not in self.safe):
                    continue                                   # no corner cutting
                tentative = cost[current] + step
                if tentative < cost.get(neighbour, 1e18):
                    cost[neighbour] = tentative
                    came[neighbour] = current
                    heuristic = math.hypot(goal[0] - neighbour[0], goal[1] - neighbour[1])
                    heapq.heappush(open_heap, (tentative + heuristic, neighbour))
        return None


if __name__ == "__main__":
    data = json.loads(MAPS.read_text(encoding="utf-8"))
    for name, row in data.items():
        router = MapRouter(row["cells"])
        print(f"\n{name}: safe cells {len(router.safe)}")
        # a route across the map: from one far corner of the safe set to the other
        cells = sorted(router.safe)
        if not cells:
            continue
        start = router.center(cells[0])
        goal = router.center(cells[-1])
        route = router.route(start, goal)
        if route:
            length = sum(math.dist(a, b) for a, b in zip(route, route[1:]))
            print(f"  route {start} -> {goal}: {len(route)} waypoints, {length:.0f} units")
            print(f"  first three: {route[:3]}")
        else:
            print(f"  no route from {start} to {goal}")
