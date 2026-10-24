"""RE4 GC G4BE08 native collision line-test documentation and Python reimplementation.

Native collision system (disassembled from main.dol, Capstone PPC, 2026-10-24):
================================================================================

The game uses a BVH (bounding volume hierarchy) over level triangles for all
line/segment collision queries.  The key routines are:

Triangle filters (called indirectly via function pointers):
  0x800b4b54  filter1(r3=tri, r4=?, r5=?, r6=?, r7=?, r8=?, r9=?) -> r3 bool
              Checks triangle type bits (0x38, 0x40, 0x80) against a mask.
              Early-out for degenerate triangles (zero-area).
  0x800b4fcc  filter2(r3=tri, r4=?, r5=?, r6=?, r7=?, r8=?, r9=?) -> r3 bool
              Additional filter, calls filter1 internally.

Wrapper:
  0x800b4ec8  wrapper(r3=tri, r4=?, r5=?, r6=?, r7=?, r8=?, r9=?) -> r3
              Saves/restores registers, calls filter2 via pointer at 0x8021073c.

BVH triangle walker:
  0x800b70b8  walk_triangles(r3=node, r4=query, ...)
              Iterates over triangles in a BVH leaf node, calls the wrapper
              for each.  Maintains closest-hit state in the query struct.

BVH node test:
  0x800b7478  test_node(r3=node, r4=query, ...)
              Tests a BVH node against the query line.  If leaf, calls
              walk_triangles.  If internal, recurses to children based on
              line-AABB intersection.

BVH walker:
  0x800b7280  walk_bvh(r3=node, r4=query, ...)
              Top-down BVH traversal.  Calls test_node for each node.

Entry points (called via pointer table at 0x8021073c):
  0x800b6c94  entry_point(r3=?, r4=?, r5=?)
              Sets up collision query struct, calls 0x800b7980.
  0x800b6e78  line_test(r3=collision_obj, r4=from, r5=to, r6=result)
              Main line test: iterates over collision objects, calls BVH walker.
              Returns hit flag in r3, result struct gets hit point/normal.

  0x800b6dc8  dispatcher(r3=?, r4=?, r5=?, r6=?, r7=?)
              Selects between 0x800b85b8, 0x800b80e8, 0x800b7c04 based on flags.

  0x800b6354  query_setup(r3=?, r4=?, r5=?)
              Initializes the collision query struct.

  0x800b795c  init(r3=?)
              Small init function.

  0x800b77d8  set_flag(r3=?, r4=?)
              Manipulates collision flags.

SAT line test (separate from BVH):
  0x800b7a9c  sat_test(r3=?, r4=?, r5=?, r6=?)
              Line test against SAT (separating axis theorem) collision data.

Pointer table (data section):
  0x8021073c: [0x800b6c94, 0x800b77d8, 0x800b795c, 0x800b6354, ...]
              Function pointers for the collision system.

Collision query struct layout (from disassembly):
  +0x00: from point (3 x f32)
  +0x0C: to point (3 x f32)
  +0x18: direction (3 x f32, normalized)
  +0x24: length (f32)
  +0x28: hit point (3 x f32)
  +0x34: hit normal (3 x f32)
  +0x40: hit distance (f32)
  +0x44: hit triangle pointer
  +0x48: flags
  +0x4C: filter mask

Result struct:
  +0x00: hit flag (u32)
  +0x04: hit point (3 x f32)
  +0x10: hit normal (3 x f32)
  +0x1C: hit distance (f32)
  +0x20: hit triangle pointer

Signature bytes (first 16 bytes of each key function):
  0x800b4b54: 94 21 ff e0 7c 08 02 a6 90 01 00 24 39 20 00 00
  0x800b4fcc: 94 21 ff e0 7c 08 02 a6 90 01 00 24 39 20 00 00
  0x800b4ec8: 94 21 ff e0 7c 08 02 a6 90 01 00 24 7d 80 00 26
  0x800b70b8: 94 21 ff d0 7c 08 02 a6 90 01 00 34 7c 9c 23 78
  0x800b7280: 94 21 ff d0 7c 08 02 a6 90 01 00 34 7c 7c 1b 78
  0x800b7478: 94 21 ff e0 7c 08 02 a6 90 01 00 24 39 20 00 00
  0x800b6e78: 94 21 ff c0 7c 08 02 a6 90 01 00 44 39 20 00 00

Python reimplementation
========================
The :func:`raycast` function below reimplements the line test using the wall
segments already decoded by :mod:`gbox.re4_navmap`.  It is verified against
the navmap's :func:`sight` (which uses the same data) and can be used by the
bot for a fan of lookahead rays.

The native hook (option a) is not yet implemented; the addresses above are
documented for a future Dolphin code-cave hook.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

__all__ = [
    "NATIVE_ADDRESSES",
    "CollisionHit",
    "raycast",
    "fan",
]

# Documented native addresses (see module docstring for full details).
NATIVE_ADDRESSES = {
    "filter1": 0x800b4b54,
    "filter2": 0x800b4fcc,
    "wrapper": 0x800b4ec8,
    "walk_triangles": 0x800b70b8,
    "test_node": 0x800b7478,
    "walk_bvh": 0x800b7280,
    "line_test": 0x800b6e78,
    "dispatcher": 0x800b6dc8,
    "query_setup": 0x800b6354,
    "sat_test": 0x800b7a9c,
    "pointer_table": 0x8021073c,
}


@dataclass
class CollisionHit:
    """Result of a raycast against the level collision."""
    blocked: bool
    point: tuple[float, float, float] | None = None
    distance: float = 0.0
    normal: tuple[float, float, float] | None = None


def raycast(walls: np.ndarray, a: list[float], b: list[float],
            see_through: bool = True) -> CollisionHit:
    """Cast a ray from *a* to *b* against the wall segments of a stage.

    Parameters
    ----------
    walls : ndarray, shape (N, 7)
        Each row is (x0, z0, x1, z1, y_lo, y_hi, attr) as decoded by
        :mod:`gbox.re4_navmap`.
    a, b : list[float]
        3D endpoints [x, y, z].
    see_through : bool
        If True, fences / window openings (attr & 0x20/0x40/0x400) do not
        block the ray, matching the game's own behavior for bullets and AI
        line-of-sight.

    Returns
    -------
    CollisionHit
        ``blocked`` is True when the segment a->b intersects at least one
        wall.  ``point`` is the first intersection point along the ray,
        ``distance`` is the parametric t (0..1), ``normal`` is the wall
        normal (approximate, from the segment direction).
    """
    if walls is None or len(walls) == 0:
        return CollisionHit(blocked=False)

    w = walls
    if see_through:
        # VAULT_BITS | BLOCKER_BIT from re4_navmap: 0x20 | 0x40 | 0x400 | 0x800
        mask = 0x20 | 0x40 | 0x400 | 0x800
        w = w[(w[:, 6].astype(np.int64) & mask) == 0]

    ax, ay, az = (float(v) for v in a)
    bx, by, bz = (float(v) for v in b)
    dx, dz = bx - ax, bz - az
    ex, ez = w[:, 2] - w[:, 0], w[:, 3] - w[:, 1]
    den = dx * ez - dz * ex
    ok = np.abs(den) > 1e-9
    den = np.where(ok, den, 1.0)
    t = ((w[:, 0] - ax) * ez - (w[:, 1] - az) * ex) / den
    s = ((w[:, 0] - ax) * dz - (w[:, 1] - az) * dx) / den
    y = ay + (by - ay) * t
    hit = ok & (t > 1e-6) & (t < 1 - 1e-6) & (s >= 0) & (s <= 1) & (y >= w[:, 4]) & (y <= w[:, 5])

    if not bool(hit.any()):
        return CollisionHit(blocked=False)

    # First hit along the ray
    t_hit = float(t[hit].min())
    idx = int(np.argmin(np.where(hit, t, np.inf)))
    px = ax + dx * t_hit
    py = ay + (by - ay) * t_hit
    pz = az + dz * t_hit
    # Approximate normal: perpendicular to the wall segment, in the XZ plane
    seg_len = math.hypot(ex[idx], ez[idx])
    if seg_len > 1e-9:
        nx, nz = -ez[idx] / seg_len, ex[idx] / seg_len
    else:
        nx, nz = 0.0, 0.0
    return CollisionHit(
        blocked=True,
        point=(px, py, pz),
        distance=t_hit,
        normal=(nx, 0.0, nz),
    )


def fan(walls: np.ndarray, origin: list[float], heading: float,
        n: int = 5, spread: float = math.pi / 3, length: float = 2000.0,
        height: float = 0.0, see_through: bool = True) -> list[CollisionHit]:
    """Cast a fan of *n* rays from *origin* spread symmetrically around *heading*.

    Each ray is cast at ground level (+ *height*) from *origin* forward
    *length* world units.  Returns a list of :class:`CollisionHit` in
    left-to-right order.
    """
    hits = []
    for i in range(n):
        angle = heading + spread * (i / (n - 1) - 0.5) if n > 1 else heading
        dx = math.sin(angle) * length
        dz = math.cos(angle) * length
        end = [origin[0] + dx, origin[1] + height, origin[2] + dz]
        hits.append(raycast(walls, origin, end, see_through=see_through))
    return hits
