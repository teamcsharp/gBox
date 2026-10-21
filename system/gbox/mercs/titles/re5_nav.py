"""RE5's own navigation mesh, read from RAM, for routes on a Mercenaries stage (found live 2026-10-21 on the Spark).

The game's AI walks a triangle mesh it keeps loaded for the stage:

    sAI [0x017BD4C8] +0x24 -> cAIPathFinding, +0x14 -> rNavigationMesh (the stage's; 0 between rounds)
    rNavigationMesh +0x70 -> points, +0x74 their count   (16 bytes each: f32 x, y, z, -)
                    +0x78 -> nodes,  +0x7C their count   (32 bytes each: +0x04 index, +0x10 -> u32 vertex indices,
                                                          +0x14 their count (3), +0x18 -> links, +0x1C link count)
    a link (16 bytes): +0x00 u32 the neighbour node, +0x08 u32 the shared edge (0: v0-v1, 1: v1-v2, 2: v2-v0),
                       +0x0C f32 a cost

Public Assembly (stage s400): 1,638 points, 2,187 triangles. NavMesh.route() runs A* over the triangles and returns
waypoints through the shared edges' midpoints, so a bot can walk to a time bonus the way the Majini walk.
"""
from __future__ import annotations

import heapq
import hashlib
import json
import math
import struct
from pathlib import Path

S_AI, AI_PATHFINDING, PF_NAVMESH = 0x017BD4C8, 0x24, 0x14
NM_POINTS, NM_NPOINTS, NM_NODES, NM_NNODES = 0x70, 0x74, 0x78, 0x7C
NODE_SIZE, NODE_VERTS, NODE_NVERTS, NODE_LINKS, NODE_NLINKS = 0x20, 0x10, 0x14, 0x18, 0x1C
LINK_SIZE = 0x10
MAX_POINTS, MAX_NODES = 20000, 30000
CELL = 400.0                                           # the grid that finds a position's triangle (cm)
Y_SLACK = 160.0                                        # a triangle holds a position this far above / below it
AVOID_R = 60.0                                         # a crossing to avoid: its portal within this
STEP_DY = 110.0                                        # a crossing between levels: a waypoint of its own
STEEP_NY = 0.5                                         # a face leaning more than 60 deg: a crossing (151 of Public
                                                       # Assembly's 2,187 triangles)


def _ok(p) -> bool:
    return isinstance(p, int) and 0x30000000 <= p < 0x40000000


def _u32(m, a) -> int:
    return struct.unpack(">I", m.rd(a, 4))[0]


