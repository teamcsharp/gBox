"""Learned occupancy-grid navigation for the RE5 Switch Mercenaries bot.

The PS3 bot reads RE5's own navigation mesh from RAM (re5_nav.py, sAI ->
cAIPathFinding -> rNavigationMesh).  The Switch binary's sAI singleton address
is not yet mapped, so this module builds a *learned* grid instead: where the
bot has actually walked is open, where it hit walls is blocked, and A* routes
across that map.  The grid persists per stage under gbox-data/mercs/learned/
so it improves across sessions.

Grid: 1 m cells in the XZ plane, keyed by stage name.  Values are costs:
  0.5  walked (the bot's own trail)
  1.0  unknown (assumed passable, mildly discouraged)
  4.0  near a wall (discouraged)
  16.0 wall memory (strongly discouraged)
A* finds the lowest-cost path; the route is smoothed by line-of-sight.
"""

from __future__ import annotations

import heapq
import json
import logging
import math
import time
from pathlib import Path

log = logging.getLogger(__name__)

CELL = 100.0          # 1 m cells (game units are cm)
WALL_RADIUS = 150.0   # wall influence radius (cm)
TRAIL_RADIUS = 80.0   # trail mark radius (cm)
NEAR_WALL = 200.0     # "near a wall" band (cm)

# cost tiers
C_WALKED = 0.5
C_UNKNOWN = 1.0
C_NEAR_WALL = 4.0
C_WALL = 16.0

# A* tuning
MAX_EXPANSIONS = 4000
DIAG_COST = math.sqrt(2.0)


def _key(x: float, z: float) -> tuple[int, int]:
    return (int(round(x / CELL)), int(round(z / CELL)))


def _center(kx: int, kz: int) -> tuple[float, float]:
    return (kx * CELL, kz * CELL)


class OccupancyGrid:
    """A per-stage learned grid with A* routing."""

    def __init__(self, stage: str, base: Path | None = None):
        self.stage = stage
        self.cells: dict[tuple[int, int], float] = {}
        self._dirty = False
        self._last_save = 0.0
        self._base = base
        if base is not None:
            self._load(base)

    # -- persistence ---------------------------------------------------------

    def _path(self, base: Path) -> Path:
        safe = self.stage.replace(" ", "_").replace("/", "-")
        return base / "nav_grids" / f"{safe}.json"

    def _load(self, base: Path) -> None:
        p = self._path(base)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("stage") != self.stage or data.get("schema") != 1:
                return
            cells = data.get("cells")
            if isinstance(cells, dict):
                self.cells = {}
                for k, v in cells.items():
                    parts = k.split(",")
                    if len(parts) == 2:
                        self.cells[(int(parts[0]), int(parts[1]))] = float(v)
        except Exception:
            pass

    def save(self, base: Path | None = None, force: bool = False) -> None:
        if base is None:
            base = self._base
        if base is None or not self._dirty:
            return
        now = time.monotonic()
        if not force and now - self._last_save < 30.0:
            return
        self._last_save = now
        self._dirty = False
        try:
            p = self._path(base)
            p.parent.mkdir(parents=True, exist_ok=True)
            payload = {"schema": 1, "stage": self.stage, "cell": CELL,
                       "cells": {f"{k[0]},{k[1]}": round(v, 3) for k, v in self.cells.items()}}
            p.write_text(json.dumps(payload), encoding="utf-8")
        except Exception as exc:
            log.debug("nav grid save failed: %s", exc)

    # -- update ---------------------------------------------------------------

    def mark_walked(self, x: float, z: float) -> None:
        k = _key(x, z)
        cur = self.cells.get(k)
        if cur is None or cur > C_WALKED:
            self.cells[k] = C_WALKED
            self._dirty = True

    def mark_wall(self, x: float, z: float) -> None:
        k = _key(x, z)
        if self.cells.get(k) != C_WALL:
            self.cells[k] = C_WALL
            self._dirty = True
        # soften neighbours into the "near wall" band (never downgrade an existing wall)
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                if dx == 0 and dz == 0:
                    continue
                nk = (k[0] + dx, k[1] + dz)
                v = self.cells.get(nk)
                if v is None or (v > C_NEAR_WALL and v != C_WALL):
                    self.cells[nk] = C_NEAR_WALL
                    self._dirty = True

    def cost(self, k: tuple[int, int]) -> float:
        return self.cells.get(k, C_UNKNOWN)

    # -- queries ---------------------------------------------------------------

    def walkable(self, k: tuple[int, int]) -> bool:
        return self.cost(k) < C_WALL

    def known_open(self, k: tuple[int, int]) -> bool:
        """A cell the bot has actually walked (not merely assumed)."""
        return self.cost(k) <= C_WALKED

    def openness(self, x: float, z: float, heading: float, cells_ahead: int = 3) -> float:
        """The summed cost of the cells along a ray from (x, z) at `heading` (rad, 0 = +Z).
        Lower is more open.  Unknown cells cost C_UNKNOWN; walls cost C_WALL."""
        total = 0.0
        for i in range(1, cells_ahead + 1):
            dist = i * CELL
            cx = x + math.sin(heading) * dist
            cz = z + math.cos(heading) * dist
            total += self.cost(_key(cx, cz))
        return total

    def best_heading(self, x: float, z: float, current: float,
                     samples: int = 8) -> tuple[float, float]:
        """Sample `samples` compass directions around (x, z); return (best_heading, its_openness).
        The current heading is included so a good-enough facing is kept."""
        best_h, best_cost = current, float("inf")
        for i in range(samples):
            h = current + 2.0 * math.pi * i / samples
            c = self.openness(x, z, h)
            if c < best_cost:
                best_h, best_cost = h, c
        return best_h, best_cost

    # -- A* ---------------------------------------------------------------------

    def _neighbours(self, k: tuple[int, int]):
        x, z = k
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                if dx == 0 and dz == 0:
                    continue
                nk = (x + dx, z + dz)
                if not self.walkable(nk):
                    continue
                step = DIAG_COST if dx and dz else 1.0
                yield nk, step

    def _heuristic(self, a: tuple[int, int], b: tuple[int, int]) -> float:
        dx, dz = abs(a[0] - b[0]), abs(a[1] - b[1])
        return max(dx, dz) + (DIAG_COST - 1.0) * min(dx, dz)

    def route(self, start: tuple[float, float], goal: tuple[float, float],
              max_expansions: int = MAX_EXPANSIONS) -> list[tuple[float, float]] | None:
        """A* from start (x, z) to goal (x, z) -> [(x, z), ...] cell centres, or None."""
        sk, gk = _key(*start), _key(*goal)
        if not self.walkable(sk):
            # nudge start to the nearest walkable cell
            sk = self._nearest_walkable(sk, radius=2)
            if sk is None:
                return None
        if not self.walkable(gk):
            gk = self._nearest_walkable(gk, radius=2)
            if gk is None:
                return None

        open_heap: list[tuple[float, tuple[int, int]]] = [(0.0, sk)]
        came: dict[tuple[int, int], tuple[int, int]] = {}
        g_score: dict[tuple[int, int], float] = {sk: 0.0}
        closed: set[tuple[int, int]] = set()
        expansions = 0

        while open_heap and expansions < max_expansions:
            _, cur = heapq.heappop(open_heap)
            if cur in closed:
                continue
            closed.add(cur)
            expansions += 1
            if cur == gk:
                return self._reconstruct(came, cur)
            for nk, step in self._neighbours(cur):
                if nk in closed:
                    continue
                tentative = g_score[cur] + step * self.cost(nk)
                if tentative < g_score.get(nk, float("inf")):
                    g_score[nk] = tentative
                    came[nk] = cur
                    f = tentative + self._heuristic(nk, gk)
                    heapq.heappush(open_heap, (f, nk))
        return None

    def _nearest_walkable(self, k: tuple[int, int], radius: int = 2) -> tuple[int, int] | None:
        best, best_d = None, float("inf")
        for dx in range(-radius, radius + 1):
            for dz in range(-radius, radius + 1):
                nk = (k[0] + dx, k[1] + dz)
                if self.walkable(nk):
                    d = dx * dx + dz * dz
                    if d < best_d:
                        best, best_d = nk, d
        return best

    def _reconstruct(self, came: dict, cur: tuple[int, int]) -> list[tuple[float, float]]:
        keys = [cur]
        while cur in came:
            cur = came[cur]
            keys.append(cur)
        keys.reverse()
        return [_center(*k) for k in keys]

    # -- smoothing --------------------------------------------------------------

    def line_of_sight(self, a: tuple[float, float], b: tuple[float, float]) -> bool:
        """Walk the segment cell-by-cell; True when every crossed cell is walkable."""
        steps = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / (CELL * 0.5)))
        for i in range(steps + 1):
            t = i / steps
            x, z = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
            if not self.walkable(_key(x, z)):
                return False
        return True

    def smooth(self, waypoints: list[tuple[float, float]]) -> list[tuple[float, float]]:
        """Greedy line-of-sight smoothing: keep the furthest visible waypoint."""
        if len(waypoints) <= 2:
            return list(waypoints)
        out = [waypoints[0]]
        i = 0
        while i < len(waypoints) - 1:
            j = len(waypoints) - 1
            while j > i + 1 and not self.line_of_sight(waypoints[i], waypoints[j]):
                j -= 1
            out.append(waypoints[j])
            i = j
        return out


