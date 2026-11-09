"""Learned occupancy-grid navigation for the RE5 Switch Mercenaries bot.

The Switch bot prefers its verified native floor mesh (re5_switch_native_nav.py)
for bonus routes. This module also keeps walking and stall observations for
fallback routing. Persistent grids are keyed by verified resource and geometry
identity under gbox-data/mercs/learned/nav_grids/verified/. An unavailable mesh
gets a fresh, nonpersistent grid; old stage-name files are never imported.

Grid: 1 m cells in the XZ plane. Stalls are routing costs, not verified walls:
  0.5  walked (the bot's own trail)
  1.0  unknown (assumed passable, mildly discouraged)
  4.0  near a wall (discouraged)
  16.0 wall memory (strongly discouraged)
A* finds the lowest-cost path; the route is smoothed by line-of-sight.
"""

from __future__ import annotations

import heapq
import hashlib
import json
import logging
import math
import time
from pathlib import Path

log = logging.getLogger(__name__)


def geometry_identity(mesh):
    """Persistent learning belongs to measured geometry, never a menu request."""
    from .re5_nav import NavMesh
    if not isinstance(mesh, NavMesh):
        return None
    content = f"RE5-Switch|{getattr(mesh, 'name', '')}|{mesh.learning_sig}"
    return 'native-' + hashlib.sha256(content.encode()).hexdigest()[:24]


def sync_geometry(bot, mesh):
    """Bind observations before movement, resetting on load gaps and stage changes.

    Old stage-name files were keyed by the *next requested* stage and cannot be
    migrated safely. Verified geometry uses a separate namespace; unknown rooms
    get only a fresh, nonpersistent grid and are never exported as mapped evidence.
    """
    identity = geometry_identity(mesh)
    scope = identity or 'unverified'
    if getattr(bot, '_navigation_scope', None) == scope and getattr(bot, '_nav', None) is not None:
        return
    old = getattr(bot, '_nav', None)
    if old is not None and getattr(old.grid, 'identity', None):
        old.grid.save(force=True)
    stage = getattr(mesh, 'stage_name', None) or 'Unknown stage'
    bot._nav = Navigator(stage, learn_dir=getattr(bot, '_learn_dir', None) if identity else None, identity=identity)
    bot._nav.grid.mesh_sig = mesh.learning_sig if identity else None
    bot._nav.grid.resource = getattr(mesh, 'name', '') if identity else None
    bot._navigation_scope = scope
    bot._trail, bot._walls, bot._dead_ends = [], [], []
    bot._native_bonus, bot._native_route, bot._native_route_active = None, [], False
    bot._reloc, bot._dwell, bot._door_goal = None, None, None
    bot._doors_stage, bot._doors, bot._door_tried = None, [], {}
    bot._wall_hist, bot._wall_push, bot._wall_rec, bot._wall_guard = [], None, None, None
    bot.stats.update(navigation_stage=stage, navigation_identity=identity,
                     navigation_identity_source='native_geometry' if identity else 'unavailable')


