"""RE4 (Switch) stage floor meshes for the Mercenaries bot and the tactical map, in RE4's world units (mm, y up, heading
atan2(dx, dz)).

RE4 keeps no navigation mesh in RAM the way RE5 does (re5_nav.read); each room carries its own collision. The meshes
are built offline from the room packs' SAT collision by gbox.re4_switch_nav (the GameCube navmap's floor rules on the
Switch bytes, which are the GameCube's byte-swapped) and kept per stage in gbox/data/re4_switch_nav/r4xx.json.

Mesh is re5_nav.NavMesh's interface in mm: points, tris, links (neighbour, edge, cost), centre, steep, sig, find,
member, floor_segment, route (with look-ahead clearance, avoid, blocked links), route_length, retreat ... Inside it is a
re5_nav.NavMesh in cm, so every threshold RE5 tuned (find's 61 cm, member's 40 cm, AVOID_R, STEP_DY, the funnel's
clearance) means the same distance on RE4's floor. Two RE4 additions:

* crossings: the links between triangles that share no edge are the room's jump-overs (a fence, a window sill: press
  the action button at the prompt) and ladders. Each carries its own approach, portal and landing; route() hands them
  out as re5_nav.Traversal (landing, .approach, .portal), the shape the RE5 walker already takes at a ladder or drop.
  None of them has been seen taken in game (`verified: false` in the file);
* clear_segment(a, b): a shot line (chest to chest) against the SAT's wall triangles - no wall shots.

nav_for(snap) picks the stage's mesh for a snapshot: by snap["room"] (0x04RR or "r4RR") or a stage name when the
driver has one, else by the player's position on a stage's floor (sticky: the current stage is kept while he stands
on it; another one is taken after SWITCH_MISSES frames off it).
"""
from __future__ import annotations

import base64
import heapq
import json
import math
import struct
import zlib
from pathlib import Path

from . import re5_nav

MM_PER_CM = 10.0
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "re4_switch_nav"
ROOMS = {"r400": "Village", "r402": "Castle", "r403": "Base", "r404": "Waterworld"}
STAGE_ROOMS = {name.lower(): room for room, name in ROOMS.items()}
STAGE_INDEX = {0: "r400", 1: "r402", 2: "r403", 3: "r404"}       # re4_switch.STAGES order (Select Stage)
ON_FLOOR_MM = 600.0                    # a stage holds the player when its floor is within this of his feet
SWITCH_MISSES = 5                      # frames off the current stage's floor before another stage is taken
EYE_MM, CHEST_MM = 1450.0, 1200.0      # the shot line: his gun at about this height, the target's chest
WALL_CELL_MM = 4000.0                  # the wall buckets for clear_segment
BLOCKER_BIT = 0x400                    # re4_navmap: an invisible blocker most rays pass


def _cm(p) -> tuple:
    return tuple(float(v) / MM_PER_CM for v in p[:3])


def _mm(p) -> tuple:
    return tuple(float(v) * MM_PER_CM for v in p[:3])


def _unpack(text: str) -> list[int]:
    raw = zlib.decompress(base64.b64decode(text))
    return list(struct.unpack(f"<{len(raw) // 4}i", raw))


def shared_links(tris, crossings=()) -> list[list[tuple]]:
    """Per triangle [(neighbour, edge, cost)]: both ways over every edge two triangles share (by vertex index), then the
    crossings [(u, v, code, cost)] (code >= 3, code % 3 = u's edge nearest the crossing)."""
    owner: dict = {}
    links = [[] for _ in tris]
    for t, tri in enumerate(tris):
        for e in range(3):
            a, b = tri[e], tri[(e + 1) % 3]
            owner.setdefault((min(a, b), max(a, b)), []).append((t, e))
    for rows in owner.values():
        for t, e in rows:
            for u, _f in rows:
                if u != t:
                    links[t].append((u, e, 0.0))
    for u, v, code, cost in crossings:
        links[u].append((v, code, float(cost)))
    return links


