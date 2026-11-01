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


def room_key(state, player):
    """Never reuse a room number alone across PSO's randomized map variants."""
    room = player.get("room")
    landmarks = sorted((str(e.get("class", "")), round(e["x"], 1),
                        round(e.get("y", 0), 1), round(e["z"], 1))
                       for e in state.get("entities", [])
                       if e.get("room") == room and e.get("kind") in ("gate", "object")
                       and all(isinstance(e.get(k), (float, int)) and math.isfinite(e[k]) for k in ("x", "z")))
    geometry = state.get("geometry_identity")
    # Empty rooms with no verified geometry are session-local: persisting a bare
    # room number would transfer a wall into an unrelated randomized layout.
    identity = {"build": "3OE2", "episode": state.get("episode"), "floor": state.get("floor"),
                "difficulty": state.get("difficulty", "unknown"), "room": room,
                "layer": state.get("geometry_layer", ("height-band-4", math.floor(player.get("y", 0) / 4))),
                "geometry": geometry, "landmarks": landmarks}
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest(), bool(geometry or landmarks)


class RoomMap:
    def __init__(self, path=None, size=12.0, floor=None, walls=None):
        self.path = Path(path) if path else None
        self.size = size
        self.walked, self.blocked, self.failures = set(), set(), {}
        self.floor = {self._valid_cell(c) for c in floor} if floor is not None else None
        self.walls = {self._valid_cell(c) for c in (walls or [])}
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
        if b in self.walls or (self.floor is not None and b not in self.floor):
            return False
        if (a, b) in self.blocked:
            return False
        dx, dz = b[0] - a[0], b[1] - a[1]
        # A diagonal may not clip either side of a known corner.
        if dx and dz:
            return self.allowed(a, (b[0], a[1])) and self.allowed(a, (a[0], b[1]))
        return True

    def route(self, start, goal, limit=6000):
        start, goal = self.cell(start), self.cell(goal)
        if self.floor is not None and goal not in self.floor:
            return None
        if goal in self.walls:
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
            geometry = (state.get("collision_grid") or {}) if state.get("geometry_layer") is not None else {}
            self.maps[key] = RoomMap(self.root / (key + ".json") if persistent else None,
                                     size=geometry.get("size", 12.0), floor=geometry.get("floor"), walls=geometry.get("walls"))
        return self.maps[key]

    def save(self):
        for item in self.maps.values():
            item.save()
