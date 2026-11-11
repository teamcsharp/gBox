"""CP17's offline half: a routable walk graph over a room's collision data.

CP17 asks for "Forest 1 -> Forest 2 by walking the collision graph" using `psomap.collision`, the floor resolver and
`pso_floor_map`, `re5_nav`'s pattern. The first two pieces exist (`psomap.collision` parses a `c.rel`; `psomap.walkable_cells`
turns its triangles into floor cells and wall cells). This module turns those cells into a graph and finds a path between two
world points - the part that can be built and tested without a session:

    floors, walls = cells(c_rel_bytes)          # step size / step-up / body height from psomap's defaults
    route = path(c_rel_bytes, start, end)       # [(x, z), ...] cell centres, or None when no path exists

The live half (CP17's accept) is walking that route with the pad and seeing the floor id change. The graph is the same one the
guide names, and a path found here is a path the walker can follow.
"""
from __future__ import annotations

from collections import deque

from . import psomap

CELL = 10.0              # world units per graph cell (psomap's default)
STEP_UP = 6.0
BODY = 18.0


def cells(collision: bytes, *, size: float = CELL, step: float = STEP_UP, body: float = BODY) -> tuple[set, set]:
    """(floor cells, wall cells) for a `c.rel`'s bytes, through psomap's own walkability rules."""
    tris = psomap.collision(collision)
    return psomap.walkable_cells(tris, size=size, step=step, body=body)


def to_cell(x: float, z: float, size: float = CELL) -> tuple[int, int]:
    import math
    return int(math.floor(x / size)), int(math.floor(z / size))


def cell_centre(cell: tuple[int, int], size: float = CELL) -> tuple[float, float]:
    return (cell[0] + 0.5) * size, (cell[1] + 0.5) * size


def path(collision: bytes, start: tuple[float, float], end: tuple[float, float], *,
         size: float = CELL, max_visits: int = 200_000) -> list[tuple[float, float]] | None:
    """A shortest 4-connected route of cell centres from `start` to `end`, or None.

    Only floor cells are walkable; wall cells block (a diagonal move through a corner is therefore never offered). The start
    and end snap to their nearest floor cell within a small radius, so a position read from RAM does not have to be exact.
    """
    floors, walls = cells(collision, size=size)
    if not floors:
        return None
    walkable = floors - walls

    def nearest(point: tuple[float, float]) -> tuple[int, int] | None:
        cell = to_cell(point[0], point[1], size)
        if cell in walkable:
            return cell
        best, best_d = None, 1e9
        for radius in range(1, 4):
            for dx in range(-radius, radius + 1):
                for dz in range(-radius, radius + 1):
                    candidate = (cell[0] + dx, cell[1] + dz)
                    if candidate not in walkable:
                        continue
                    cx, cz = cell_centre(candidate, size)
                    d = (cx - point[0]) ** 2 + (cz - point[1]) ** 2
                    if d < best_d:
                        best, best_d = candidate, d
            if best:
                return best
        return None

    a, b = nearest(start), nearest(end)
    if a is None or b is None:
        return None
    if a == b:
        return [cell_centre(a, size)]

    seen = {a: None}
    queue = deque([a])
    visits = 0
    while queue and visits < max_visits:
        visits += 1
        current = queue.popleft()
        if current == b:
            break
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (current[0] + dx, current[1] + dz)
            if nxt in seen or nxt not in walkable:
                continue
            seen[nxt] = current
            queue.append(nxt)
    if b not in seen:
        return None
    route = []
    node = b
    while node is not None:
        route.append(cell_centre(node, size))
        node = seen[node]
    route.reverse()
    return route


def describe(collision: bytes) -> dict:
    """A one-block summary: how many cells the room has and how much of it is walkable."""
    floors, walls = cells(collision)
    return {"floors": len(floors), "walls": len(walls), "walkable": len(floors - walls)}
