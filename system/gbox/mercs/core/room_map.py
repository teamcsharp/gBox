"""A stage's real map from its collision, for every walk and shot a Mercenaries bot makes (mm, y up, heading
atan2(dx, dz)): a floor mask and the walls with their height spans (titles.re4_room_map: RE4 Switch's SAT rooms, #9342;
titles.re5_room_map: RE5 Switch's Havok stages, #9360). The title modules pick the table and convert their units.

* a walk is refused when a sample along it (every SAMPLE_MM, the start's own cell aside) falls on a cell without floor
  (off the map: water, a void), when it crosses a wall whose height span meets his body (his feet + BODY_LO_MM ..
  BODY_HI_MM: a wall on the floor below or a beam above his head does not count; an invisible blocker does), when it
  brings him nearer than body_r (BRUSH_R_MM: his half width) to such a wall than he already is (a corner, a shallow
  angle), or when it ends within end_r of one (he would stand pressed to it, the camera inside it). Both margins
  shrink in a gap narrower than they allow (GAP_MARGIN_X of its width): a doorway passes through its middle;
* a shot is refused when it crosses a wall that is not a blocker at the shot's own height there.
"""
from __future__ import annotations

import base64
import math
import zlib

BODY_LO_MM, BODY_HI_MM = 300.0, 1700.0   # his body above his feet: a wall spanning any of it stops a walk
BODY_R_MM = 350.0                        # a walk ending this near such a wall: refused (pressed to it)
BRUSH_R_MM = 300.0                       # a walk bringing him this near one (a corner, a shallow angle): refused
SAMPLE_MM = 125.0                        # the floor along a walk, half a cell at a time
BUCKET_MM = 4000.0                       # the walls' lookup buckets
EYE_MM, CHEST_MM = 1450.0, 1200.0        # a shot from his gun this high to the target's chest this high (RE4's)
SOLID, BLOCKER, WALKED = 0, 1, 2         # a wall's flag (RoomMap)
# A gap (a doorway, a corridor) narrower than the margins allow - walls within twice the margin on both sides of the
# way, their nearest points within twice the margin of each other along it (two jambs, not a jamb and a wall far on) -
# gets margins of this share of its width: through its middle he passes (a 600 mm door: 240 mm a side, his middle
# 300 mm off each jamb), off its middle he does not. His collision radius is not measured: conservative, never shut.
GAP_MARGIN_X = 0.4


def _ok(p) -> bool:
    try:
        return len(p) >= 3 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in p[:3])
    except TypeError:
        return False


def _cross(ax, az, bx, bz, x0, z0, x1, z1):
    """t along a -> b where it crosses the segment (x0, z0) - (x1, z1), or None."""
    rx, rz, sx, sz = bx - ax, bz - az, x1 - x0, z1 - z0
    den = rx * sz - rz * sx
    if abs(den) < 1e-9:
        return None
    qx, qz = x0 - ax, z0 - az
    t = (qx * sz - qz * sx) / den
    u = (qx * rz - qz * rx) / den
    return t if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0 else None


def _dist_seg(px, pz, x0, z0, x1, z1) -> float:
    dx, dz = x1 - x0, z1 - z0
    n2 = dx * dx + dz * dz
    t = 0.0 if n2 < 1e-9 else max(0.0, min(1.0, ((px - x0) * dx + (pz - z0) * dz) / n2))
    return math.hypot(px - (x0 + t * dx), pz - (z0 + t * dz))


def _side(ax, az, bx, bz, px, pz) -> int:
    """Which side of the way a -> b the point p lies on: +1 his left (the larger heading), -1 his right, 0 on it."""
    c = (bx - ax) * (pz - az) - (bz - az) * (px - ax)
    return 0 if abs(c) < 1e-9 else (-1 if c > 0 else 1)