class _CmMesh(re5_nav.NavMesh):
    """re5_nav.NavMesh in cm with explicit crossings {code: (approach, portal, landing, extra cost)}: no steep faces
    (the room's walls are not in the floor; its ladders are crossings), _portal of a crossing is its own portal, and
    route() walks a crossing as one Traversal priced by its length plus its cost."""

    def __init__(self, points, tris, links, crossings: dict):
        self.crossings = crossings
        super().__init__(points, tris, links)
        # the rim: vertices on an edge no floor continues across (a wall, a drop, a fence). The funnel keeps its
        # clearance from these only - the mesh's inner vertices (rectangle corners on open floor) are not obstacles.
        self.rim = set()
        for t, tri in enumerate(self.tris):
            open_edges = {e for _v, e, _c in self.links[t] if 0 <= e < 3}
            for e in range(3):
                if e not in open_edges:
                    self.rim.update((tri[e], tri[(e + 1) % 3]))

    def _portal_pair(self, u: int, edge: int, v: int, clearance: float) -> tuple:
        """The shared edge as (left, right) walking from u into v (re5_nav _edge's handedness), each end on the rim
        moved `clearance` toward the other (both on the rim and closer than twice it: the middle)."""
        t = self.tris[u]
        i, j = t[edge % 3], t[(edge + 1) % 3]
        p, q = self.points[i], self.points[j]
        # left / right about the edge's middle, walking from u's centre through it (re5_nav._edge measures from u's
        # centre along centre-to-centre, which a sliver of a fan can put on one side of both ends)
        cu = self.centre[u]
        mx, mz = (p[0] + q[0]) / 2.0, (p[2] + q[2]) / 2.0
        dx, dz = mx - cu[0], mz - cu[2]
        if not dx * (p[2] - mz) - dz * (p[0] - mx) > 0:
            (p, i), (q, j) = (q, j), (p, i)
        if clearance <= 0.0:
            return p, q
        n = math.hypot(q[0] - p[0], q[2] - p[2])
        if n < 1e-6:
            return p, q
        on_p, on_q = i in self.rim, j in self.rim
        if on_p and on_q:
            s = min(0.5, clearance / n)
            return (tuple(p[k] + s * (q[k] - p[k]) for k in range(3)), tuple(q[k] - s * (q[k] - p[k]) for k in range(3)))
        s = min(clearance / n, 0.95)
        if on_p:
            return tuple(p[k] + s * (q[k] - p[k]) for k in range(3)), q
        if on_q:
            return p, tuple(q[k] - s * (q[k] - p[k]) for k in range(3))
        return p, q

    def _steep(self, t) -> bool:
        return False

    def _portal(self, a: int, edge: int) -> tuple:
        c = self.crossings.get(edge) if edge >= 3 else None
        return tuple(c[1]) if c is not None else super()._portal(a, edge)

    def route(self, start, goal, avoid=(), pull=True, blocked_links=(), link_penalties=None,
              clearance=0.0) -> list | None:
        """re5_nav.NavMesh.route with this mesh's crossings: the same endpoints rule (non-steep floor within 61 cm),
        the same A* over triangle centres, avoid / blocked_links / link_penalties, the funnel with clearance."""
        a, b = (self.find(p, floor_only=True, height_slack=61.0) for p in (start, goal))
        if a is None or b is None:
            return None
        if a == b:
            return [tuple(goal)]
        if self.component(a) != self.component(b):
            return None
        target = self.centre[b]
        dist = {a: 0.0}
        came: dict = {}
        heap = [(0.0, a)]
        penalties = link_penalties or {}
        while heap:
            _, u = heapq.heappop(heap)
            if u == b:
                break
            cu = self.centre[u]
            for v, edge, _cost in self.links[u]:
                if (u, v) in blocked_links or not 0 <= v < len(self.tris):
                    continue
                if avoid and any(math.dist(self._portal(u, edge), q) < re5_nav.AVOID_R for q in avoid):
                    continue
                cv = self.centre[v]
                c = self.crossings.get(edge) if edge >= 3 else None
                step = (math.dist(cu, c[0]) + math.dist(c[0], c[2]) + math.dist(c[2], cv) + c[3]) if c is not None \
                    else math.dist(cu, cv)
                nd = dist[u] + step + penalties.get((u, v), 0.0)
                if nd < dist.get(v, math.inf):
                    dist[v], came[v] = nd, (u, edge)
                    heapq.heappush(heap, (nd + math.dist(cv, target), v))
        if b not in came:
            return None
        hops, v = [], b
        while v != a:
            u, edge = came[v]
            hops.append((u, edge, v))
            v = u
        hops.reverse()
        out, seg_start, seg = [], tuple(start), []
        for u, edge, v in hops:
            c = self.crossings.get(edge) if edge >= 3 else None
            if c is not None:
                approach, portal, landing = tuple(c[0]), tuple(c[1]), tuple(c[2])
                out += re5_nav.funnel(seg_start, seg, approach) if pull else seg + [approach]
                out.append(re5_nav.Traversal(landing, approach, portal))
                seg_start, seg = landing, []
            else:
                seg.append(self._portal_pair(u, edge, v, clearance) if pull
                           else re5_nav.FloorWaypoint(self._portal(u, edge), (u, v)))
        return out + (re5_nav.funnel(seg_start, seg, tuple(goal)) if pull else seg + [tuple(goal)])


