"""Bounded PSO room navigation with persistent, evidence-based blocked edges.

Observed stalls are not a collision mesh. They are kept separately from an
optional verified collision grid, and keyed by the actual static room layout.
"""
from __future__ import annotations

import hashlib
import heapq
import json
import math
from pathlib import Path


def geometry_view(state, player):
    """Select the measured player layer; never borrow the other buddy's grid."""
    if "geometry_players" not in state:
        return state
    slot = player.get("controller")
    if slot not in (1, 2):
        slot = next((k for k, row in state.get("players", {}).items() if row.get("ptr") == player.get("ptr")), None)
    return state["geometry_players"].get(slot, {})


def room_key(state, player):
    """Never reuse a room number alone across PSO's randomized map variants."""
    room = player.get("room")
    landmarks = sorted((str(e.get("class", "")), round(e["x"], 1),
                        round(e.get("y", 0), 1), round(e["z"], 1))
                       for e in state.get("entities", [])
                       if e.get("room") == room and e.get("kind") in ("gate", "object")
                       and all(isinstance(e.get(k), (float, int)) and math.isfinite(e[k]) for k in ("x", "z")))
    view = geometry_view(state, player)
    geometry = view.get("geometry_identity")
    # Empty rooms with no verified geometry are session-local: persisting a bare
    # room number would transfer a wall into an unrelated randomized layout.
    identity = {"build": "3OE2", "episode": state.get("episode"), "floor": state.get("floor"),
                "difficulty": state.get("difficulty", "unknown"), "room": room,
                "layer": view.get("geometry_layer", ("height-band-4", math.floor(player.get("y", 0) / 4))),
                "geometry": geometry, "landmarks": landmarks if not geometry else []}
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest(), bool(geometry or landmarks)


