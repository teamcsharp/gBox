"""Measured RE5 stage hazards, separate from otherwise walkable native floor.

Missile Area's three incinerators come from the operator's s405.arc scene
resource, not a screen estimate. The observed native geometry signature pins
their coordinate frame. Bounds are conservative AABBs of the serialized four
corners (A/B have less than 4 cm skew). No game flag or health is changed.
See docs/research/re5-missile-incinerators.md for source hashes and death replay.
"""
from __future__ import annotations

from dataclasses import dataclass
import heapq
import math


MISSILE_GEOMETRY = "1350-1664-ff6314937b448650"
# Deliberate route clearance, not an assertion about the native flame radius.
BODY_MARGIN_CM = 100.0
VERTICAL_MARGIN_CM = 50.0


def _point(value):
    return (isinstance(value, (tuple, list)) and len(value) == 3
            and all(type(v) in (int, float) and math.isfinite(v) for v in value))


@dataclass(frozen=True)
class Hazard:
    name: str
    low: tuple[float, float, float]
    high: tuple[float, float, float]
    source: str = "s405_sce/native_scene_incinerator"

    def bounds(self, margin=BODY_MARGIN_CM):
        if type(margin) not in (int, float) or not math.isfinite(margin) or not 0 <= margin <= 1000:
            raise ValueError("hazard route margin must be finite and in 0..1000 cm")
        expansion = (margin, VERTICAL_MARGIN_CM, margin)
        return (tuple(v-d for v,d in zip(self.low, expansion)),
                tuple(v+d for v,d in zip(self.high, expansion)))

    def contains(self, pos, *, margin=0., vertical_margin=True):
        if not _point(pos):
            return False
        low, high = self.bounds(margin) if vertical_margin else (self.low, self.high)
        return all(a <= v <= b for a,v,b in zip(low,pos,high))

    def intersects(self, start, end, *, margin=BODY_MARGIN_CM):
        """Slab intersection catches a whole path crossing, even with both ends outside."""
        if not _point(start) or not _point(end):
            return True  # invalid coordinates cannot certify a clear route
        low, high = self.bounds(margin)
        enter, leave = 0., 1.
        for a,b,lo,hi in zip(start,end,low,high):
            delta = b-a
            if abs(delta) < 1e-12:
                if a < lo or a > hi:
                    return False
                continue
            t0,t1 = sorted(((lo-a)/delta,(hi-a)/delta))
            enter,leave = max(enter,t0),min(leave,t1)
            if enter > leave:
                return False
        return True

    def departing(self, start, end, *, margin=BODY_MARGIN_CM):
        """Allow escape from a clearance margin, never entry through the native box.

        At least one horizontal separating axis must grow farther from the
        native volume. This certifies the entire linear leg, including short
        steps still within the margin. It does not waive another hazard.
        """
        if not _point(start) or not _point(end) or not self.contains(start, margin=margin):
            return False
        for axis in (0, 2):
            if start[axis] < self.low[axis] and end[axis] < start[axis]:
                return True
            if start[axis] > self.high[axis] and end[axis] > start[axis]:
                return True
        return False

    def evidence(self):
        return {"name":self.name, "source":self.source, "low_cm":list(self.low),
                "high_cm":list(self.high), "status":"native_scene_lethal_volume",
                "activity":"conservatively_excluded; no live off-state verified"}


INCINERATORS = (
    Hazard("incineratorA", (-1220.1844482421875,60.,-13689.041015625),
           (-458.7967834472656,160.,-12664.556640625)),
    Hazard("incineratorB", (-6996.50830078125,49.234283447265625,-22339.642578125),
           (-6487.57275390625,149.23428344726562,-21639.30078125)),
    Hazard("incineratorC", (-3017.599365234375,461.10687255859375,-23308.724609375),
           (-2421.918701171875,561.1068725585938,-22743.439453125)),
)


def for_mesh(mesh):
    """A requested menu stage or stale display name is insufficient authority."""
    return INCINERATORS if getattr(mesh, "sig", None) == MISSILE_GEOMETRY else ()


def blocked_segment(mesh, start, end, *, margin=BODY_MARGIN_CM, departing=False):
    for hazard in for_mesh(mesh):
        if hazard.intersects(start,end,margin=margin):
            if departing and hazard.departing(start,end,margin=margin):
                continue
            return hazard
    return None


