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
import time
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


class Traversal(tuple):
    """A candidate action link, never permission to walk across a wall or between storeys.

    Coordinates are the landing; approach stays on the departing floor. Only a game prompt and observed
    arrival can establish that this enemy-navmesh link is also usable by the player.
    """
    def __new__(cls, landing, approach, portal):
        value = super().__new__(cls, landing)
        value.approach, value.portal = tuple(approach), tuple(portal)
        return value


class FloorWaypoint(tuple):
    def __new__(cls, point, link):
        value = super().__new__(cls, point)
        value.link = tuple(link)
        return value


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
    def boundary_context(self, pos, *, radius=600., limit=12):
        """Nearby native floor edges; solid collision is a separate decoder.

        Inspect at most 256 local triangles. Action links remain crossings; only
        edges without a shared-floor continuation are labelled mesh boundaries.
        """
        node = self.find(pos, floor_only=True, height_slack=60.)
        if node is None:
            return {'floor': None, 'edges': [], 'source': 'native_navmesh'}
        gx, gz = int(math.floor(pos[0]/CELL)), int(math.floor(pos[2]/CELL))
        span = min(4, int(math.ceil(radius/CELL)))
        nearby = set()
        for x in range(gx-span, gx+span+1):
            for z in range(gz-span, gz+span+1):
                nearby.update(self.grid.get((x,z), ()))
        edges = []
        for i in sorted(nearby, key=lambda n: math.dist(pos, self.centre[n]))[:256]:
            if self.steep[i] or abs(self.centre[i][1]-pos[1]) > 100.:
                continue
            tri = self.tris[i]
            for edge in range(3):
                a,b = self.points[tri[edge]],self.points[tri[(edge+1)%3]]
                continuations = [(v,e) for v,e,_ in self.links[i] if e%3 == edge]
                shared = any(0<=v<len(self.tris) and not self.steep[v]
                             and {tuple(a),tuple(b)} <= {tuple(self.points[n]) for n in self.tris[v]}
                             for v,_ in continuations)
                if shared:
                    continue
                mid = tuple((u+v)/2 for u,v in zip(a,b))
                distance = math.dist(pos,mid)
                if distance <= radius:
                    edges.append((distance, {'a':list(a),'b':list(b),
                        'kind':'action_link' if continuations else 'mesh_boundary'}))
        edges.sort(key=lambda pair: pair[0])
        return {'floor':node, 'edges':[e for _,e in edges[:limit]], 'source':'native_navmesh',
                'collision_class':'unknown; stationary motion is not proof of a physical wall'}

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

    def find(self, pos, *, floor_only=False, height_slack=Y_SLACK) -> int | None:
        """The containing triangle with the nearest floor height; no projection across an unknown gap or wall."""
        if len(pos) != 3 or not all(math.isfinite(v) for v in pos):
            return None
        x, y, z = pos
        cell = (int(math.floor(x / CELL)), int(math.floor(z / CELL)))
        best, best_dy = None, height_slack
        for i in self.grid.get(cell, ()):
            if floor_only and self.steep[i]:
                continue
            if self._inside(i, x, z):
                height = self._height(i, x, z)
                if height is None:                        # a vertical face has no floor height at this x/z
                    continue
                dy = abs(height - y)
                if dy < best_dy:
                    best, best_dy = i, dy
        return best

    def elevated(self, pos, tri=None) -> bool:
        """Whether pos floats STEP_DY or more above (or below) the floor the mesh has under it: a goal on top of a
        vehicle or a prop. find() accepts up to Y_SLACK, so without this check a route ends on the ground at the
        object's foot and the last waypoint (the goal itself) is a run into its wall."""
        tri = self.find(pos) if tri is None else tri
        if tri is None:
            return True
        height = self._height(tri, pos[0], pos[2])
        return height is None or abs(height - pos[1]) >= STEP_DY


    def floor_segment(self, start, goal, *, blocked_links=()) -> bool:
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
                if (u,v) in blocked_links:
                    continue
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

    def route(self, start, goal, avoid=(), pull=True, blocked_links=(), link_penalties=None) -> list | None:
        """Floor waypoints and explicit candidate Traversal links along the cheapest directed triangle path.

        pull=False uses floor-edge midpoints instead of funnel corners. Steep-face chains and off-mesh links
        retain a floor approach and landing; they cannot become ordinary walk commands. Endpoints must be on
        non-steep floors within 60 cm of their own height. avoid: positions of
        crossings the player could not take (an AI-only drop or climb): links through a portal within AVOID_R of one
        are left out."""
        a, b = (self.find(p, floor_only=True, height_slack=61.0) for p in (start, goal))
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
                if (u, v) in blocked_links:
                    continue
                if not 0 <= v < len(self.tris):
                    continue
                if avoid and any(math.dist(self._portal(u, edge), q) < AVOID_R for q in avoid):
                    continue
                cv = self.centre[v]
                nd = dist[u] + math.dist(cu, cv) + (link_penalties or {}).get((u, v), 0.0)
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
        out, seg_start, seg = [], tuple(start), []
        index = 0
        while index < len(hops):
            u, edge, v = hops[index]
            shared = {self.tris[u][edge % 3], self.tris[u][(edge + 1) % 3]}
            action = self.steep[u] or self.steep[v] or not shared <= set(self.tris[v]) \
                or abs(self.centre[v][1] - self.centre[u][1]) >= STEP_DY
            if action:
                portal = self._portal(u, edge)
                approach = self._inset(u, portal)
                # Cross a steep face as one prompted action; its intermediate vertices are not walkable floors.
                while self.steep[v] and index + 1 < len(hops):
                    index += 1
                    _, edge, v = hops[index]
                if self.steep[v]:
                    return None
                last_u, last_edge, _ = hops[index]
                exit_portal = self._portal(last_u, last_edge)
                shared_exit = {self.tris[last_u][last_edge % 3], self.tris[last_u][(last_edge + 1) % 3]}
                landing = self._inset(v, exit_portal) if shared_exit <= set(self.tris[v]) else self.centre[v]
                out += funnel(seg_start, seg, approach) if pull else seg + [approach]
                out.append(Traversal(landing, approach, portal))
                seg_start, seg = landing, []
            else:
                seg.append(self._edge(u, edge, v) if pull else FloorWaypoint(self._portal(u, edge), (u, v)))
            index += 1
        return out + (funnel(seg_start, seg, tuple(goal)) if pull else seg + [tuple(goal)])

    def _inset(self, node, portal):
        centre = self.centre[node]
        distance = math.dist(centre, portal)
        t = min(1.0, 30.0 / max(distance, 1.0))
        return tuple(portal[k] + t * (centre[k] - portal[k]) for k in range(3))

    def _edge(self, u: int, edge: int, v: int) -> tuple:
        """The shared edge as (left, right) seen walking from u into v (a consistent handedness, for funnel())."""
        t = self.tris[u]
        p, q = self.points[t[edge % 3]], self.points[t[(edge + 1) % 3]]
        cu, cv = self.centre[u], self.centre[v]
        dx, dz = cv[0] - cu[0], cv[2] - cu[2]
        return (p, q) if dx * (p[2] - cu[2]) - dz * (p[0] - cu[0]) > 0 else (q, p)

    def route_length(self, start, goal, avoid=(), blocked_links=(), link_penalties=None) -> float | None:
        """Three-dimensional route length in cm, including changes of elevation, or None without a route."""
        r = self.route(start, goal, avoid=avoid, blocked_links=blocked_links, link_penalties=link_penalties)
        if r is None:
            return None
        pts = [tuple(start)] + r
        return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))

    @staticmethod
    def hazard_segment_clear(start, goal, hazards, *, departing=False):
        """Exact segment distance to current observed spherical avoidance margins.

        A departure from inside a margin must move monotonically away. This
        does not invent collision geometry or persist a temporary bomb as a wall.
        """
        delta = tuple(goal[k]-start[k] for k in range(3))
        length2 = sum(v*v for v in delta)
        for centre,radius in hazards:
            before = math.dist(start,centre)
            t = max(0.,min(1.,sum((centre[k]-start[k])*delta[k] for k in range(3))/max(length2,1e-9)))
            nearest = math.dist(centre,tuple(start[k]+t*delta[k] for k in range(3)))
            if nearest < radius:
                away = sum((start[k]-centre[k])*delta[k] for k in range(3)) >= 0
                if not (departing and before<radius and away and math.dist(goal,centre)>before):
                    return False
        return True

    def route_avoiding_hazards(self, start, goal, hazards, *, avoid=(), blocked_links=(), link_penalties=None):
        """Use a normal route if clear, else find a verified floor detour around transient hazards.

        The alternate graph follows actual directed shared floor edges through
        their portals and triangle interiors. No action link or unseen sidestep
        is created. Coarse meshes without a supported detour return None.
        """
        hazards = tuple(hazards)
        route = self.route(start,goal,avoid=avoid,blocked_links=blocked_links,link_penalties=link_penalties)
        if not hazards or route is None:
            return route
        if all(self.hazard_segment_clear(a,b,hazards) for a,b in zip([start]+route,route)):
            return route
        if not self.hazard_segment_clear(start,start,hazards) or not self.hazard_segment_clear(goal,goal,hazards):
            return None
        source,destination = (self.find(p,floor_only=True,height_slack=61.) for p in (start,goal))
        if source is None or destination is None:
            return None
        costs,previous,queue = {source:0.},{},[(0.,source)]
        while queue:
            cost,u = heapq.heappop(queue)
            if cost != costs[u]:
                continue
            if u == destination:
                break
            origin = start if u==source else self.centre[u]
            for v,edge,_ in self.links[u]:
                if not 0<=v<len(self.tris) or not 0<=edge<3 or (u,v) in blocked_links \
                        or self.steep[u] or self.steep[v]:
                    continue
                shared = {self.tris[u][edge],self.tris[u][(edge+1)%3]}
                if not shared<=set(self.tris[v]):
                    continue
                portal = self._portal(u,edge)
                if any(math.dist(portal,q)<AVOID_R for q in avoid):
                    continue
                endpoint = goal if v==destination else self.centre[v]
                if not self.hazard_segment_clear(origin,portal,hazards) \
                        or not self.hazard_segment_clear(portal,endpoint,hazards):
                    continue
                distance = cost+math.dist(origin,portal)+math.dist(portal,endpoint)+(link_penalties or {}).get((u,v),0.)
                if distance < costs.get(v,math.inf):
                    costs[v],previous[v] = distance,(u,edge)
                    heapq.heappush(queue,(distance,v))
        if destination not in previous:
            return None
        hops,node = [],destination
        while node != source:
            u,edge = previous[node]
            hops.append((u,edge,node))
            node = u
        route = []
        for u,edge,v in reversed(hops):
            route.append(FloorWaypoint(self._portal(u,edge),(u,v)))
            route.append(tuple(goal) if v==destination else self.centre[v])
        if all(self.floor_segment(a,b) and self.hazard_segment_clear(a,b,hazards)
               for a,b in zip([start]+route,route)):
            return route
        return None

    def retreat(self, start, hazard, min_distance=500., *, max_travel=1600., blocked_links=(), link_penalties=None):
        """A measured, monotonic floor route away from an explosive, or None.

        This never guesses blast radius or immunity. The caller supplies its safety
        distance. No ladders, windows, drops or unknown off-mesh links are accepted
        during the escape; every segment has linked floor support. Candidate triangle
        centres are inexpensive and leave the character clear of portal boundaries.
        """
        if any(len(p) != 3 or not all(math.isfinite(v) for v in p) for p in (start, hazard)) \
                or min_distance <= 0 or max_travel <= 0:
            return None
        if math.dist(start, hazard) >= min_distance:
            return []
        node = self.find(start, floor_only=True, height_slack=61.)
        if node is None:
            return None
        # Bounded directed Dijkstra over ordinary floor links, not enemy-only actions.
        queue, costs, previous = [(0., node)], {node: 0.}, {}
        best, endpoint = None, None
        while queue:
            cost, u = heapq.heappop(queue)
            if cost != costs[u] or cost > max_travel:
                continue
            origin = start if u == node else self.centre[u]
            # Large floor triangles can contain a safe escape although their
            # centroid is still inside the safety radius. Probe inset vertices too.
            candidates = [self.centre[u]]
            for index in self.tris[u]:
                vertex, centre = self.points[index], self.centre[u]
                length = math.dist(vertex, centre)
                ratio = min(1., 75. / max(length, 1.))
                candidates.append(tuple(vertex[k] + ratio * (centre[k]-vertex[k]) for k in range(3)))
            candidates = [q for q in candidates if math.dist(q,hazard) >= min_distance
                          and cost + math.dist(origin,q) <= max_travel
                          and sum((q[k]-origin[k])*(origin[k]-hazard[k]) for k in range(3)) >= -20.
                          and self.floor_segment(origin,q)]
            if candidates:
                best, endpoint = u, min(candidates,key=lambda q:math.dist(origin,q))
                break
            for v, edge, _ in self.links[u]:
                if (u, v) in blocked_links or not 0 <= v < len(self.tris) or not 0 <= edge < 3 \
                        or self.steep[v] or abs(self.centre[u][1] - self.centre[v][1]) >= STEP_DY:
                    continue
                shared = {self.tris[u][edge], self.tris[u][(edge + 1) % 3]}
                if not shared <= set(self.tris[v]):
                    continue
                # Never approach the placed mine to reach a purportedly safe endpoint.
                portal = self._portal(u, edge)
                origin = start if u == node else self.centre[u]
                if math.dist(portal, hazard) + 20. < math.dist(origin, hazard) \
                        or math.dist(self.centre[v], hazard) + 20. < math.dist(portal, hazard):
                    continue
                distance = math.dist(origin, portal) + math.dist(portal, self.centre[v])
                penalty = max(0., (link_penalties or {}).get((u, v), 0.))
                candidate = cost + distance + penalty
                if candidate < costs.get(v, math.inf) and candidate <= max_travel:
                    costs[v], previous[v] = candidate, (u, edge)
                    heapq.heappush(queue, (candidate, v))
        if best is None:
            return None
        hops, current = [], best
        while current != node:
            u, edge = previous[current]
            hops.append((u, edge, current))
            current = u
        hops.reverse()
        route = [FloorWaypoint(self._portal(u, edge), (u, v)) for u, edge, v in hops] + [endpoint]
        if all(self.floor_segment(a, b) for a, b in zip([start] + route, route)):
            return route
        return None

    def recovery_points(self, pos, radius=180.0):
        """Nearby same-level floor probes, not proof of collision clearance from an unmapped position."""
        candidates = []
        for i, tri in enumerate(self.tris):
            if self.steep[i]:
                continue
            vertices = [self.points[v] for v in tri]
            for a, b in zip(vertices, vertices[1:] + vertices[:1]):
                dx, dz = b[0] - a[0], b[2] - a[2]
                length2 = dx * dx + dz * dz
                t = max(0., min(1., ((pos[0] - a[0]) * dx + (pos[2] - a[2]) * dz) / max(length2, 1e-9)))
                edge = tuple(a[k] + t * (b[k] - a[k]) for k in range(3))
                q = self._inset(i, edge)
                if abs(q[1] - pos[1]) < 50. and math.dist(q, pos) <= radius:
                    candidates.append(q)
        out = []
        for q in sorted(candidates, key=lambda q: math.dist(q, pos)):
            if all(math.dist(q, other) > 60. for other in out):
                out.append(q)
                if len(out) == 8:
                    break
        return out