class RoomMap:
    def __init__(self, path=None, size=12.0, floor=None, walls=None, heights=None, max_step=.75, max_slope=.75,
                 recovery=False):
        self.path = Path(path) if path else None
        self.size = size
        # A recovery grid is the margin single-height fallback used when the native
        # projection came back empty: it has a PARTIAL floor and NO authoritative
        # walls, so a cell missing from it is "unknown", not a cliff. route() may
        # therefore relax floor/height MEMBERSHIP for it when the constrained path
        # fails - never for a complete projection (where missing == wall/cliff).
        self.recovery = bool(recovery)
        self._relax = False
        self.walked, self.blocked, self.failures = set(), set(), {}
        self.floor = {self._valid_cell(c) for c in floor} if floor is not None else None
        self.walls = {self._valid_cell(c) for c in (walls or [])}
        self.heights = {self._valid_cell(row[:2]): float(row[2]) for row in (heights or [])}
        self.max_step, self.max_slope = max_step, max_slope
        if any(not math.isfinite(y) for y in self.heights.values()):
            raise ValueError("Invalid collision height")
        if self.path and self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if data.get("version") != 1 or data.get("size") != size:
                    return
                self.walked = {self._valid_cell(c) for c in data.get("walked", [])[:30000]}
                self.blocked = {(self._valid_cell(a), self._valid_cell(b))
                                for a, b in data.get("blocked", [])[:30000]}
            except (OSError, ValueError, TypeError, AttributeError):
                self.walked, self.blocked = set(), set()

    @staticmethod
    def _valid_cell(c):
        if not isinstance(c, (list, tuple)) or len(c) != 2 or any(type(v) is not int or abs(v) > 100000 for v in c):
            raise ValueError("Invalid remembered navigation cell")
        return tuple(c)

    def cell(self, point):
        return math.floor(point[0] / self.size), math.floor(point[1] / self.size)

    def center(self, cell):
        return (cell[0] + .5) * self.size, (cell[1] + .5) * self.size

    def allowed(self, a, b):
        if b in self.walls or (a, b) in self.blocked:
            return False
        # Floor/height MEMBERSHIP is a hard wall only on the primary pass (or any
        # complete projection). When relaxing a RECOVERY grid - which has no wall
        # data and only a partial floor - a cell it simply does not cover is open
        # space, not a cliff; verified walls and learned blocked edges above still
        # apply, and a real step/slope between two KNOWN heights still blocks.
        if not self._relax and self.floor is not None and b not in self.floor:
            return False
        if self.heights and a in self.heights and b in self.heights:
            if abs(self.heights[a] - self.heights[b]) > self.max_step + self.max_slope * self.size * math.dist(a, b):
                return False
        elif not self._relax and self.heights and (a not in self.heights or b not in self.heights):
            return False
        dx, dz = b[0] - a[0], b[1] - a[1]
        # A diagonal may not clip either side of a known corner.
        if dx and dz:
            sides = ((b[0], a[1]), (a[0], b[1]))
            return all(self.allowed(a, side) and self.allowed(side, b) for side in sides)
        return True

    def route(self, start, goal, limit=6000):
        scell, gcell = self.cell(start), self.cell(goal)
        path = self._astar(scell, gcell, limit, relax=False)
        if path is None and self.recovery and (self.floor is not None or self.heights):
            # ONLY for a recovery grid: its partial floor could not connect start to
            # goal, so retry ignoring floor/height membership gaps (never cliffs,
            # walls or learned blocks) - otherwise the caller straight-lines into a
            # wall and wedges. A complete projection is never relaxed, so cliffs /
            # outside-the-floor / walls-below-a-bridge stay hard (fix A, safely).
            path = self._astar(scell, gcell, limit, relax=True)
        return path

    def _astar(self, start, goal, limit, *, relax):
        self._relax = relax
        try:
            if goal in self.walls:
                return None
            if not relax and self.floor is not None and goal not in self.floor:
                return None
            h = lambda c: math.hypot(c[0] - goal[0], c[1] - goal[1])
            frontier, previous, costs = [(h(start), start)], {start: None}, {start: 0.0}
            while frontier and len(previous) <= limit:
                _, cell = heapq.heappop(frontier)
                if cell == goal:
                    route = [cell]
                    while previous[route[-1]] is not None:
                        route.append(previous[route[-1]])
                    return [self.center(c) for c in reversed(route)]
                for dx, dz in ((0, 1), (1, 0), (0, -1), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                    nxt = cell[0] + dx, cell[1] + dz
                    if not self.allowed(cell, nxt):
                        continue
                    cost = costs[cell] + math.hypot(dx, dz) * (1 if nxt in self.walked else 1.6)
                    if cost < costs.get(nxt, float("inf")):
                        costs[nxt], previous[nxt] = cost, cell
                        heapq.heappush(frontier, (cost + h(nxt), nxt))
            return None
        finally:
            self._relax = False

    def observe(self, before, after, intended, *, reliable):
        """Only stable movement with no combat/menu/transition can teach a wall."""
        if not reliable:
            return False
        a, b, target = self.cell(before), self.cell(after), self.cell(intended)
        moved = math.dist(before, after)
        if moved >= 2:
            count = max(1, math.ceil(moved / (self.size / 3)))
            prev = a
            for i in range(count + 1):
                c = self.cell((before[0] + (after[0] - before[0]) * i / count,
                               before[1] + (after[1] - before[1]) * i / count))
                self.walked.add(c)
                self.blocked.discard((prev, c))
                self.blocked.discard((c, prev))
                self.failures.pop((prev, c), None)
                prev = c
            return False
        if a == target or math.dist(before, intended) < self.size / 2:
            return False
        dx, dz = target[0] - a[0], target[1] - a[1]
        nxt = a[0] + (1 if dx > 0 else -1 if dx < 0 else 0), a[1] + (1 if dz > 0 else -1 if dz < 0 else 0)
        key = a, nxt
        self.failures[key] = self.failures.get(key, 0) + 1
        if self.failures[key] < 2:
            return False
        self.blocked.add(key)
        self.blocked.add((nxt, a))
        self.save()
        return True

    def save(self):
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "size": self.size, "walked": sorted(self.walked)[-30000:],
                   "blocked": sorted(self.blocked)[-30000:]}
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(self.path)


class Maps:
    def __init__(self, root):
        self.root, self.maps = Path(root), {}

    def get(self, state, player):
        key, persistent = room_key(state, player)
        if key not in self.maps:
            if len(self.maps) >= 128:
                self.maps.pop(next(iter(self.maps))).save()
            # A flattened whole-level grid must not block a bridge using the wall
            # below it. Only consume a grid whose native provider identifies its
            # current floor layer; otherwise use height-bounded observations.
            view = geometry_view(state, player)
            geometry = (view.get("collision_grid") or {}) if view.get("geometry_layer") is not None else {}
            self.maps[key] = RoomMap(self.root / (key + ".json") if persistent else None,
                                     size=geometry.get("size", 12.0), floor=geometry.get("floor"), walls=geometry.get("walls"),
                                     heights=geometry.get("heights"), max_step=geometry.get("max_step", .75), max_slope=geometry.get("max_slope", .75),
                                     recovery=bool(geometry.get("recovery")))
        return self.maps[key]

    def save(self):
        for item in self.maps.values():
            item.save()
