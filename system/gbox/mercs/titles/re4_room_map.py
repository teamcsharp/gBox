"""RE4 (Switch) Mercenaries: the room's real map for every walk and shot the bot makes (#9342, checked; mm, y up).

    rm = for_snap(snap)                  # the stage's map (snap["nav"]'s room, else the round's stage, else the last)
    rm.walk_block(a, b)                  # why a walk from a to b (positions, his feet) is refused, or None
    rm.walk_clear(a, b)                  # ... is allowed
    rm.sight_block(a, b)                 # the wall a shot from a to b (feet; his gun EYE_MM up, the target's chest
                                         #   CHEST_MM up) meets, or None
    rm.blocked_cell(x, z, y)             # the computed '#': no floor, or a wall within his body's height crosses it

The table (gbox/data/re4_switch_room_map/r4xx.json, built by gbox.re4_switch_room_map from the RomFS and #9342's
JSON; the builder's docstring says what was checked and what was dropped): a 250 mm floor mask by #9342's rule (every
storey merged - "floor somewhere under this cell") and #9342's wall segments, each with the height span of the SAT
triangles behind it and a blocker flag (an invisible wall: it stops him, not a shot).

* a walk is refused when a sample along it (every SAMPLE_MM, the start's own cell aside) falls on a cell without floor
  (off the map: water, a void), when it crosses a wall whose height span meets his body (his feet + BODY_LO_MM ..
  BODY_HI_MM: a wall on the floor below or a beam above his head does not count; an invisible blocker does), when it
  brings him nearer than body_r (BRUSH_R_MM: his half width) to such a wall than he already is (a corner, a shallow
  angle), or when it ends within end_r of one (he would stand pressed to it, the camera inside it);
* a shot is refused when it crosses a wall that is not a blocker at the shot's own height there.

Rooms and MercMode's stages (Select Stage's order, gbox.mercs.titles.re4_switch.STAGES; re4_stage_greybox.STAGES and
re4_nav.ROOMS name the same rooms): Village r400, Castle r402, Base r403, Waterworld r404 (STAGE_ROOM). The frame was
checked live: the bot's RAM positions lie on each room's SAT floor with RAM y = the floor's height (median 0 mm).
"""
from __future__ import annotations

import base64
import json
import math
import zlib
from pathlib import Path

from . import re4_nav

FORMAT = "gbox.re4_switch_room_map/1"
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "re4_switch_room_map"
ROOMS = dict(re4_nav.ROOMS)                                  # r400 Village, r402 Castle, r403 Base, r404 Waterworld
STAGE_ROOM = {name: room for room, name in ROOMS.items()}    # MercMode / Select Stage name -> the room
STAGE_INDEX = dict(re4_nav.STAGE_INDEX)                      # Select Stage index (re4_switch.STAGES order) -> the room
BODY_LO_MM, BODY_HI_MM = 300.0, 1700.0   # his body above his feet: a wall spanning any of it stops a walk
BODY_R_MM = 350.0                        # a walk ending this near such a wall: refused (pressed to it)
BRUSH_R_MM = 300.0                       # a walk bringing him this near one (a corner, a shallow angle): refused
SAMPLE_MM = 125.0                        # the floor along a walk, half a cell at a time
BUCKET_MM = 4000.0                       # the walls' lookup buckets
EYE_MM, CHEST_MM = re4_nav.EYE_MM, re4_nav.CHEST_MM


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


def _dist_segs(ax, az, bx, bz, x0, z0, x1, z1) -> float:
    """The least distance between the segments a-b and (x0, z0)-(x1, z1) (0 when they cross)."""
    if _cross(ax, az, bx, bz, x0, z0, x1, z1) is not None:
        return 0.0
    return min(_dist_seg(ax, az, x0, z0, x1, z1), _dist_seg(bx, bz, x0, z0, x1, z1),
               _dist_seg(x0, z0, ax, az, bx, bz), _dist_seg(x1, z1, ax, az, bx, bz))