class NavMesh:
    def __init__(self, points: list, tris: list, links: list, ptr: int = 0):
        self.points, self.tris, self.links, self.ptr = points, tris, links, ptr
        geometry = hashlib.sha256()
        for p in points:
            geometry.update(struct.pack(">3f", *p))
        for tri in tris:
            geometry.update(struct.pack(">3I", *tri))
        self.sig = f"{len(points)}-{len(tris)}-{geometry.hexdigest()[:16]}"  # learned crossings belong to this geometry
        topology = hashlib.sha256()
        for u, outgoing in enumerate(links):
            for v, edge, _ in sorted(outgoing):
                topology.update(struct.pack(">3I", u, v, edge))
        self.learning_sig = self.sig + "-" + topology.hexdigest()[:12]
        self.centre = [tuple(sum(points[v][k] for v in t) / 3.0 for k in range(3)) for t in tris]
        self.steep = [self._steep(t) for t in tris]        # a ladder's or a drop's face: a crossing between levels
        self.grid: dict = {}
        for i, t in enumerate(tris):
            xs, zs = [points[v][0] for v in t], [points[v][2] for v in t]
            for gx in range(int(math.floor(min(xs) / CELL)), int(math.floor(max(xs) / CELL)) + 1):
                for gz in range(int(math.floor(min(zs) / CELL)), int(math.floor(max(zs) / CELL)) + 1):
                    self.grid.setdefault((gx, gz), []).append(i)
        self._comp: list | None = None

    def _steep(self, t) -> bool:
        """A triangle whose face leans more than STEEP from flat (a ladder, a drop, a wall of the mesh)."""
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = (self.points[v] for v in t)
        ux, uy, uz = bx - ax, by - ay, bz - az
        wx, wy, wz = cx - ax, cy - ay, cz - az
        nx, ny, nz = uy * wz - uz * wy, uz * wx - ux * wz, ux * wy - uy * wx
        n = math.sqrt(nx * nx + ny * ny + nz * nz)
        return n > 0 and abs(ny) / n < STEEP_NY

    # --- where ---
    def member(self, pos) -> int | None:
        """An unambiguous containing floor, with stricter membership than the route endpoint lookup.

        Vertical faces, shared boundaries and overlapping floors at the same height are not evidence of membership.
        A tight floor-height tolerance also keeps a mid-air animation from proving a traversal.
        """
        if len(pos) != 3 or not all(math.isfinite(v) for v in pos):
            return None
        x, y, z = pos
        cell = (int(math.floor(x / CELL)), int(math.floor(z / CELL)))
        candidates = []
        for i in self.grid.get(cell, ()):
            if not self.steep[i] and self._inside(i, x, z):
                height = self._height(i, x, z)
                if height is not None and abs(height - y) < 40.0:
                    candidates.append((abs(height - y), i))
        candidates.sort()
        if not candidates or (len(candidates) > 1 and candidates[1][0] - candidates[0][0] < 1.0):
            return None
        return candidates[0][1]

    def _inside(self, i: int, x: float, z: float) -> bool:
        (ax, _, az), (bx, _, bz), (cx, _, cz) = (self.points[v] for v in self.tris[i])
        d1 = (x - bx) * (az - bz) - (ax - bx) * (z - bz)
        d2 = (x - cx) * (bz - cz) - (bx - cx) * (z - cz)
        d3 = (x - ax) * (cz - az) - (cx - ax) * (z - az)
        neg, pos = (d1 < 0) or (d2 < 0) or (d3 < 0), (d1 > 0) or (d2 > 0) or (d3 > 0)
        return not (neg and pos)

    def find(self, pos) -> int | None:
        """The containing triangle with the nearest floor height; no projection across an unknown gap or wall."""
        if len(pos) != 3 or not all(math.isfinite(v) for v in pos):
            return None
        x, y, z = pos
        cell = (int(math.floor(x / CELL)), int(math.floor(z / CELL)))
        best, best_dy = None, Y_SLACK
        for i in self.grid.get(cell, ()):
            if self._inside(i, x, z):
                height = self._height(i, x, z)
                if height is None:                        # a vertical face has no floor height at this x/z
                    continue
                dy = abs(height - y)
                if dy < best_dy:
                    best, best_dy = i, dy
        return best

    def floor_segment(self, start, goal) -> bool:
        """Whether a centre-line segment stays on linked, non-steep floors in the recorded direction.

        This proves mesh support, not clearance from dynamic objects or the character's collision radius. In
        particular, adjacent floor faces without a link are not an opening, and a ladder cannot be skipped.
        """
        if any(len(p) != 3 or not all(math.isfinite(v) for v in p) for p in (start, goal)):
            return False
        ax, az = (math.floor(start[k] / CELL) for k in (0, 2))
        bx, bz = (math.floor(goal[k] / CELL) for k in (0, 2))
        if (abs(bx - ax) + 1) * (abs(bz - az) + 1) > 4096:
            return False
        candidates = set()
        for x in range(min(ax, bx), max(ax, bx) + 1):
            for z in range(min(az, bz), max(az, bz) + 1):
                candidates.update(self.grid.get((x, z), ()))
        intervals = {}
        eps = 1e-7
        for i in candidates:
            if self.steep[i]:
                continue
            vertices = [self.points[v] for v in self.tris[i]]
            area = _area2(*vertices)
            if abs(area) < 1e-6:
                continue
            lo, hi = 0.0, 1.0
            for j in range(3):
                a, b = vertices[j], vertices[(j + 1) % 3]
                before, after = _area2(a, b, start) / area, _area2(a, b, goal) / area
                delta = after - before
                if abs(delta) < eps:
                    if before < -eps:
                        hi = -1.0
                        break
                elif delta > 0:
                    lo = max(lo, -before / delta)
                else:
                    hi = min(hi, -before / delta)
            if lo > hi + eps:
                continue
            # The segment must follow the actual floor, not overlap a different storey in x/z.
            supported = True
            for t in (lo, hi):
                p = tuple(start[k] + t * (goal[k] - start[k]) for k in range(3))
                height = self._height(i, p[0], p[2])
                if height is None or abs(height - p[1]) >= 40.0:
                    supported = False
                    break
            if supported:
                intervals[i] = (lo, hi)
        reached = {i: 0.0 for i, (lo, hi) in intervals.items() if lo <= eps and hi >= -eps}
        queue = [(0.0, i) for i in reached]
        heapq.heapify(queue)
        while queue:
            entry, u = heapq.heappop(queue)
            if entry != reached[u]:
                continue
            if intervals[u][1] >= 1.0 - eps:
                return True
            for v, edge, _ in self.links[u]:
                if v not in intervals or not 0 <= edge < 3:
                    continue
                # Only an actual shared edge authorizes ordinary floor travel. Off-mesh action links keep
                # their explicit waypoint/prompt handling in route().
                shared = {self.tris[u][edge], self.tris[u][(edge + 1) % 3]}
                if not shared <= set(self.tris[v]):
                    continue
                p, q = (self.points[x] for x in shared)
                rx, rz = goal[0] - start[0], goal[2] - start[2]
                sx, sz = q[0] - p[0], q[2] - p[2]
                px, pz = p[0] - start[0], p[2] - start[2]
                cross = rx * sz - rz * sx
                if abs(cross) > eps:
                    portal_lo = portal_hi = (px * sz - pz * sx) / cross
                    along_edge = (px * rz - pz * rx) / cross
                    if not -eps <= along_edge <= 1.0 + eps:
                        continue
                else:
                    length2 = rx * rx + rz * rz
                    if length2 <= eps or abs(px * rz - pz * rx) > eps:
                        continue
                    portal_lo, portal_hi = sorted(((px * rx + pz * rz) / length2,
                        ((q[0] - start[0]) * rx + (q[2] - start[2]) * rz) / length2))
                at = max(entry, intervals[v][0], portal_lo)
                if at <= min(intervals[u][1], intervals[v][1], portal_hi) + eps and at < reached.get(v, math.inf):
                    reached[v] = at
                    heapq.heappush(queue, (at, v))
        return False

    def _height(self, i, x, z):
        """Height on a sloping triangle; its centroid can be metres above a player at the ramp's foot."""
        a, b, c = (self.points[v] for v in self.tris[i])
        det = (b[2] - c[2]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[2] - c[2])
        if abs(det) < 1e-6:
            return None
        u = ((b[2] - c[2]) * (x - c[0]) + (c[0] - b[0]) * (z - c[2])) / det
        v = ((c[2] - a[2]) * (x - c[0]) + (a[0] - c[0]) * (z - c[2])) / det
        return u * a[1] + v * b[1] + (1.0 - u - v) * c[1]

    def component(self, i: int) -> int:
        """Weakly connected islands for a cheap rejection test; route() still respects one-way drop links."""
        if self._comp is None:
            comp = [-1] * len(self.tris)
            adjacent = [set() for _ in self.tris]
            for a, links in enumerate(self.links):
                for b, _, _ in links:
                    if 0 <= b < len(comp):
                        adjacent[a].add(b)
                        adjacent[b].add(a)
            for s in range(len(self.tris)):
                if comp[s] >= 0:
                    continue
                stack, comp[s] = [s], s
                while stack:
                    a = stack.pop()
                    for b in adjacent[a]:
                        if comp[b] < 0:
                            comp[b] = s
                            stack.append(b)
            self._comp = comp
        return self._comp[i]

    # --- routes ---
    def _portal(self, a: int, edge: int) -> tuple:
        t = self.tris[a]
        p, q = self.points[t[edge % 3]], self.points[t[(edge + 1) % 3]]
        return tuple((p[k] + q[k]) / 2.0 for k in range(3))

    def route(self, start, goal, avoid=(), pull=True) -> list | None:
        """Waypoints from start to goal (positions): the corners of the string-pulled path through the shared edges of
        the cheapest triangle path (pull=False: every edge's midpoint), then the goal itself; [goal] when both are on
        one triangle; None when the mesh has no way there. A crossing between levels (the next triangle STEP_DY above
        or below: a ladder, a drop) is always a waypoint of its own, at the edge's middle. avoid: positions of
        crossings the player could not take (an AI-only drop or climb): links through a portal within AVOID_R of one
        are left out."""
        a, b = self.find(start), self.find(goal)
        if a is None or b is None:
            return None
        if a == b:
            return [tuple(goal)]
        if self.component(a) != self.component(b):
            return None
        gx, gy, gz = self.centre[b]
        dist = {a: 0.0}
        came: dict = {}
        heap = [(0.0, a)]
        while heap:
            _, u = heapq.heappop(heap)
            if u == b:
                break
            cu = self.centre[u]
            for v, edge, _cost in self.links[u]:
                if not 0 <= v < len(self.tris):
                    continue
                if avoid and any(math.dist(self._portal(u, edge), q) < AVOID_R for q in avoid):
                    continue
                cv = self.centre[v]
                nd = dist[u] + math.dist(cu, cv)
                if nd < dist.get(v, math.inf):
                    dist[v], came[v] = nd, (u, edge)
                    heapq.heappush(heap, (nd + math.dist(cv, (gx, gy, gz)), v))
        if b not in came:
            return None
        hops, v = [], b
        while v != a:
            u, edge = came[v]
            hops.append((u, edge, v))
            v = u
        hops.reverse()
        if not pull:
            return [self._portal(u, edge) for u, edge, _ in hops] + [tuple(goal)]
        out, seg_start, seg = [], tuple(start), []
        for u, edge, v in hops:
            if abs(self.centre[v][1] - self.centre[u][1]) >= STEP_DY or self.steep[u] or self.steep[v]:
                # a level change (a ladder's or a drop's face, or a step between flat triangles): its own waypoint
                mid = self._portal(u, edge)
                out += funnel(seg_start, seg, mid)
                seg_start, seg = mid, []
            else:
                seg.append(self._edge(u, edge, v))
        return out + funnel(seg_start, seg, tuple(goal))

    def _edge(self, u: int, edge: int, v: int) -> tuple:
        """The shared edge as (left, right) seen walking from u into v (a consistent handedness, for funnel())."""
        t = self.tris[u]
        p, q = self.points[t[edge % 3]], self.points[t[(edge + 1) % 3]]
        cu, cv = self.centre[u], self.centre[v]
        dx, dz = cv[0] - cu[0], cv[2] - cu[2]
        return (p, q) if dx * (p[2] - cu[2]) - dz * (p[0] - cu[0]) > 0 else (q, p)

    def route_length(self, start, goal, avoid=()) -> float | None:
        """The length (cm, in x / z) of route(start, goal), or None without one."""
        r = self.route(start, goal, avoid=avoid)
        if r is None:
            return None
        pts = [tuple(start)] + r
        return sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][2] - pts[i][2]) for i in range(len(pts) - 1))