def native_bonus_action(bot, mesh, player, bonus, now, mine_sites=()):
    """Follow native floor waypoints; enemy action links wait for the game's prompt."""
    from . import re5_switch as config
    from .re5_nav import Traversal
    from .re5_switch_mines import BLAST_CM, CLEAR_MARGIN_CM
    pos, goal = tuple(player['pos']), tuple(bonus['pos'])
    radius = BLAST_CM + CLEAR_MARGIN_CM
    key = (mesh.sig, bonus['ptr'], goal, tuple(mine_sites))
    state = getattr(bot, '_native_bonus', None)
    def hazard_clear(a, b):
        # Match the mine controller's conservative horizontal exclusion policy.
        dx, dz = b[0]-a[0], b[2]-a[2]
        length2 = dx*dx+dz*dz
        for site in mine_sites:
            t = max(0.,min(1.,((site[0]-a[0])*dx+(site[2]-a[2])*dz)/length2)) if length2 else 0.
            if math.hypot(a[0]+t*dx-site[0],a[2]+t*dz-site[2]) < radius:
                return False
        return True
    def block(reason):
        bot._bonus_block[bonus['ptr']] = now + config.BONUS_BLOCK_S
        bot._bonus = bot._native_bonus = None
        bot._native_route_active, bot._native_route = False, []
        bot.stats['nav_bonus_blocks'] = bot.stats.get('nav_bonus_blocks', 0) + 1
        bot.doing, bot.why = 'walk', reason
        return {'hold': ()}
    if mesh.find(pos, floor_only=True, height_slack=61.) is None:
        return block('native route: current floor is unverified; choose another goal')
    if state is None or state['key'] != key or now-state['at'] >= 2.:
        hazards = [((s[0], pos[1], s[2]), radius) for s in mine_sites]
        path = mesh.route_avoiding_hazards(pos, goal, hazards) if hazards else mesh.route(pos, goal)
        if path is None or any(not hazard_clear(a,b) for a,b in zip([pos]+path,path)):
            return block('native route: no supported path to time bonus; choose another goal')
        waiting = state.get('waiting') if state and state['key'] == key else None
        old = state if state and state['key'] == key else {}
        state = bot._native_bonus = {'key':key, 'at':now, 'route':list(path), 'waiting':waiting,
                                    'anchor':old.get('anchor',pos), 'last':old.get('last',now),
                                    'effort':old.get('effort',0.)}
        bot.stats['nav_bonus_routes'] = bot.stats.get('nav_bonus_routes', 0) + 1
    route = state['route']
    while route:
        waypoint = route[0]
        target = waypoint.approach if isinstance(waypoint, Traversal) else waypoint
        if isinstance(waypoint, Traversal):
            # Only actual arrival on its landing floor consumes the action link.
            if math.dist(pos, waypoint) <= 90. and mesh.floor_segment(pos, waypoint):
                route.pop(0)
                state['waiting'] = None
                continue
            break
        if len(route) <= 1 or math.dist(pos,target) > 75.:
            break
        after = route[1].approach if isinstance(route[1], Traversal) else route[1]
        if not mesh.floor_segment(pos,after) or not hazard_clear(pos,after):
            break
        route.pop(0)
    if not route:
        return None
    bot._native_route_active, bot._native_route = True, list(route)
    waypoint = route[0]
    target = waypoint.approach if isinstance(waypoint, Traversal) else waypoint
    if not mesh.floor_segment(pos,target) or not hazard_clear(pos,target):
        return block('native route: next leg leaves this floor; choose another goal')
    dist = math.dist(pos,target)
    if isinstance(waypoint, Traversal) and dist <= 30.:
        state['waiting'] = now if state['waiting'] is None else state['waiting']
        if now-state['waiting'] >= 8.:
            return block('native route: traversal prompt did not appear; choose another goal')
        bot.doing, bot.why = 'walk', 'native route: at the crossing approach; waiting for its prompt'
        bot.stats['nav_bonus_waiting_prompt'] = True
        face = config.wrap(config.heading(waypoint[0]-pos[0],waypoint[2]-pos[2])-player['rot'])
        return {'hold':bot._turn(face,config.TURN_TOL)}
    bot.stats['nav_bonus_waiting_prompt'] = False
    if len(route) == 1 and not isinstance(waypoint, Traversal) and math.dist(pos,goal) <= config.KNIFE_R:
        return None  # verified final approach: the existing bonus prompt/knife rule takes it
    if dist <= 15. and len(route) > 1:
        return block('native route: corner cannot be skipped on this floor; choose another goal')
    if math.dist(pos,state['anchor']) >= 40.:
        state['anchor'], state['effort'] = pos, 0.
    elif now-state['last'] <= .3:
        state['effort'] += max(0.,now-state['last'])
    state['last'] = now
    if state['effort'] >= 6.:
        return block('native route: no observed progress; choose another goal')
    err = config.wrap(config.heading(target[0]-pos[0],target[2]-pos[2])-player['rot'])
    bot.doing, bot.why = 'walk', 'time bonus: following the native floor route'
    bot.stats['nav_bonus_waypoint'] = [round(v,1) for v in target]
    bot._native_probe_cm = min(config.MESH_PROBE_CM, max(15., dist))
    if abs(err) > math.radians(25):
        return {'hold':bot._turn(err,config.TURN_TOL)}
    return {'hold':(('lup','b') if dist > config.BONUS_WALK_R else ('lup',)) + bot._turn(err,config.TURN_TOL)}

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

    def __init__(self, stage: str, base: Path | None = None, identity: str | None = None):
        self.stage = stage
        self.identity = identity
        self.mesh_sig, self.resource = None, None
        self.cells: dict[tuple[int, int], float] = {}
        self.hazard_cells: frozenset[tuple[int, int]] = frozenset()
        self._dirty = False
        self._last_save = 0.0
        self._base = base
        if base is not None:
            self._load(base)

    # -- persistence ---------------------------------------------------------

    def _path(self, base: Path) -> Path:
        if self.identity:
            return base / 'nav_grids' / 'verified' / f'{self.identity}.json'
        safe = self.stage.replace(" ", "_").replace("/", "-")
        return base / "nav_grids" / f"{safe}.json"

    def _load(self, base: Path) -> None:
        p = self._path(base)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("stage") != self.stage or data.get("schema") != (2 if self.identity else 1):
                return
            if self.identity and data.get('geometry_identity') != self.identity:
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
            payload = {"schema": 2 if self.identity else 1, "stage": self.stage, "cell": CELL,
                       "cells": {f"{k[0]},{k[1]}": round(v, 3) for k, v in self.cells.items()}}
            if self.identity:
                payload['geometry_identity'] = self.identity
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
        if k in self.hazard_cells:
            return C_WALL
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

    def smooth(self, waypoints: list[tuple[float, float]], segment_clear=None) -> list[tuple[float, float]]:
        """Greedy line-of-sight smoothing: keep the furthest visible waypoint."""
        if len(waypoints) <= 2:
            return list(waypoints)
        out = [waypoints[0]]
        i = 0
        while i < len(waypoints) - 1:
            j = len(waypoints) - 1
            while j > i + 1 and not (self.line_of_sight(waypoints[i], waypoints[j])
                                    and (segment_clear is None or segment_clear(waypoints[i], waypoints[j]))):
                j -= 1
            out.append(waypoints[j])
            i = j
        return out


