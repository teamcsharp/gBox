"""Strict RE6 floor containment; nearest-triangle recovery is not floor proof."""
from __future__ import annotations

import math


def floor_at(mesh, point, max_height_error_cm, *, cell_cm=400.):
    """Return (triangle, actual floor height), never an off-floor nearest point.

    Heights are interpolated at the point, so sloping floors and overlapping
    storeys are checked at the player's feet rather than at triangle centres.
    Missing or malformed geometry supplies no placement/safety evidence.
    """
    if (not isinstance(point, (list, tuple)) or len(point) != 3
            or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in point)):
        return None
    grid, verts, tris = (getattr(mesh, name, None) for name in ('grid', 'V', 'T'))
    if not isinstance(grid, dict) or verts is None or tris is None:
        return None
    x, y, z = point
    best = None
    try:
        for k in grid.get((int(x // cell_cm), int(z // cell_cm)), ()):
            (ax, ay, az), (bx, by, bz), (cx, cy, cz) = (verts[v][:3] for v in tris[k])
            det = (bz - cz) * (ax - cx) + (cx - bx) * (az - cz)
            if not math.isfinite(det) or abs(det) < 1e-9:
                continue
            wa = ((bz - cz) * (x - cx) + (cx - bx) * (z - cz)) / det
            wb = ((cz - az) * (x - cx) + (ax - cx) * (z - cz)) / det
            wc = 1. - wa - wb
            if min(wa, wb, wc) < -1e-9:
                continue
            height = wa * ay + wb * by + wc * cy
            error = abs(height - y)
            if math.isfinite(error) and error <= max_height_error_cm and (best is None or error < best[0]):
                best = error, k, height
    except (IndexError, KeyError, TypeError, ValueError, OverflowError):
        return None
    return (best[1], best[2]) if best is not None else None
