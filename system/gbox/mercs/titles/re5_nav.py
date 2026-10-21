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
import math
import struct

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
    def _inside(self, i: int, x: float, z: float) -> bool:
        (ax, _, az), (bx, _, bz), (cx, _, cz) = (self.points[v] for v in self.tris[i])
        d1 = (x - bx) * (az - bz) - (ax - bx) * (z - bz)
        d2 = (x - cx) * (bz - cz) - (bx - cx) * (z - cz)
        d3 = (x - ax) * (cz - az) - (cx - ax) * (z - az)
        neg, pos = (d1 < 0) or (d2 < 0) or (d3 < 0), (d1 > 0) or (d2 > 0) or (d3 > 0)
        return not (neg and pos)

    def find(self, pos) -> int | None:
        """The triangle under a position (x, y, z): the one containing it in x / z whose height is nearest; else the
        nearest centre within two grid cells (a position just off the mesh: a ledge, a corner)."""
        x, y, z = pos
        cell = (int(math.floor(x / CELL)), int(math.floor(z / CELL)))
        best, best_dy = None, Y_SLACK
        for i in self.grid.get(cell, ()):
            if self._inside(i, x, z):
                dy = abs(self.centre[i][1] - y)
                if dy < best_dy:
                    best, best_dy = i, dy
        if best is not None:
            return best
        near, near_d = None, 2 * CELL
        for gx in range(cell[0] - 2, cell[0] + 3):
            for gz in range(cell[1] - 2, cell[1] + 3):
                for i in self.grid.get((gx, gz), ()):
                    c = self.centre[i]
                    if abs(c[1] - y) > Y_SLACK:
                        continue
                    d = math.hypot(c[0] - x, c[2] - z)
                    if d < near_d:
                        near, near_d = i, d
        return near

    def component(self, i: int) -> int:
        """The connected part of the mesh a triangle belongs to (the start roof, the street, ...)."""
        if self._comp is None:
            comp = [-1] * len(self.tris)
            for s in range(len(self.tris)):
                if comp[s] >= 0:
                    continue
                stack, comp[s] = [s], s
                while stack:
                    a = stack.pop()
                    for b, _, _ in self.links[a]:
                        if 0 <= b < len(comp) and comp[b] < 0:
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
        return None
    if cache is not None and nav in cache:
        return cache[nav]
    pts, npts = _u32(m, nav + NM_POINTS), _u32(m, nav + NM_NPOINTS)
    nodes, nnodes = _u32(m, nav + NM_NODES), _u32(m, nav + NM_NNODES)
    if not (_ok(pts) and _ok(nodes) and 0 < npts <= MAX_POINTS and 0 < nnodes <= MAX_NODES):
        return None
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
    if cache is not None:
        cache.clear()
        cache[nav] = mesh
    return mesh