class Navigator:
    """Per-bot navigation state: the grid, the current route, replanning."""

    REPLAN_S = 2.0
    WP_REACHED = 120.0        # cm
    ROUTE_STALE_S = 25.0

    def __init__(self, stage: str, learn_dir: Path | None = None, identity: str | None = None):
        self.grid = OccupancyGrid(stage, base=learn_dir, identity=identity)
        self.route: list[tuple[float, float]] | None = None
        self.route_at = -math.inf
        self.goal: tuple[float, float] | None = None
        self.replans = 0
        self.hazards = ()

    def set_hazards(self, circles) -> None:
        """Temporary (x, z, radius) exclusions; never teach a mine as a permanent wall."""
        circles = tuple(sorted(tuple(map(float, circle)) for circle in circles))
        if circles == self.hazards:
            return
        self.hazards = circles
        cells = set()
        for x, z, radius in circles:
            cx, cz = _key(x, z)
            reach = math.ceil(radius / CELL) + 1
            for dx in range(-reach, reach + 1):
                for dz in range(-reach, reach + 1):
                    k = cx + dx, cz + dz
                    wx, wz = _center(*k)
                    # Exclude every cell that could overlap the disk, including diagonal edges.
                    if math.hypot(wx - x, wz - z) < radius + CELL / math.sqrt(2):
                        cells.add(k)
        self.grid.hazard_cells = frozenset(cells)
        self.route = None
        self.route_at = -math.inf

    def hazard_clear(self, start, end) -> bool:
        """Check the complete segment, including a route's final/direct approach."""
        dx, dz = end[0] - start[0], end[1] - start[1]
        length2 = dx*dx + dz*dz
        for x, z, radius in self.hazards:
            t = max(0., min(1., ((x-start[0])*dx + (z-start[1])*dz) / length2)) if length2 else 0.
            if math.hypot(start[0]+t*dx-x, start[1]+t*dz-z) < radius:
                return False
        return True

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
        self.route = self.grid.smooth(raw, segment_clear=self.hazard_clear)
        return self.route

    def next_waypoint(self, pos: tuple[float, float]) -> tuple[float, float] | None:
        """The first route point not yet reached (drop waypoints within WP_REACHED)."""
        if not self.route:
            return None
        x, z = pos
        while len(self.route) > 1:
            wx, wz = self.route[0]
            if math.hypot(wx - x, wz - z) <= self.WP_REACHED and self.hazard_clear((x, z), self.route[1]):
                self.route.pop(0)
            else:
                break
        return self.route[0]

    def save(self) -> None:
        self.grid.save()