def _dp(pts: list, tol: float) -> list:
    """Douglas-Peucker in x / z over plain points (both ends kept)."""
    if len(pts) < 3:
        return list(pts)
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        a, b = pts[i], pts[j]
        dx, dz = b[0] - a[0], b[2] - a[2]
        n2 = dx * dx + dz * dz
        worst, at = -1.0, -1
        for k in range(i + 1, j):
            p = pts[k]
            t = 0.0 if n2 < 1e-9 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[2] - a[2]) * dz) / n2))
            d = math.hypot(p[0] - (a[0] + t * dx), p[2] - (a[2] + t * dz))
            if d > worst:
                worst, at = d, k
        if worst > tol:
            keep[at] = True
            stack += [(i, at), (at, j)]
    return [p for p, k in zip(pts, keep) if k]


def simplify(start, route: list, tol: float) -> list:
    """A route's floor runs thinned (_dp, tol in its units): a staircase of 200 mm cell corners along a wall becomes
    its few real corners; no kept point moves, so the path shifts by at most tol. Traversals and the point before each
    (its approach) stay."""
    out, run, origin = [], [], tuple(start)
    for q in route:
        if isinstance(q, re5_nav.Traversal):
            out += _dp([origin] + run, tol)[1:]
            out.append(q)
            run, origin = [], tuple(q)
        else:
            run.append(q)
    return out + _dp([origin] + run, tol)[1:]


SIMPLIFY_MM = 80.0                     # route corners within this of the line between their neighbours are dropped
                                       # (at most half the route's clearance: 100 routes on r400 at 350 mm kept every
                                       # 100 mm sample on the floor)


def _out(q):
    """A cm waypoint as mm, keeping its kind (Traversal, FloorWaypoint, plain point)."""
    if isinstance(q, re5_nav.Traversal):
        return re5_nav.Traversal(_mm(q), _mm(q.approach), _mm(q.portal))
    if isinstance(q, re5_nav.FloorWaypoint):
        return re5_nav.FloorWaypoint(_mm(q), q.link)
    return _mm(q)