def _closest_side(ax, az, bx, bz, x0, z0, x1, z1) -> tuple:
    """(the least distance between the way a-b and the wall, the side of the way its nearest point lies on, how far
    along the way - mm from a - the way's own nearest point is)."""
    if _cross(ax, az, bx, bz, x0, z0, x1, z1) is not None:
        return 0.0, 0, 0.0
    wx, wz = bx - ax, bz - az
    L2 = wx * wx + wz * wz
    L = math.sqrt(L2)
    best = None
    for px, pz in ((x0, z0), (x1, z1)):                    # a wall end to the way
        t = 0.0 if L2 < 1e-9 else max(0.0, min(1.0, ((px - ax) * wx + (pz - az) * wz) / L2))
        d = math.hypot(px - (ax + t * wx), pz - (az + t * wz))
        if best is None or d < best[0]:
            best = (d, _side(ax, az, bx, bz, px, pz), t * L)
    for qx, qz, s in ((ax, az, 0.0), (bx, bz, L)):         # a way end to the wall: the wall's nearest point
        dx, dz = x1 - x0, z1 - z0
        n2 = dx * dx + dz * dz
        t = 0.0 if n2 < 1e-9 else max(0.0, min(1.0, ((qx - x0) * dx + (qz - z0) * dz) / n2))
        px, pz = x0 + t * dx, z0 + t * dz
        d = math.hypot(qx - px, qz - pz)
        if d < best[0]:
            best = (d, _side(ax, az, bx, bz, px, pz), s)
    return best


def _point_side(a, b, w) -> int:
    """The side of the way a -> b the wall's nearest point to b lies on."""
    dx, dz = w[2] - w[0], w[3] - w[1]
    n2 = dx * dx + dz * dz
    t = 0.0 if n2 < 1e-9 else max(0.0, min(1.0, ((b[0] - w[0]) * dx + (b[2] - w[1]) * dz) / n2))
    return _side(a[0], a[2], b[0], b[2], w[0] + t * dx, w[1] + t * dz)


def _gap(rows, window: float = math.inf) -> float:
    """The way's width between the walls on its two sides, rows (distance, side, wall, along): the least sum of a
    wall's distance on his left and one's on his right whose nearest points lie within window of each other along the
    way - a doorway's two jambs, not a jamb here and a wall far on (infinite with no such pair)."""
    left = [(d, s) for d, side, _w, s in rows if side > 0]
    right = [(d, s) for d, side, _w, s in rows if side < 0]
    return min((dl + dr for dl, sl in left for dr, sr in right if abs(sl - sr) <= window), default=math.inf)


def _dist_segs(ax, az, bx, bz, x0, z0, x1, z1) -> float:
    """The least distance between the segments a-b and (x0, z0)-(x1, z1) (0 when they cross)."""
    if _cross(ax, az, bx, bz, x0, z0, x1, z1) is not None:
        return 0.0
    return min(_dist_seg(ax, az, x0, z0, x1, z1), _dist_seg(bx, bz, x0, z0, x1, z1),
               _dist_seg(x0, z0, ax, az, bx, bz), _dist_seg(x1, z1, ax, az, bx, bz))