def blocked_path(mesh, start, path, *, margin=BODY_MARGIN_CM, departing=False):
    """Check actual legs and action-link landings, not only a route's endpoint."""
    previous = start
    for waypoint in path:
        approach = getattr(waypoint, "approach", None)
        legs = (approach, waypoint) if approach is not None else (waypoint,)
        for point in legs:
            hit = blocked_segment(mesh, previous, point, margin=margin, departing=departing)
            if hit:
                return hit
            previous = point
    return None


def route(mesh, start, goal, *, avoid=(), clearance=0., blocked_links=(), link_penalties=None,
          margin=BODY_MARGIN_CM):
    """Preserve safe native routes, or find a supported path around scene volumes.

    First remove hazardous native transitions and reuse the mesh's ordinary
    action-link representation. If smoothing still cuts a hazard, a directed
    Dijkstra pass follows shared floor portals and triangle interiors exactly.
    That fallback never invents an off-mesh crossing or converts an action
    link into ordinary walking. Every resulting 3D leg is checked again.
    """
    from .re5_nav import AVOID_R, FloorWaypoint

    if not _point(start) or not _point(goal):
        return None
    options = dict(avoid=avoid,clearance=clearance,blocked_links=blocked_links,link_penalties=link_penalties)
    original = mesh.route(start,goal,**options)
    if not for_mesh(mesh) or original is None:
        return original
    if blocked_path(mesh,start,original,margin=margin,departing=True) is None:
        return original
    if blocked_segment(mesh,goal,goal,margin=margin):
        return None

    # Static scene geometry: cache only transition exclusions, not a player's
    # route or dynamic mines. A different geometry/margin cannot reuse them.
    key = (getattr(mesh,'learning_sig',mesh.sig),margin)
    cached = getattr(mesh,'_stage_hazard_edge_cache',None)
    if cached is None or cached[0] != key:
        excluded = set()
        for u,outgoing in enumerate(mesh.links):
            for v,edge,_ in outgoing:
                if not 0 <= v < len(mesh.tris) or not 0 <= edge < 3:
                    continue
                portal = mesh._portal(u,edge)
                if blocked_path(mesh,mesh.centre[u],[portal,mesh.centre[v]],margin=margin):
                    excluded.add((u,v))
        cached = mesh._stage_hazard_edge_cache = (key,frozenset(excluded))
    forbidden = frozenset(blocked_links) | cached[1]
    alternate = mesh.route(start,goal,avoid=avoid,pull=False,clearance=clearance,
                           blocked_links=forbidden,link_penalties=link_penalties)
    if alternate is not None and blocked_path(mesh,start,alternate,margin=margin,departing=True) is None:
        return alternate

    source,destination = (mesh.find(p,floor_only=True,height_slack=61.) for p in (start,goal))
    if source is None or destination is None:
        return None
    costs,previous,queue = {source:0.},{},[(0.,source)]
    while queue:
        cost,u = heapq.heappop(queue)
        if cost != costs[u]:
            continue
        if u == destination:
            break
        origin = start if u == source else mesh.centre[u]
        for v,edge,_ in mesh.links[u]:
            if not 0 <= v < len(mesh.tris) or not 0 <= edge < 3 or (u,v) in blocked_links \
                    or mesh.steep[u] or mesh.steep[v]:
                continue
            shared = {mesh.tris[u][edge],mesh.tris[u][(edge+1)%3]}
            if not shared <= set(mesh.tris[v]):
                continue
            portal = mesh._portal(u,edge)
            if any(math.dist(portal,q) < AVOID_R for q in avoid):
                continue
            endpoint = goal if v == destination else mesh.centre[v]
            if blocked_path(mesh,origin,[portal,endpoint],margin=margin,departing=True):
                continue
            length = cost+math.dist(origin,portal)+math.dist(portal,endpoint)
            length += max(0.,(link_penalties or {}).get((u,v),0.))
            if length < costs.get(v,math.inf):
                costs[v],previous[v] = length,(u,edge)
                heapq.heappush(queue,(length,v))
    if destination not in previous:
        return None
    hops,node = [],destination
    while node != source:
        u,edge = previous[node]
        hops.append((u,edge,node))
        node = u
    result = []
    for u,edge,v in reversed(hops):
        result.append(FloorWaypoint(mesh._portal(u,edge),(u,v)))
        result.append(tuple(goal) if v == destination else mesh.centre[v])
    if blocked_path(mesh,start,result,margin=margin,departing=True) is not None:
        return None
    if not all(mesh.floor_segment(a,b,blocked_links=blocked_links)
               for a,b in zip([start]+result,result)):
        return None
    return result