class Learning:
    """Bounded observations, not new navigation links or proof that a prompted animation completed.

    Only consecutive positions on directly linked floors count as a successful directed crossing. Vertical-face
    chains and skipped triangles remain unclassified; route arrival is recorded separately at the actual goal.
    """
    MAX_GEOMETRIES, MAX_VISITS, MAX_CROSSINGS, MAX_ROUTES = 8, 4096, 8192, 512
    MAX_COUNT, MAX_FILE_BYTES = 1_000_000, 4_000_000
    OUTCOMES = ("started", "arrived", "timed_out", "unreachable", "blocked", "interrupted")

    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.stages = {}
        self.previous = self.last_visit = self.active_route = None
        self.key = None
        if self.path is not None:
            try:
                if self.path.stat().st_size <= self.MAX_FILE_BYTES:
                    self._load(json.loads(self.path.read_text(encoding="utf-8")))
            except (OSError, ValueError, TypeError):
                pass

    @staticmethod
    def _index_key(key, pair=False):
        if not isinstance(key, str) or len(key) > 24:
            return False
        parts = key.split(":")
        return len(parts) == (2 if pair else 1) and all(p.isascii() and p.isdigit() and int(p) < MAX_NODES
                                                      for p in parts)

    def _count(self, value):
        return min(value, self.MAX_COUNT) if type(value) is int and value > 0 else 0

    def _load(self, data):
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("stages"), dict):
            return
        for key, stage in list(data["stages"].items())[-self.MAX_GEOMETRIES:]:
            if not isinstance(key, str) or len(key) > 100 or not isinstance(stage, dict):
                continue
            clean = {"visits": {}, "crossings": {}, "routes": {}}
            for name, cap in (("visits", self.MAX_VISITS), ("crossings", self.MAX_CROSSINGS)):
                rows = stage.get(name)
                if isinstance(rows, dict):
                    clean[name] = {k: self._count(v) for k, v in list(rows.items())[-cap:]
                                   if self._index_key(k, name == "crossings") and self._count(v)}
            rows = stage.get("routes")
            if isinstance(rows, dict):
                for k, v in list(rows.items())[-self.MAX_ROUTES:]:
                    if self._index_key(k, True) and isinstance(v, dict):
                        clean["routes"][k] = {n: self._count(v.get(n)) for n in self.OUTCOMES}
            self.stages[key] = clean

    def _stage(self, mesh):
        key = mesh.learning_sig
        if self.key != key:
            self.suspend()
            self.key = key
        if key not in self.stages:
            if len(self.stages) >= self.MAX_GEOMETRIES:
                del self.stages[next(iter(self.stages))]
            self.stages[key] = {"visits": {}, "crossings": {}, "routes": {}}
        # Keep the active geometry when evicting an old stage, including stages loaded from disk.
        stage = self.stages.pop(key)
        self.stages[key] = stage
        return stage

    def _increment(self, rows, key, cap):
        if key not in rows and len(rows) >= cap:
            del rows[next(iter(rows))]
        rows[key] = min(self.MAX_COUNT, rows.get(key, 0) + 1)

    def observe(self, mesh, pos, now):
        if mesh is None:
            self.suspend()
            return None
        stage = self._stage(mesh)
        node = mesh.member(pos)
        previous, self.previous = self.previous, None
        if node is None or not math.isfinite(now):
            return None
        if self.last_visit != node:
            self._increment(stage["visits"], str(node), self.MAX_VISITS)
            self.last_visit = node
        crossed = None
        if previous is not None:
            old, before, at = previous
            dt = now - at
            if old != node and 0 < dt <= 1.0 and math.dist(before, pos) <= 750.0 * dt + 20.0 \
                    and any(v == node for v, _, _ in mesh.links[old]):
                crossed = f"{old}:{node}"
                self._increment(stage["crossings"], crossed, self.MAX_CROSSINGS)
        self.previous = (node, tuple(pos), now)
        if self.active_route is not None:
            _, _, goal_node, goal = self.active_route
            if node == goal_node and math.dist(pos, goal) <= 140.0:
                self.finish_route("arrived")
        return crossed

    def begin_route(self, mesh, start, goal):
        self.finish_route("interrupted")
        if mesh is None:
            return
        stage = self._stage(mesh)
        a, b = mesh.member(start), mesh.member(goal)
        if a is None or b is None:
            return
        key = f"{a}:{b}"
        if key not in stage["routes"]:
            if len(stage["routes"]) >= self.MAX_ROUTES:
                del stage["routes"][next(iter(stage["routes"]))]
            stage["routes"][key] = {n: 0 for n in self.OUTCOMES}
        row = stage["routes"][key]
        row["started"] = min(self.MAX_COUNT, row["started"] + 1)
        self.active_route = (self.key, key, b, tuple(goal))

    def finish_route(self, outcome):
        route, self.active_route = self.active_route, None
        if route is None or outcome not in self.OUTCOMES or outcome == "started":
            return
        stage = self.stages.get(route[0])
        row = stage["routes"].get(route[1]) if stage else None
        if row is not None:
            row[outcome] = min(self.MAX_COUNT, row[outcome] + 1)

    def suspend(self):
        self.finish_route("interrupted")
        self.previous = self.last_visit = None

    def route_penalty(self, mesh, start, goal):
        """A small additive cost in cm; cannot make a blocked or absent directed route reachable."""
        stage = self.stages.get(mesh.learning_sig)
        if not stage:
            return 0.0
        a, b = mesh.member(start), mesh.member(goal)
        row = stage["routes"].get(f"{a}:{b}", {})
        failures = sum(row.get(k, 0) for k in ("timed_out", "unreachable", "blocked"))
        return min(500.0, 100.0 * failures / (1 + row.get("arrived", 0)))

    def summary(self):
        stage = self.stages.get(self.key, {})
        return {"nav_geometry": self.key, "nav_visited_triangles": len(stage.get("visits", {})),
                "nav_observed_crossings": sum(stage.get("crossings", {}).values()),
                "nav_route_arrivals": sum(row.get("arrived", 0) for row in stage.get("routes", {}).values())}

    def save(self):
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps({"version": 1, "stages": self.stages}, separators=(",", ":")), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass


def _area2(a, b, c) -> float:
    return (c[0] - a[0]) * (b[2] - a[2]) - (b[0] - a[0]) * (c[2] - a[2])


def funnel(start, portals: list, goal) -> list:
    """String pulling (the simple stupid funnel algorithm, in x / z): the corners of the shortest path from start to
    goal through the portals [(left, right), ...], then the goal. [goal] without portals."""
    pts = list(portals) + [(tuple(goal), tuple(goal))]
    apex = left = right = tuple(start)
    ai = li = ri = -1
    out: list = []
    i = 0
    while i < len(pts):
        pl, pr = pts[i]
        if _area2(apex, right, pr) <= 0.0:                 # the right side narrows
            if apex == right or _area2(apex, left, pr) > 0.0:
                right, ri = pr, i
            else:                                           # crossed the left: the left point is a corner
                out.append(left)
                apex, ai = left, li
                left = right = apex
                li = ri = ai
                i = ai + 1
                continue
        if _area2(apex, left, pl) >= 0.0:                  # the left side narrows
            if apex == left or _area2(apex, right, pl) < 0.0:
                left, li = pl, i
            else:
                out.append(right)
                apex, ai = right, ri
                left = right = apex
                li = ri = ai
                i = ai + 1
                continue
        i += 1
    if not out or out[-1] != tuple(goal):
        out.append(tuple(goal))
    return out