class RoomMap:
    """One room's map (see the module docstring). floor: bytes of packed bits (numpy.packbits order: the first cell in
    the high bit), rows x cols, row 0 the smallest z; walls: [(x0, z0, x1, z1, y low, y high, flag)] - flag SOLID (it
    stops him and a shot), BLOCKER (an invisible wall: him, not a shot) or WALKED (he was seen walking through it: a
    door, a gate, a prop the collision still holds - neither)."""

    def __init__(self, room: str, origin, cell: float, cols: int, rows: int, floor: bytes, walls, *,
                 stage: str = "", source: dict | None = None):
        self.room, self.stage = room, stage or room
        self.ox, self.oz = float(origin[0]), float(origin[1])
        self.cell, self.cols, self.rows = float(cell), int(cols), int(rows)
        self.floor = bytes(floor)
        self.walls = [(float(w[0]), float(w[1]), float(w[2]), float(w[3]), float(w[4]), float(w[5]), int(w[6]))
                      for w in walls]
        self.source = dict(source or {})
        self._buckets: dict = {}
        for k, (x0, z0, x1, z1, *_r) in enumerate(self.walls):
            for gx in range(int(math.floor(min(x0, x1) / BUCKET_MM)), int(math.floor(max(x0, x1) / BUCKET_MM)) + 1):
                for gz in range(int(math.floor(min(z0, z1) / BUCKET_MM)), int(math.floor(max(z0, z1) / BUCKET_MM)) + 1):
                    self._buckets.setdefault((gx, gz), []).append(k)

    @classmethod
    def from_mask(cls, room: str, origin, cell: float, mask_rows, walls, **kw) -> "RoomMap":
        """From a list of strings / lists of truthy cells (row 0 the smallest z): the tests' synthetic rooms."""
        rows, cols = len(mask_rows), len(mask_rows[0]) if mask_rows else 0
        bits = bytearray((rows * cols + 7) // 8)
        for r, line in enumerate(mask_rows):
            for c, v in enumerate(line):
                if v not in (0, False, " ", "#"):
                    i = r * cols + c
                    bits[i >> 3] |= 0x80 >> (i & 7)
        return cls(room, origin, cell, cols, rows, bytes(bits), walls, **kw)

    # --- the floor ---
    def cell_of(self, x: float, z: float):
        c, r = int(math.floor((x - self.ox) / self.cell)), int(math.floor((z - self.oz) / self.cell))
        return (r, c) if 0 <= c < self.cols and 0 <= r < self.rows else None

    def floor_at(self, x: float, z: float) -> bool:
        """Floor under this cell on some storey (False outside the grid)."""
        rc = self.cell_of(x, z)
        if rc is None:
            return False
        i = rc[0] * self.cols + rc[1]
        return bool(self.floor[i >> 3] & (0x80 >> (i & 7)))

    # --- the walls ---
    def walls_near(self, a, b, pad: float = 0.0):
        x0, x1 = sorted((a[0], b[0]))
        z0, z1 = sorted((a[2], b[2]))
        gx0, gx1 = int(math.floor((x0 - pad) / BUCKET_MM)), int(math.floor((x1 + pad) / BUCKET_MM))
        gz0, gz1 = int(math.floor((z0 - pad) / BUCKET_MM)), int(math.floor((z1 + pad) / BUCKET_MM))
        if (gx1 - gx0 + 1) * (gz1 - gz0 + 1) > 4096:
            return range(len(self.walls))
        out = set()
        for gx in range(gx0, gx1 + 1):
            for gz in range(gz0, gz1 + 1):
                out.update(self._buckets.get((gx, gz), ()))
        return sorted(out)

    @staticmethod
    def _in_band(w, y: float) -> bool:
        """A wall that stops a walk with his feet at y: within his body's height, and not one he walked through."""
        return w[6] != WALKED and w[5] >= y + BODY_LO_MM and w[4] <= y + BODY_HI_MM

    def walked_through(self, k: int) -> bool:
        """Wall k is one he was seen walking through (WALKED from now on, for walks and shots); False when it already
        was."""
        w = self.walls[k]
        if w[6] == WALKED:
            return False
        self.walls[k] = w[:6] + (WALKED,)
        return True

    def wall_crossed(self, a, b):
        """The first wall within his body's height (a's feet) that the walk a -> b crosses, as (wall, t), or None."""
        best = None
        for k in self.walls_near(a, b):
            w = self.walls[k]
            if not self._in_band(w, a[1]):
                continue
            t = _cross(a[0], a[2], b[0], b[2], *w[:4])
            if t is not None and (best is None or t < best[1]):
                best = (w, t)
        return best

    def wall_near(self, p, r: float, y: float | None = None):
        """A wall within his body's height (feet at y, p's own by default) within r of p (x, z), or None."""
        y = p[1] if y is None else y
        for k in self.walls_near(p, p, pad=r):
            w = self.walls[k]
            if self._in_band(w, y) and _dist_seg(p[0], p[2], *w[:4]) < r:
                return w
        return None

    def walk_block(self, a, b, *, end_r: float = BODY_R_MM, body_r: float = BRUSH_R_MM) -> str | None:
        """Why the walk from a to b (his feet at a) is refused, or None (see the module docstring); body_r: his body's
        half width - a wall the walk brings him nearer than this (and nearer than he is now: walking along a wall
        he already stands beside is no closer) is refused too, a corner as much as a face."""
        if not (_ok(a) and _ok(b)):
            return "not a position"
        L = math.hypot(b[0] - a[0], b[2] - a[2])
        n = max(1, int(math.ceil(L / SAMPLE_MM)))
        start = self.cell_of(a[0], a[2])
        for i in range(1, n + 1):
            x, z = a[0] + (b[0] - a[0]) * i / n, a[2] + (b[2] - a[2]) * i / n
            if self.cell_of(x, z) != start and not self.floor_at(x, z):
                return f"off the floor at {x:.0f},{z:.0f}"
        hit = self.wall_crossed(a, b)
        if hit is not None:
            w, t = hit
            return f"a wall {w[0]:.0f},{w[1]:.0f}-{w[2]:.0f},{w[3]:.0f} (y {w[4]:.0f}..{w[5]:.0f}) {t * L:.0f} mm on"
        m = max(body_r, end_r)
        if m <= 0.0:
            return None
        # the walls near the way, each with the side of it they stand on: a gap (a doorway) narrower than the margins
        # allow gets margins of GAP_MARGIN_X of its width - through its middle he passes, off it he does not
        rows = []
        for k in self.walls_near(a, b, pad=2.0 * m):
            w = self.walls[k]
            if not self._in_band(w, a[1]):
                continue
            d, side, s = _closest_side(a[0], a[2], b[0], b[2], *w[:4])
            if d < 2.0 * m:
                rows.append((d, side, w, s))
        br = min(body_r, GAP_MARGIN_X * _gap(rows, 2.0 * m))
        if body_r > 0.0:
            for d, _side, w, _s in rows:
                if d < br and d < _dist_seg(a[0], a[2], *w[:4]) - 1.0:
                    return (f"brushes a wall {w[0]:.0f},{w[1]:.0f}-{w[2]:.0f},{w[3]:.0f} ({d:.0f} mm, margin "
                            f"{br:.0f})")
        if end_r > 0.0:
            ends = [(_dist_seg(b[0], b[2], *w[:4]), _point_side(a, b, w), w, L) for _d, _s, w, _t in rows]
            er = min(end_r, GAP_MARGIN_X * _gap(ends))
            for d, _side, w, _s in ends:
                if d < er:
                    return f"ends {d:.0f} mm from a wall {w[0]:.0f},{w[1]:.0f}-{w[2]:.0f},{w[3]:.0f} (margin {er:.0f})"
        return None

    def walk_clear(self, a, b, **kw) -> bool:
        return self.walk_block(a, b, **kw) is None

    def blocked_cell(self, x: float, z: float, y: float) -> bool:
        """The computed '#' for him standing at height y: no floor, or a wall within his body's height crosses it."""
        if not self.floor_at(x, z):
            return True
        c0, r0 = self.ox + math.floor((x - self.ox) / self.cell) * self.cell, \
            self.oz + math.floor((z - self.oz) / self.cell) * self.cell
        corners = ((c0, r0), (c0 + self.cell, r0), (c0 + self.cell, r0 + self.cell), (c0, r0 + self.cell))
        for k in self.walls_near((c0, 0, r0), (c0 + self.cell, 0, r0 + self.cell)):
            w = self.walls[k]
            if not self._in_band(w, y):
                continue
            if all(c0 <= q[0] <= c0 + self.cell and r0 <= q[1] <= r0 + self.cell for q in ((w[0], w[1]), (w[2], w[3]))):
                return True                                  # wholly inside the cell
            for i in range(4):
                p, q = corners[i], corners[(i + 1) % 4]
                if _cross(p[0], p[1], q[0], q[1], *w[:4]) is not None:
                    return True
        return False

    # --- the shot ---
    def sight_block(self, a, b, *, eye: float = EYE_MM, chest: float = CHEST_MM):
        """The first wall (not a blocker) a shot from a's gun to b's chest meets at its own height, as (wall, t, y), or
        None (an end that is not a position: ("bad end", 0, 0))."""
        if not (_ok(a) and _ok(b)):
            return ("bad end", 0.0, 0.0)
        ya, yb = a[1] + eye, b[1] + chest
        best = None
        for k in self.walls_near(a, b):
            w = self.walls[k]
            if w[6]:
                continue
            t = _cross(a[0], a[2], b[0], b[2], *w[:4])
            if t is None:
                continue
            y = ya + t * (yb - ya)
            if w[4] <= y <= w[5] and (best is None or t < best[1]):
                best = (w, t, y)
        return best

    def sight_clear(self, a, b, **kw) -> bool:
        return self.sight_block(a, b, **kw) is None

    def describe(self) -> dict:
        return {"room": self.room, "stage": self.stage, "cells": [self.cols, self.rows], "walls": len(self.walls),
                "blockers": sum(1 for w in self.walls if w[6] == BLOCKER),
                "walked": sum(1 for w in self.walls if w[6] == WALKED)}


def from_json(data: dict, formats=None) -> RoomMap:
    """A table (one stage) as a RoomMap; formats: the format names this caller reads (any when None)."""
    if formats is not None and data.get("format") not in formats:
        raise ValueError(f"not a room map this title reads (format {data.get('format')!r})")
    g = data["grid"]
    floor = zlib.decompress(base64.b64decode(g["floor"]))
    if len(floor) * 8 < g["cols"] * g["rows"]:
        raise ValueError("the floor mask is shorter than its grid")
    return RoomMap(data["room"], g["origin_mm"], g["cell_mm"], g["cols"], g["rows"], floor, data.get("walls", ()),
                   stage=data.get("stage", ""), source=data.get("source"))