class RoomMap:
    """One room's map (see the module docstring). floor: bytes of packed bits (numpy.packbits order: the first cell in
    the high bit), rows x cols, row 0 the smallest z; walls: [(x0, z0, x1, z1, y low, y high, blocker)]."""

    def __init__(self, room: str, origin, cell: float, cols: int, rows: int, floor: bytes, walls, *,
                 stage: str = "", source: dict | None = None):
        self.room, self.stage = room, stage or ROOMS.get(room, room)
        self.ox, self.oz = float(origin[0]), float(origin[1])
        self.cell, self.cols, self.rows = float(cell), int(cols), int(rows)
        self.floor = bytes(floor)
        self.walls = [(float(w[0]), float(w[1]), float(w[2]), float(w[3]), float(w[4]), float(w[5]), bool(w[6]))
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
        return w[5] >= y + BODY_LO_MM and w[4] <= y + BODY_HI_MM

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
        if body_r > 0.0:
            for k in self.walls_near(a, b, pad=body_r):
                w = self.walls[k]
                if not self._in_band(w, a[1]):
                    continue
                d = _dist_segs(a[0], a[2], b[0], b[2], *w[:4])
                if d < body_r and d < _dist_seg(a[0], a[2], *w[:4]) - 1.0:
                    return f"brushes a wall {w[0]:.0f},{w[1]:.0f}-{w[2]:.0f},{w[3]:.0f} ({d:.0f} mm)"
        if end_r > 0.0:
            w = self.wall_near((b[0], a[1], b[2]), end_r)
            if w is not None:
                return f"ends {end_r:.0f} mm from a wall {w[0]:.0f},{w[1]:.0f}-{w[2]:.0f},{w[3]:.0f}"
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
                "blockers": sum(1 for w in self.walls if w[6])}


def from_json(data: dict) -> RoomMap:
    if data.get("format") != FORMAT:
        raise ValueError(f"not an RE4 Switch room map (format {data.get('format')!r})")
    g = data["grid"]
    floor = zlib.decompress(base64.b64decode(g["floor"]))
    if len(floor) * 8 < g["cols"] * g["rows"]:
        raise ValueError("the floor mask is shorter than its grid")
    return RoomMap(data["room"], g["origin_mm"], g["cell_mm"], g["cols"], g["rows"], floor, data.get("walls", ()),
                   stage=data.get("stage", ""), source=data.get("source"))


_CACHE: dict = {}


def path_of(room: str, data_dir: Path | None = None) -> Path:
    return Path(data_dir or DATA_DIR) / f"{room}.json"


def load(room: str | None, data_dir: Path | None = None) -> RoomMap | None:
    """The room's map (r400 ...), read once and kept; None when there is none or it cannot be read."""
    if not room:
        return None
    key = (str(data_dir or DATA_DIR), room)
    if key not in _CACHE:
        try:
            _CACHE[key] = from_json(json.loads(path_of(room, data_dir).read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError, TypeError, zlib.error):
            _CACHE[key] = None
    return _CACHE[key]


def room_for_stage(value) -> str | None:
    """A MercMode / Select Stage name ("Base"), its index (2), or a room id ("r403", 0x0403) -> the room."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return re4_nav.room_of(value)
    text = str(value).strip()
    return STAGE_ROOM.get(text) or STAGE_ROOM.get(text.title()) or re4_nav.room_of(text)


def room_of_snap(snap: dict) -> str | None:
    """The room a snapshot is in: its stage mesh's (snap["nav"], picked by the player's floor - re4_nav.Picker), else,
    on a snapshot read from the game (module_base), a room / stage it names, the round's own stage index
    (snap["game"]["stage"]) or the last room picked. A mesh that is not the stage's own table (a test's synthetic room
    named r400) gives none: the room map is laid over the room's real coordinates only."""
    snap = snap if isinstance(snap, dict) else {}
    nav = snap.get("nav")
    if nav is not None:
        room = getattr(nav, "room", None)
        return room if room in ROOMS and re4_nav.load(room) is nav else None
    if snap.get("module_base") is None:
        return None
    for key in ("room", "stage_room", "stage_name", "stage"):
        room = room_for_stage(snap.get(key))
        if room in ROOMS:
            return room
    game = snap.get("game")
    if isinstance(game, dict):
        room = STAGE_INDEX.get(game.get("stage")) if isinstance(game.get("stage"), int) else None
        if room in ROOMS:
            return room
    room = getattr(re4_nav.PICKER, "room", None)
    return room if room in ROOMS else None


def for_snap(snap: dict, data_dir: Path | None = None) -> RoomMap | None:
    """This snapshot's room map (snap["room_map"] when one is given, as the tests do), or None; never raises."""
    try:
        given = snap.get("room_map") if isinstance(snap, dict) else None
        if isinstance(given, RoomMap):
            return given
        return load(room_of_snap(snap), data_dir)
    except Exception:                                        # noqa: BLE001 - the map never costs the tick
        return None