class Mesh:
    """One RE4 stage's floor (mm). See the module docstring."""

    units = "mm"
    geometry_source = "room_collision"

    def __init__(self, points, tris, crossings=(), *, room: str = "", stage: str = "", walls=(), ladders=(),
                 bonuses=(), source: dict | None = None):
        self.points = [tuple(float(v) for v in p[:3]) for p in points]
        self.tris = [tuple(int(v) for v in t[:3]) for t in tris]
        self.crossing_rows = {}
        rows = []
        for c in crossings:
            code = int(c["edge"])
            if code < 3 or not (0 <= int(c["u"]) < len(self.tris) and 0 <= int(c["v"]) < len(self.tris)):
                continue
            self.crossing_rows[code] = dict(c)
            rows.append((int(c["u"]), int(c["v"]), code, float(c.get("cost") or 0.0)))
        self.links = shared_links(self.tris, rows)
        cross_cm = {code: (_cm(c["approach"]), _cm(c["portal"]), _cm(c["landing"]),
                           float(c.get("cost") or 0.0) / MM_PER_CM) for code, c in self.crossing_rows.items()}
        self._cm = _CmMesh([_cm(p) for p in self.points], self.tris, self.links, cross_cm)
        self.centre = [_mm(c) for c in self._cm.centre]
        self.steep = self._cm.steep
        self.sig, self.learning_sig = "re4." + self._cm.sig, "re4." + self._cm.learning_sig
        self.room, self.stage_name = room, stage
        self.source = dict(source or {})
        self.walls = [tuple(w) for w in walls]
        self.ladders = [dict(row) for row in ladders]
        self.bonuses = [dict(row) for row in bonuses]
        # the tactical map's climbs ([x, z, y low, y high]): the ladders' foot and top
        self.climbs = [[int(round(r["pos"][0])), int(round(r["pos"][2])), int(round(min(r["pos"][1], r["top"][1]))),
                        int(round(max(r["pos"][1], r["top"][1])))] for r in self.ladders
                       if isinstance(r.get("pos"), (list, tuple)) and isinstance(r.get("top"), (list, tuple))]
        self._wall_grid: dict | None = None

    # --- where ---
    def find(self, pos, *, floor_only=False, height_slack=re5_nav.Y_SLACK * MM_PER_CM) -> int | None:
        return self._cm.find(_cm(pos), floor_only=floor_only, height_slack=height_slack / MM_PER_CM) \
            if _ok(pos) else None

    def member(self, pos) -> int | None:
        return self._cm.member(_cm(pos)) if _ok(pos) else None

    def _height(self, i, x, z):
        h = self._cm._height(i, x / MM_PER_CM, z / MM_PER_CM)
        return None if h is None else h * MM_PER_CM

    def floor_y(self, x: float, z: float, near_y: float, slack: float = 3000.0) -> float | None:
        """The floor's height under (x, z) nearest near_y (within slack), else None."""
        best, gap = None, slack
        cell = (int(math.floor(x / MM_PER_CM / re5_nav.CELL)), int(math.floor(z / MM_PER_CM / re5_nav.CELL)))
        for i in self._cm.grid.get(cell, ()):
            if self._cm._inside(i, x / MM_PER_CM, z / MM_PER_CM):
                h = self._height(i, x, z)
                if h is not None and abs(h - near_y) < gap:
                    best, gap = h, abs(h - near_y)
        return best

    def on_floor(self, pos, slack: float = ON_FLOOR_MM) -> bool:
        return self.find(pos, floor_only=True, height_slack=slack) is not None

    def elevated(self, pos, tri=None) -> bool:
        return self._cm.elevated(_cm(pos), tri)

    def component(self, i: int) -> int:
        return self._cm.component(i)

    def boundary_context(self, pos, *, radius=6000., limit=12):
        out = self._cm.boundary_context(_cm(pos), radius=radius / MM_PER_CM, limit=limit)
        for e in out.get("edges", ()):
            e["a"], e["b"] = list(_mm(e["a"])), list(_mm(e["b"]))
        out["source"] = "room_collision"
        return out

    def floor_segment(self, start, goal, *, blocked_links=()) -> bool:
        if not (_ok(start) and _ok(goal)):
            return False
        return self._cm.floor_segment(_cm(start), _cm(goal), blocked_links=blocked_links)

    # --- routes ---
    def route(self, start, goal, avoid=(), pull=True, blocked_links=(), link_penalties=None,
              clearance=0.0) -> list | None:
        """Waypoints in mm (plain points, re5_nav.Traversal at a crossing); avoid: crossing portals (mm) to leave out;
        link_penalties: {(u, v): mm}; clearance: mm kept from a portal's ends (re5_nav.NavMesh.route)."""
        if not (_ok(start) and _ok(goal)):
            return None
        pts = self._cm.route(_cm(start), _cm(goal), avoid=tuple(_cm(q) for q in avoid), pull=pull,
                             blocked_links=blocked_links,
                             link_penalties={k: v / MM_PER_CM for k, v in (link_penalties or {}).items()},
                             clearance=clearance / MM_PER_CM)
        if pts is None:
            return None
        out = [_out(q) for q in pts]
        if out and not isinstance(out[-1], re5_nav.Traversal):
            out[-1] = tuple(float(v) for v in goal[:3])      # the goal exactly, not a rounding of it
        tol = min(SIMPLIFY_MM, clearance / 2.0)            # (corners on the rim itself: none may move)
        return simplify(start, out, tol) if pull and tol > 0.0 else out

    def route_length(self, start, goal, avoid=(), blocked_links=(), link_penalties=None) -> float | None:
        r = self.route(start, goal, avoid=avoid, blocked_links=blocked_links, link_penalties=link_penalties)
        if r is None:
            return None
        pts = [tuple(start)] + [tuple(q) for q in r]
        return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))

    hazard_segment_clear = staticmethod(re5_nav.NavMesh.hazard_segment_clear)

    def route_avoiding_hazards(self, start, goal, hazards, *, avoid=(), blocked_links=(), link_penalties=None):
        pts = self._cm.route_avoiding_hazards(_cm(start), _cm(goal), [(_cm(c), r / MM_PER_CM) for c, r in hazards],
                                              avoid=tuple(_cm(q) for q in avoid), blocked_links=blocked_links,
                                              link_penalties={k: v / MM_PER_CM
                                                              for k, v in (link_penalties or {}).items()})
        return None if pts is None else [_out(q) for q in pts]

    def retreat(self, start, hazard, min_distance=5000., *, max_travel=16000., blocked_links=(), link_penalties=None):
        pts = self._cm.retreat(_cm(start), _cm(hazard), min_distance / MM_PER_CM, max_travel=max_travel / MM_PER_CM,
                               blocked_links=blocked_links,
                               link_penalties={k: v / MM_PER_CM for k, v in (link_penalties or {}).items()})
        return None if pts is None else [_out(q) for q in pts]

    def recovery_points(self, pos, radius=1800.0):
        return [_mm(q) for q in self._cm.recovery_points(_cm(pos), radius / MM_PER_CM)]

    # --- line of sight ---
    def _walls_near(self, a, b):
        if self._wall_grid is None:
            grid: dict = {}
            for k, (x0, z0, x1, z1, *_rest) in enumerate(self.walls):
                for gx in range(int(math.floor(min(x0, x1) / WALL_CELL_MM)), int(math.floor(max(x0, x1) / WALL_CELL_MM)) + 1):
                    for gz in range(int(math.floor(min(z0, z1) / WALL_CELL_MM)),
                                    int(math.floor(max(z0, z1) / WALL_CELL_MM)) + 1):
                        grid.setdefault((gx, gz), []).append(k)
            self._wall_grid = grid
        out = set()
        gx0, gx1 = sorted((int(math.floor(a[0] / WALL_CELL_MM)), int(math.floor(b[0] / WALL_CELL_MM))))
        gz0, gz1 = sorted((int(math.floor(a[2] / WALL_CELL_MM)), int(math.floor(b[2] / WALL_CELL_MM))))
        if (gx1 - gx0 + 1) * (gz1 - gz0 + 1) > 4096:
            return range(len(self.walls))
        for gx in range(gx0, gx1 + 1):
            for gz in range(gz0, gz1 + 1):
                out.update(self._wall_grid.get((gx, gz), ()))
        return out

    def blocking_wall(self, a, b, *, eye: float = EYE_MM, chest: float = CHEST_MM):
        """The first wall a shot from a (his feet; the gun at eye above them) to b (the target's feet; his chest at chest
        above) meets: (wall row (x0, z0, x1, z1, lo, hi, attr), t along the shot 0..1, the shot's height there), or None
        when it meets none (the SAT's steep triangles as their footprint and height span; invisible blockers, which most
        rays pass, are left out; floors and ceilings are not tested). An end that is not a position: ("bad end", 0, 0)."""
        if not (_ok(a) and _ok(b)):
            return ("bad end", 0.0, 0.0)
        ax, ay, az = a[0], a[1] + eye, a[2]
        bx, by, bz = b[0], b[1] + chest, b[2]
        rx, rz = bx - ax, bz - az
        best = None
        for k in self._walls_near(a, b):
            x0, z0, x1, z1, lo, hi, attr = self.walls[k][:7]
            if attr & BLOCKER_BIT:
                continue
            sx, sz = x1 - x0, z1 - z0
            den = rx * sz - rz * sx
            if abs(den) < 1e-9:
                continue
            qx, qz = x0 - ax, z0 - az
            t = (qx * sz - qz * sx) / den
            u = (qx * rz - qz * rx) / den
            if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
                y = ay + t * (by - ay)
                if lo <= y <= hi and (best is None or t < best[1]):
                    best = (tuple(self.walls[k][:7]), t, y)
        return best

    def clear_segment(self, a, b, *, eye: float = EYE_MM, chest: float = CHEST_MM) -> bool:
        """Whether a shot from a to b meets none of the room's walls (blocking_wall is None)."""
        return self.blocking_wall(a, b, eye=eye, chest=chest) is None

    def describe(self) -> dict:
        return {"room": self.room, "stage": self.stage_name, "points": len(self.points), "tris": len(self.tris),
                "crossings": len(self.crossing_rows), "walls": len(self.walls), "source": self.geometry_source}