def read(m, cache: dict | None = None) -> NavMesh | None:
    """The stage's navigation mesh from RAM (None between rounds); cache: {navmesh pointer: NavMesh} so a round's
    mesh is read once (a few thousand small reads)."""
    sai = _u32(m, S_AI)
    pf = _u32(m, sai + AI_PATHFINDING) if _ok(sai) else 0
    nav = _u32(m, pf + PF_NAVMESH) if _ok(pf) else 0
    if not _ok(nav):
        if cache is not None:
            cache.clear()                              # a later stage can reuse this same rNavigationMesh address
        return None
    pts, npts = _u32(m, nav + NM_POINTS), _u32(m, nav + NM_NPOINTS)
    nodes, nnodes = _u32(m, nav + NM_NODES), _u32(m, nav + NM_NNODES)
    if not (_ok(pts) and _ok(nodes) and 0 < npts <= MAX_POINTS and 0 < nnodes <= MAX_NODES):
        if cache is not None:
            cache.clear()
        return None
    source = (pts, npts, nodes, nnodes)
    if cache is not None and nav in cache and getattr(cache[nav], "source", None) == source:
        return cache[nav]
    raw = m.rd(pts, 16 * npts)
    points = [struct.unpack(">3f", raw[16 * i:16 * i + 12]) for i in range(npts)]
    raw = m.rd(nodes, NODE_SIZE * nnodes)
    tris, links = [], []
    for i in range(nnodes):
        rec = raw[NODE_SIZE * i:NODE_SIZE * (i + 1)]
        vptr, nv = struct.unpack(">II", rec[NODE_VERTS:NODE_VERTS + 8])
        lptr, nl = struct.unpack(">II", rec[NODE_LINKS:NODE_LINKS + 8])
        vs = struct.unpack(">3I", m.rd(vptr, 12)) if _ok(vptr) and nv >= 3 else (0, 0, 0)
        tris.append(tuple(v if v < npts else 0 for v in vs))
        ls = []
        if _ok(lptr) and 0 < nl <= 8:
            lr = m.rd(lptr, LINK_SIZE * nl)
            for k in range(nl):
                nb, _, edge, cost = struct.unpack(">IIIf", lr[LINK_SIZE * k:LINK_SIZE * (k + 1)])
                ls.append((nb, edge, cost))
        links.append(ls)
    mesh = NavMesh(points, tris, links, ptr=nav)
    mesh.source = source
    if cache is not None:
        cache.clear()
        cache[nav] = mesh
    return mesh
