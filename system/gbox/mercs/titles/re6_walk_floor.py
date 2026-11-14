"""Local RE6 walking proof over the supplied native navigation graph.

This does not establish that a cached graph belongs to the active stage. The
3:1 rise/run ceiling is a conservative controller policy, not a recovered
native maximum-slope flag. Near-vertical connected NAV triangles can represent
transitions that ordinary walking cannot certify; native traversal owns those.
"""
from __future__ import annotations

import math

from .re6_floor import floor_at

MAX_GRADE = 3.
FEET_TOLERANCE_CM = 30.
MAX_TRIANGLES = 256
EPS = 1e-8


def _plane(mesh, triangle):
    try:
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = [mesh.V[v] for v in mesh.T[triangle]]
        det = (bx-ax)*(cz-az)-(cx-ax)*(bz-az)
        if not math.isfinite(det) or abs(det) < 1e-9:
            return None
        gx = ((by-ay)*(cz-az)-(cy-ay)*(bz-az))/det
        gz = ((bx-ax)*(cy-ay)-(cx-ax)*(by-ay))/det
        return (gx, gz) if math.isfinite(gx) and math.isfinite(gz) else None
    except (IndexError, KeyError, TypeError, ValueError, OverflowError):
        return None


def triangle_walkable_all_directions(mesh, triangle):
    """A stale-yaw disk needs every direction's grade, not only one bearing."""
    plane = _plane(mesh, triangle)
    return plane is not None and math.hypot(*plane) <= MAX_GRADE


def _interval(mesh, triangle, start, end):
    """Exact parameter interval of the projected line inside one triangle."""
    (ax, _, az), (bx, _, bz), (cx, _, cz) = [mesh.V[v] for v in mesh.T[triangle]]
    det = (bz-cz)*(ax-cx)+(cx-bx)*(az-cz)
    if not math.isfinite(det) or abs(det) < 1e-9:
        return None

    def weights(point):
        x, _, z = point
        a = ((bz-cz)*(x-cx)+(cx-bx)*(z-cz))/det
        b = ((cz-az)*(x-cx)+(ax-cx)*(z-cz))/det
        return a, b, 1-a-b

    first, last = weights(start), weights(end)
    lo, hi = 0., 1.
    for a, b in zip(first, last):
        delta = b-a
        if abs(delta) < EPS:
            if a < -EPS:
                return None
        elif delta > 0:
            lo = max(lo, -a/delta)
        else:
            hi = min(hi, -a/delta)
    return (max(0., lo), min(1., hi)) if lo <= hi+EPS else None


def _on_edge(mesh, edge, x, z):
    a, b = (mesh.V[v] for v in edge)
    dx, dz = b[0]-a[0], b[2]-a[2]
    size = dx*dx+dz*dz
    if size < 1e-12:
        return math.hypot(x-a[0], z-a[2]) <= 1e-5
    t = ((x-a[0])*dx+(z-a[2])*dz)/size
    return -EPS <= t <= 1+EPS and math.hypot(x-a[0]-t*dx, z-a[2]-t*dz) <= 1e-5


def walk_segment(mesh, start, end):
    """Prove connected floor and bounded directional grade for the whole step.

    Follow actual shared edges at the line's exit point. Checking every crossed
    triangle also rejects a thin steep ridge between two level endpoints; fixed
    distance sampling and total endpoint rise would miss it. No nearest-floor
    fallback or unlinked overlapping storey can supply this proof.
    """
    if any(not isinstance(p, (list, tuple)) or len(p) != 3 or
           not all(isinstance(v, (int, float)) and math.isfinite(v) for v in p)
           for p in (start, end)):
        return False
    first = floor_at(mesh, start, FEET_TOLERANCE_CM)
    if first is None or not hasattr(mesh, 'edge_nb'):
        return False
    dx, dz = end[0]-start[0], end[2]-start[2]
    length = math.hypot(dx, dz)
    if length <= 1e-6:
        return True
    todo, seen = [(first[0], 0.)], set()
    try:
        while todo and len(seen) < MAX_TRIANGLES:
            k, entered = todo.pop()
            if k in seen:
                continue
            seen.add(k)
            interval, plane = _interval(mesh, k, start, end), _plane(mesh, k)
            if interval is None or plane is None:
                continue
            lo, hi = interval
            if lo > entered+EPS or hi < entered-EPS:
                continue
            if hi-entered > EPS and abs((plane[0]*dx+plane[1]*dz)/length) > MAX_GRADE:
                continue
            if hi >= 1.-EPS:
                return True
            x, z = start[0]+hi*dx, start[2]+hi*dz
            for edge, neighbor in mesh.edge_nb[k].items():
                if neighbor not in seen and _on_edge(mesh, edge, x, z):
                    todo.append((neighbor, hi))
    except (IndexError, KeyError, TypeError, ValueError, OverflowError):
        return False
    return False