def _ok(p) -> bool:
    try:
        return len(p) >= 3 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in p[:3])
    except TypeError:
        return False


def from_json(data: dict) -> Mesh:
    if data.get("format") != "gbox.re4_switch_nav/1":
        raise ValueError(f"not an RE4 Switch stage mesh (format {data.get('format')!r})")
    flat, idx = _unpack(data["points"]), _unpack(data["tris"])
    points = [tuple(flat[i:i + 3]) for i in range(0, len(flat), 3)]
    tris = [tuple(idx[i:i + 3]) for i in range(0, len(idx), 3)]
    return Mesh(points, tris, data.get("crossings", ()), room=data.get("room", ""), stage=data.get("stage", ""),
                walls=data.get("walls", ()), ladders=data.get("ladders", ()), bonuses=data.get("bonuses", ()),
                source=data.get("source"))


_CACHE: dict = {}
_BOUNDS: dict = {}


def path_of(room: str, data_dir: Path | None = None) -> Path:
    return Path(data_dir or DATA_DIR) / f"{room}.json"


def load(room: str, data_dir: Path | None = None) -> Mesh | None:
    """The stage mesh of a room (r400 ...), read once and kept; None when the file is missing or unreadable."""
    key = (str(data_dir or DATA_DIR), room)
    if key in _CACHE:
        return _CACHE[key]
    try:
        data = json.loads(path_of(room, data_dir).read_text(encoding="utf-8"))
        mesh = from_json(data)
        _BOUNDS[key] = data.get("bounds")
    except (OSError, ValueError, KeyError, TypeError, zlib.error, struct.error):
        mesh = None
    _CACHE[key] = mesh
    return mesh