class Learning:
    """Bounded observations, not new navigation links or proof that a prompted animation completed.

    Only consecutive positions on directly linked floors count as a successful directed crossing. Vertical-face
    chains and skipped triangles remain unclassified; route arrival is recorded separately at the actual goal.
    """
    MAX_GEOMETRIES, MAX_VISITS, MAX_CROSSINGS, MAX_ROUTES = 8, 4096, 8192, 512
    MAX_COUNT, MAX_FILE_BYTES = 1_000_000, 4_000_000
    MAX_DAMAGE_NODES, MAX_DAMAGE_EVENTS = 512, 128
    DAMAGE_HALF_LIFE_S, DAMAGE_LINK_COST, DAMAGE_MAX_WEIGHT = 1800., 250., 4.
    OUTCOMES = ("started", "arrived", "timed_out", "unreachable", "blocked", "interrupted")

    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.stages = {}
        self.previous = self.last_visit = self.active_route = None
        self.key = None
        self.recent_crossings = []
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
            if isinstance(stage.get('obstructions'),list):
                clean['obstructions'] = []
                for event in stage['obstructions'][-64:]:
                    try:
                        if not isinstance(event,dict) or len(json.dumps(event,allow_nan=False))>6000 \
                                or len(event.get('pos',[]))!=3 or not all(type(v) in (int,float) and math.isfinite(v) for v in event['pos']) \
                                or event.get('source')!='native_navmesh' or len(event.get('edges',[]))>12:
                            continue
                        clean['obstructions'].append(event)
                    except (ValueError,TypeError):
                        continue
            if isinstance(stage.get("mine_sites"), dict):
                clean["mine_sites"] = {
                    node: {name:self._count(row.get(name)) for name in self.MINE_COUNTERS}
                    for node,row in list(stage["mine_sites"].items())[-512:]
                    if self._index_key(node) and isinstance(row,dict)}
            if isinstance(stage.get("damage_risk"), dict):
                clean["damage_risk"] = {}
                for node,row in list(stage["damage_risk"].items())[-self.MAX_DAMAGE_NODES:]:
                    if not self._index_key(node) or not isinstance(row,dict):
                        continue
                    weight, at, pos = row.get("weight"), row.get("at"), row.get("pos")
                    if type(weight) not in (int,float) or not math.isfinite(weight) or not 0 < weight <= self.DAMAGE_MAX_WEIGHT \
                            or type(at) not in (int,float) or not math.isfinite(at) or at < 0 \
                            or not isinstance(pos,(tuple,list)) or len(pos)!=3 \
                            or any(type(v) not in (int,float) or not math.isfinite(v) for v in pos):
                        continue
                    clean["damage_risk"][node] = {"weight":weight,"at":at,"pos":list(pos)}
            if isinstance(stage.get("damage_events"), list):
                clean["damage_events"] = list(dict.fromkeys(event for event in stage["damage_events"][-self.MAX_DAMAGE_EVENTS:]
                                                            if self._damage_id(event)))
            if isinstance(stage.get("stalls"), dict):
                clean["stalls"] = {k: self._count(v) for k, v in list(stage["stalls"].items())[-self.MAX_CROSSINGS:]
                                   if self._index_key(k, True) and self._count(v)}
            if isinstance(stage.get("oscillations"), dict):
                clean["oscillations"] = {k: self._count(v) for k, v in list(stage["oscillations"].items())[-self.MAX_CROSSINGS:]
                                         if self._index_key(k, True) and self._count(v)}
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
                # A later observed traversal weakens a collision hypothesis (enemies can temporarily block paths).
                stalls = stage.get("stalls", {})
                if crossed in stalls:
                    stalls[crossed] = max(0, stalls[crossed] - 1)
                # A-B-A-B in a small area is recorded as route indecision, not a new wall.
                # Two-way links remain traversable and later clean crossings weaken the cost.
                recent = [(a, b, t) for a, b, t in self.recent_crossings if now - t <= 8.]
                recent.append((old, node, now))
                self.recent_crossings = recent[-4:]
                oscillations = stage.setdefault("oscillations", {})
                if self.active_route is not None and len(recent) >= 3 and [(a, b) for a, b, _ in recent[-3:]] == \
                        [(old, node), (node, old), (old, node)]:
                    self._increment(oscillations, crossed, self.MAX_CROSSINGS)
                elif crossed in oscillations:
                    oscillations[crossed] = max(0, oscillations[crossed] - 1)
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
        self.recent_crossings = []

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
                "nav_route_arrivals": sum(row.get("arrived", 0) for row in stage.get("routes", {}).values()),
                "nav_failed_portals": sum(v > 0 for v in stage.get("stalls", {}).values()),
                "nav_oscillating_portals": sum(v > 0 for v in stage.get("oscillations", {}).values()),
                "nav_damage_risk_nodes": len(stage.get("damage_risk", {})),
                "nav_damage_incidents_retained": len(stage.get("damage_events", [])),
                "mine_sites_learned": len(stage.get("mine_sites", {}))}

    # Correlated deaths are retained as observations, never labelled mine kills.
    # Only a future native attacker attribution may populate confirmed_kills.
    MINE_COUNTERS = ("placements", "detonations", "retreats", "damage_windows",
                     "candidate_deaths", "confirmed_kills")

    def note_mine(self, mesh, pos, counter, count=1):
        if mesh is None or counter not in self.MINE_COUNTERS or type(count) is not int or count <= 0:
            return False
        node = mesh.member(pos)
        if node is None:
            return False
        sites = self._stage(mesh).setdefault("mine_sites", {})
        key = str(node)
        if key not in sites and len(sites) >= 512:
            del sites[next(iter(sites))]
        row = sites.setdefault(key,{})
        row[counter] = min(self.MAX_COUNT,row.get(counter,0)+count)
        return True

    def mine_site(self, mesh, pos):
        """A bounded deployment preference; cannot change collision or weapon damage."""
        node = mesh.member(pos) if mesh is not None else None
        row = self.stages.get(mesh.learning_sig,{}).get("mine_sites",{}).get(str(node),{}) if mesh else {}
        placed = row.get("placements",0)
        damage = row.get("damage_windows",0)
        return {**{name:row.get(name,0) for name in self.MINE_COUNTERS},
                "defer": placed >= 2 and damage >= 2 and damage / placed >= .5,
                "evidence": "observed deployment/retreat and nearby death windows; kills require native attribution"}

    def blocked(self, mesh, link):
        if mesh is None or link is None:
            return
        a, b = link
        if not (0 <= a < len(mesh.tris)) or not any(v == b for v, _, _ in mesh.links[a]):
            return
        stage = self._stage(mesh)
        self._increment(stage.setdefault("stalls", {}), f"{a}:{b}", self.MAX_CROSSINGS)

    def obstruction(self, mesh, pos, goal, reason, *, approach=None, native_ray=None):
        if mesh is None or not callable(getattr(mesh,'boundary_context',None)):
            return None
        event = mesh.boundary_context(pos)
        event.update(pos=list(pos), goal=list(goal), reason=str(reason)[:160], at=time.time())
        if approach is not None:
            dx,dz = approach[0]-pos[0],approach[2]-pos[2]
            length = math.hypot(dx,dz)
            if length >= 20.:
                event['blocked_approach'] = {'pos':[pos[0]+100.*dx/length,pos[1],pos[2]+100.*dz/length],
                    'radius':80., 'evidence':'commanded_movement_without_progress', 'wall_object_verified':False}
        if isinstance(native_ray,dict) and all(isinstance(native_ray.get(k),(tuple,list)) and len(native_ray[k])==3
                and all(type(v) in (int,float) and math.isfinite(v) for v in native_ray[k]) for k in ('from','at')):
            event['native_ray'] = {k:list(native_ray[k]) for k in ('from','at')}
            event['native_ray'].update(source='uLaserSight RAM decoder',freshness='unverified context only',wall_object_verified=False)
        stage = self._stage(mesh)
        stage['obstructions'] = (stage.get('obstructions',[])+[event])[-64:]
        return event

    def approach_obstacles(self, mesh, *, now=None):
        """Short-lived hypotheses for this exact geometry; not permanent solid walls."""
        stage = self.stages.get(getattr(mesh,'learning_sig',None),{})
        at = time.time() if now is None else now
        grouped = {}
        for event in stage.get('obstructions',[])[-64:]:
            row = event.get('blocked_approach') or {};p=row.get('pos');when=event.get('at')
            if row.get('evidence')!='commanded_movement_without_progress' or not isinstance(p,list) or len(p)!=3 \
                    or any(type(v) not in (int,float) or not math.isfinite(v) for v in p) \
                    or type(when) not in (int,float) or not math.isfinite(when) or not 0<=at-when<=300.:
                continue
            key = tuple(round(v/80.) for v in p)
            prior = grouped.get(key)
            grouped[key] = {'pos':p,'radius':80.,'at':max(when,(prior or {}).get('at',when)),
                'observations':1+(prior or {}).get('observations',0),
                'reason':'Observed blocked approach; physical wall object unverified',
                'wall_object_verified':False}
        return [row for row in grouped.values() if at-row['at'] <= min(300.,16.*2**min(4,row['observations']-1))][-24:]

    def retry_delay(self, mesh, link):
        count = self.stages.get(getattr(mesh,'learning_sig',None),{}).get('stalls',{}).get(
            ':'.join(map(str,link)) if link else '',0)
        return min(120.,8.*2**min(4,max(0,count-1)))

    @staticmethod
    def _damage_id(value):
        return isinstance(value,str) and len(value)==32 and all(c in '0123456789abcdef' for c in value)

    def _damage_weight(self, row, now):
        return row["weight"] * 2. ** (-max(0., now-row["at"]) / self.DAMAGE_HALF_LIFE_S)

    def note_damage(self, mesh, pos, incident_id, *, observed_at):
        """An observed HP loss makes this measured floor a soft risk, with no cause attribution.

        Caller must persist the incident first. Geometry membership is exact;
        off-floor/ambiguous positions cannot train a nearby floor. Event IDs
        prevent duplicate delivery/replay from increasing the risk repeatedly.
        Existing periodic/final save persists this bounded state.
        """
        if mesh is None or not self._damage_id(incident_id) \
                or type(observed_at) not in (int,float) or not math.isfinite(observed_at) or observed_at < 0:
            return False
        if not isinstance(pos,(tuple,list)) or len(pos)!=3 \
                or any(type(v) not in (int,float) or not math.isfinite(v) for v in pos):
            return False
        node = mesh.member(pos)
        if node is None:
            return False
        stage = self._stage(mesh)
        events = stage.setdefault("damage_events", [])
        if incident_id in events:
            return False
        risk = stage.setdefault("damage_risk", {})
        key = str(node)
        old = risk.get(key)
        if key not in risk and len(risk) >= self.MAX_DAMAGE_NODES:
            del risk[next(iter(risk))]
        risk[key] = {"weight":min(self.DAMAGE_MAX_WEIGHT, 1.+(self._damage_weight(old,observed_at) if old else 0.)),
                     "at":observed_at,"pos":list(pos)}
        events.append(incident_id)
        del events[:-self.MAX_DAMAGE_EVENTS]
        return True

    def link_penalties(self, mesh, *, now=None):
        stage = self.stages.get(mesh.learning_sig, {})
        out = {tuple(map(int, key.split(":"))): min(3000., 500. * count)
               for key, count in stage.get("stalls", {}).items() if count > 0}
        for key, count in stage.get("oscillations", {}).items():
            link = tuple(map(int, key.split(":")))
            if count > 0:
                out[link] = min(4000., out.get(link, 0.) + min(1000., 200. * count))
        at = time.time() if now is None else now
        # Only entering a measured risk floor incurs cost; leaving it remains
        # available. No incident can create a link or make a checkpoint unreachable.
        if stage.get("damage_risk") and type(at) in (int,float) and math.isfinite(at):
            risks = {int(node):weight for node,row in stage["damage_risk"].items()
                     if (weight:=self._damage_weight(row,at)) >= .01}
            for u, links in enumerate(mesh.links):
                for v, _, _ in links:
                    weight = risks.get(v,0.)
                    cost = 25. * round(min(1000., self.DAMAGE_LINK_COST*weight)/25.)
                    if cost > 0:
                        # Route-cache signatures must not change every tick as
                        # time passes; decay only changes meaningful cost steps.
                        out[(u,v)] = out.get((u,v),0.) + cost
        return out

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


def read(m, cache: dict | None = None, s_ai: int | None = None) -> NavMesh | None:
    """The stage's navigation mesh from RAM (None between rounds); cache: {navmesh pointer: NavMesh} so a round's
    mesh is read once (a few thousand small reads). s_ai overrides the s_ai singleton address (RE6's chain)."""
    sai = _u32(m, S_AI) if s_ai is None else s_ai
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
