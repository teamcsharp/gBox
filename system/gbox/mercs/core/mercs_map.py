"""The bot-core consumer for the static Mercenaries map format gbox.mercs_map/1 (#9528).

Loads the per-stage JSON that scripts/mercs_map_gen.py builds statically (canonical
gbox-data/mercs/maps/<title>/<stage>.json; bounded committed samples live in
docs/research/) and answers the queries the core needs against a stage:

  wall blocking with the measured wall height span (y up, mm),
  floor containment from the measured floor mask rectangles,
  doorways (vaults/ladders) and chokepoints,
  named places, and shortest routes over the measured block route graph.

Nothing here launches or touches a game session; it is pure computation over the
committed tables, so it runs anywhere the repo does.
"""
from __future__ import annotations

import heapq
import json
import math
from pathlib import Path

FORMAT = "gbox.mercs_map/1"
BLOCKING_KINDS = ("solid", "blocker")  # 'walked' segments are gaps, not blocks


def _dist_point_segment(px, pz, ax, az, bx, bz) -> float:
    """2-D distance from point (px, pz) to segment (a)-(b), in the map units (mm)."""
    dx, dz = bx - ax, bz - az
    l2 = dx * dx + dz * dz
    if l2 == 0.0:
        return math.hypot(px - ax, pz - az)
    t = max(0.0, min(1.0, ((px - ax) * dx + (pz - az) * dz) / l2))
    return math.hypot(px - (ax + t * dx), pz - (az + t * dz))


def _inside_polygon(x, z, poly) -> bool:
    """Even-odd ray cast: is (x, z) inside the [x, z] polygon?"""
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, zi = poly[i]
        xj, zj = poly[j]
        if (zi > z) != (zj > z):
            xcross = (xj - xi) * (z - zi) / (zj - zi) + xi
            if x < xcross:
                inside = not inside
        j = i
    return inside


class MercsMap:
    """One stage of gbox.mercs_map/1, as produced by scripts/mercs_map_gen.py."""

    def __init__(self, data: dict):
        if not isinstance(data, dict) or data.get("format") != FORMAT:
            raise ValueError(f"not a {FORMAT} document (format={data.get('format') if isinstance(data, dict) else type(data).__name__!r})")
        if data.get("units") != "mm":
            raise ValueError("gbox.mercs_map/1 is millimetre-only")
        self.data = data

    # ------------------------------------------------------------------ loading
    @classmethod
    def load(cls, path) -> "MercsMap":
        return cls(json.loads(Path(path).read_text()))

    # -------------------------------------------------------------- stage facts
    @property
    def title(self) -> str:
        return self.data["title"]

    @property
    def stage(self) -> str:
        return self.data["stage"]

    @property
    def room(self) -> str:
        return self.data["room"]

    @property
    def bounds(self) -> dict:
        return self.data["bounds"]

    @property
    def source(self) -> dict:
        return self.data.get("source", {})

    # ------------------------------------------------------------------- walls
    def walls(self) -> list[dict]:
        return self.data.get("walls", [])

    def wall_blocks(self, x: float, z: float, y: float, tol_mm: float = 100.0) -> bool:
        """Is the point (x, z) at height y blocked by a solid/blocker wall?

        A wall only blocks at heights inside its measured span y0..y1, and 'walked'
        segments (the gaps RE5 uses for doorways) never block.
        """
        for w in self.walls():
            if w.get("kind") not in BLOCKING_KINDS:
                continue
            if not (w["y0"] <= y <= w["y1"]):
                continue
            a, b = w["a"], w["b"]
            if _dist_point_segment(x, z, a[0], a[1], b[0], b[1]) <= tol_mm:
                return True
        return False

    # ------------------------------------------------------------------- floor
    def floor_polygons(self) -> list[list]:
        return self.data.get("floor", {}).get("polygons", [])

    def on_floor(self, x: float, z: float) -> bool:
        return any(_inside_polygon(x, z, poly) for poly in self.floor_polygons())

    # ------------------------------------------------------------ map features
    def doorways(self) -> list[dict]:
        return self.data.get("doorways", [])

    def chokepoints(self) -> list[dict]:
        return self.data.get("chokepoints", [])

    def cover(self) -> list[dict]:
        return self.data.get("cover", [])

    def spawns(self) -> dict:
        return self.data.get("spawns", {})

    def chokepoints_within(self, x: float, z: float, within_mm: float) -> list[dict]:
        out = []
        for c in self.chokepoints():
            if math.hypot(x - c["pos"][0], z - c["pos"][1]) <= within_mm:
                out.append(c)
        return out

    # -------------------------------------------------------------- named places
    def places(self) -> dict:
        """Named places as {name: [x, z]} (route-graph floor blocks + bonuses)."""
        return self.data.get("places", {})

    def nearest_place(self, x: float, z: float):
        """(name, [x, z]) of the closest named place, or None when the stage has none."""
        best, best_d = None, None
        for name, pos in self.places().items():
            d = math.hypot(x - pos[0], z - pos[1])
            if best_d is None or d < best_d:
                best, best_d = (name, list(pos)), d
        return best

    # ------------------------------------------------------------- route graph
    def route_nodes(self) -> dict:
        return self.data.get("routes", {}).get("nodes", {})

    def route_edges(self) -> list:
        return self.data.get("routes", {}).get("edges", [])

    def nearest_node(self, x: float, z: float):
        """Route-node id closest to (x, z), or None on an empty graph."""
        best, best_d = None, None
        for nid, node in self.route_nodes().items():
            d = math.hypot(x - node["pos"][0], z - node["pos"][1])
            if best_d is None or d < best_d:
                best, best_d = nid, d
        return best

    def shortest_route(self, place_a: str, place_b: str):
        """Dijkstra over the measured block edges between two named places.

        Returns (node_id_path, cost) or None when either place is missing or the
        blocks are not connected.
        """
        places = self.places()
        if place_a not in places or place_b not in places:
            return None
        start = self.nearest_node(*places[place_a])
        goal = self.nearest_node(*places[place_b])
        if start is None or goal is None:
            return None
        adj: dict[str, list[tuple[str, float]]] = {}
        for a, b, cost in self.route_edges():
            adj.setdefault(a, []).append((b, float(cost)))
            adj.setdefault(b, []).append((a, float(cost)))
        dist = {start: 0.0}
        came: dict[str, str] = {}
        pq = [(0.0, start)]
        seen = set()
        while pq:
            d, n = heapq.heappop(pq)
            if n in seen:
                continue
            seen.add(n)
            if n == goal:
                break
            for m, c in adj.get(n, ()):
                nd = d + c
                if nd < dist.get(m, math.inf):
                    dist[m] = nd
                    came[m] = n
                    heapq.heappush(pq, (nd, m))
        if goal not in dist:
            return None
        path = [goal]
        while path[-1] != start:
            path.append(came[path[-1]])
        path.reverse()
        return path, dist[goal]


def load_map(path) -> MercsMap:
    return MercsMap.load(path)