def bounds(room: str, data_dir: Path | None = None) -> dict | None:
    """A room's bounds without building its mesh ({x: [lo, hi], z, y} in mm)."""
    key = (str(data_dir or DATA_DIR), room)
    if key not in _BOUNDS:
        try:
            _BOUNDS[key] = json.loads(path_of(room, data_dir).read_text(encoding="utf-8")).get("bounds")
        except (OSError, ValueError):
            _BOUNDS[key] = None
    return _BOUNDS[key]


def room_of(value) -> str | None:
    """A room from the driver's hints: 0x04RR, "r4RR", a stage name, or a Select Stage index."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        if 0x0400 <= value <= 0x04FF:
            room = f"r{value & 0xFFF:03x}"
            return room if room in ROOMS else None
        return STAGE_INDEX.get(value)
    text = str(value).strip().lower()
    if text in ROOMS:
        return text
    return STAGE_ROOMS.get(text)


class Picker:
    """Which stage mesh a snapshot stands on (nav_for). Sticky, so a frame in mid-air or on a ladder keeps the stage."""

    def __init__(self, data_dir: Path | None = None, rooms=tuple(ROOMS)):
        self.data_dir, self.rooms = data_dir, tuple(rooms)
        self.room, self.misses, self.how = None, 0, ""

    def _candidates(self, pos) -> list[str]:
        out = []
        for room in self.rooms:
            b = bounds(room, self.data_dir)
            if b and not (b["x"][0] - 2000 <= pos[0] <= b["x"][1] + 2000 and b["z"][0] - 2000 <= pos[2] <= b["z"][1] + 2000
                          and b["y"][0] - 3000 <= pos[1] <= b["y"][1] + 3000):
                continue
            mesh = load(room, self.data_dir)
            if mesh is not None and mesh.on_floor(pos):
                out.append(room)
        return out

    def pick(self, snap: dict) -> Mesh | None:
        snap = snap or {}
        for key in ("room", "stage_room", "stage_name", "stage"):
            room = room_of(snap.get(key))
            if room is not None:
                mesh = load(room, self.data_dir)
                if mesh is not None:
                    self.room, self.misses, self.how = room, 0, f"snapshot {key}"
                    return mesh
        pos = (snap.get("player") or {}).get("pos")
        if not _ok(pos or ()):
            return load(self.room, self.data_dir) if self.room else None
        current = load(self.room, self.data_dir) if self.room else None
        if current is not None and current.on_floor(pos):
            self.misses = 0
            return current
        cands = self._candidates(pos)
        if len(cands) > 1:                                   # two stages' floors here: the enemies' floors decide
            foes = [e.get("pos") for e in snap.get("enemies") or () if _ok(e.get("pos") or ())]
            cands.sort(key=lambda r: -sum(load(r, self.data_dir).on_floor(q) for q in foes))
        if current is not None:
            self.misses += 1
            if self.misses < SWITCH_MISSES or not cands:
                return current
        if not cands:
            return None
        self.room, self.misses, self.how = cands[0], 0, "the player's floor"
        return load(self.room, self.data_dir)


PICKER = Picker()


def nav_for(snap: dict, picker: Picker | None = None) -> Mesh | None:
    """The stage mesh for this snapshot (see Picker); never raises."""
    try:
        return (picker or PICKER).pick(snap)
    except Exception:                                       # noqa: BLE001 - the map never costs the snapshot
        return None


def attach(snap: dict, picker: Picker | None = None) -> dict:
    """snap["nav"] = the stage's mesh (left as it is when the driver already put one there); returns snap."""
    if isinstance(snap, dict) and snap.get("nav") is None:
        snap["nav"] = nav_for(snap, picker)
    return snap