class Navigator:
    """Per-bot navigation state: the grid, the current route, replanning."""

    REPLAN_S = 2.0
    WP_REACHED = 120.0        # cm
    ROUTE_STALE_S = 25.0

    def __init__(self, stage: str, learn_dir: Path | None = None):
        self.grid = OccupancyGrid(stage, base=learn_dir)
        self.route: list[tuple[float, float]] | None = None
        self.route_at = -math.inf
        self.goal: tuple[float, float] | None = None
        self.replans = 0

    def update(self, trail: list, walls: list) -> None:
        """Fold the bot's own trail and wall memory into the grid."""
        for _t, pos in trail or []:
            self.grid.mark_walked(pos[0], pos[2])
        for x, z, _h in walls or []:
            self.grid.mark_wall(x, z)

    def plan(self, start: tuple[float, float], goal: tuple[float, float], now: float,
             force: bool = False) -> list[tuple[float, float]] | None:
        """(Re)plan when stale or forced; returns the smoothed route or None."""
        if (not force and self.route is not None and self.goal == goal
                and now - self.route_at < self.REPLAN_S):
            return self.route
        raw = self.grid.route(start, goal)
        self.replans += 1
        self.route_at = now
        self.goal = goal
        if raw is None:
            self.route = None
            return None
        self.route = self.grid.smooth(raw)
        return self.route

    def next_waypoint(self, pos: tuple[float, float]) -> tuple[float, float] | None:
        """The first route point not yet reached (drop waypoints within WP_REACHED)."""
        if not self.route:
            return None
        x, z = pos
        while len(self.route) > 1:
            wx, wz = self.route[0]
            if math.hypot(wx - x, wz - z) <= self.WP_REACHED:
                self.route.pop(0)
            else:
                break
        return self.route[0]

    def save(self) -> None:
        self.grid.save()
