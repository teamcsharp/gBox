"""RE4 (Switch, title 010099A00BC1E000) room collision -> the stage floor mesh the Mercenaries bot routes on and the
tactical map draws, one small JSON per stage (`gbox/data/re4_switch_nav/r4xx.json`, read by
`gbox.mercs.titles.re4_nav`).

RE4 keeps no navigation mesh in RAM the way RE5 does; each room carries its own collision. Measured 2026-11-10 on the
launched 1.0.2 RomFS (`bio4/st4/r400 r402 r403 r404.udas`, read-only copies):

* The room DAT keeps the GameCube slot order (`CAM SAT LIT LIT SMD ... EAT AEV ...`). Slot 1 `SAT` is the player's
  collision, slot 14 `EAT` the enemies'. The SAT is the GameCube SAT (`gbox.re4_navmap.sat_read`) with every field
  little-endian: `u8 0x80, u8 0x01, u16 0xFF79, u32 body (8)`; body `u16, u16 #verts, u16 #normals, u16 #edges, u16,
  u16 #tris, 4 x u16`; f32 vertices, f32 unit normals, f32 edge vectors, 20-byte triangles (`u16 v0 v1 v2 normal e0 e1
  e2 pad, u16 attr-hi, u16 attr-lo`), then the bounding-volume tree (not read). Byte-swapped to the GameCube layout,
  the four rooms give the GameCube's vertex / triangle counts (r402: 1,395 / 1,277 against 1,393 / 1,275) and, for
  r400, r403 and r404, the GameCube navmap's 1,031 / 1,055 / 765 wall segments to the 0.1 mm and its whole grid
  (`profiles/gamedata/re4_r4xx_navmap.json`: layers, heights, states, reach) bit for bit.
* `AEV` entries are 0xF0 bytes (GameCube 0x9C): zone `+0x0C y, +0x10 height, +0x18 four (x, z)`, `+0x39 type, +0x3A
  index, +0x3C trigger`, type data from `+0x70` (a ladder: `x y z facing`, `+0x80 s8 rungs`). `ITA` entries are 0xB8:
  the same zone, `+0x70 x y z`, `+0x94 u16 item, flag, amount`. Converted to the GameCube layout they give the
  GameCube's events (hourglasses, ladders, zones) except one area zone in r403 (AEV[34], moved).
* `etc/omake01.esl` / `omake02.esl` are the GameCube set lists little-endian (one r400 spawn moved).

So the floor is built by the GameCube navmap's own rules (`re4_navmap.build_stage`: SAT floors ny >= 0.7 sampled on a
200 mm grid in storeys, walls / ceilings / no headroom block, `VAULT_BITS` fences and windows are jump-overs, ladders
from AEV type 0x10, the playable area = there and back from a central spawn) and turned here into the triangle mesh
`gbox.mercs.titles.re5_nav.NavMesh` takes:

* walkable cells (free or near a wall, in the playable area) are merged into rectangles of one plane (at most
  MAX_SIDE cells a side, heights within PLANE_TOL of a plane); a rectangle's polygon keeps its corners and every point
  where what lies across its side changes, so neighbours share whole edges (no T-junctions: re5_nav links need shared
  vertex indices); 4-point polygons split in two, larger ones are fanned from the centre;
* vertex heights are the SAT floor under the point nearest the cells' own height (on a 350 mm step the shared vertex
  takes one side's height);
* links join triangles over shared edges (rebuilt from the triangles at load); the crossings are explicit links
  between triangles that share no edge: a fence or window jump-over (`vault`, both ways where the grid allows, a drop
  through a window one way) and a ladder (`ladder`, up and down - the GameCube navmap's reading, the way down not
  seen in game). Each carries its own approach, portal and landing, which `re4_nav` hands the walker as
  `re5_nav.Traversal`s;
* the SAT's steep triangles (|ny| < 0.7) are kept as wall segments for line-of-sight tests (`re4_nav.Mesh.clear_segment`).

    python -m gbox.re4_switch_nav build --st4 <bio4/st4> --etc <bio4/etc> [--out gbox/data/re4_switch_nav] [--png DIR]
    python -m gbox.re4_switch_nav verify --st4 <bio4/st4> [--png DIR]      # the mesh against the drawn floor (SMD)
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import struct
import sys
import time
import zlib
from pathlib import Path

import numpy as np

from . import re4_navmap as N
from .re4_switch_assets import pack_slots

FORMAT = "gbox.re4_switch_nav/1"
TITLE_ID = "010099A00BC1E000"
GAME_ID = "270a15eb98dab4d7"
ROOMS = {"r400": "Village", "r402": "Castle", "r403": "Base", "r404": "Waterworld"}
ESL_OF = {"r400": "omake01.esl", "r402": "omake01.esl", "r403": "omake02.esl", "r404": "omake02.esl"}
DATA_DIR = Path(__file__).resolve().parent / "data" / "re4_switch_nav"

AEV_BYTES, ITA_BYTES = 0xF0, 0xB8          # entry sizes on the Switch (GameCube 0x9C both)
GC_EVENT_BYTES = 0x9C
MAX_SIDE = 16                              # cells (200 mm): the largest rectangle side, 3.2 m
PLANE_TOL = 30.0                           # mm: a rectangle's cell heights within this of one plane
VAULT_SPAN = 4                             # cells: the widest fence / sill strip a jump-over crosses
VAULT_COST, LADDER_COST = 2000.0, 3000.0   # mm added to a crossing's length (the animation's time, roughly)
LADDER_REACH = 300.0                       # mm from the ladder's stand point toward the ladder: the portal
WALL_NY = 0.7                              # |ny| below this: a wall (the GameCube navmap's floor rule's complement)


class NavBuildError(ValueError):
    """The room bytes are not the layout measured here."""


# --- the Switch files in the GameCube layout ------------------------------------------------------------------------

def sat_to_gc(s: bytes) -> bytes:
    """A Switch SAT / EAT (little-endian) as the GameCube's big-endian bytes, up to the triangles (the tree is left)."""
    if len(s) < 0x1C or s[:2] != b"\x80\x01" or struct.unpack_from("<H", s, 2)[0] != 0xFF79:
        raise NavBuildError("not a Switch SAT/EAT (80 01 79 ff)")
    body = struct.unpack_from("<I", s, 4)[0]
    if body + 0x14 > len(s):
        raise NavBuildError("SAT body offset past the end")
    b = bytearray(s)
    struct.pack_into(">HI", b, 2, 0xFF79, body)
    head = struct.unpack_from("<10H", s, body)
    struct.pack_into(">10H", b, body, *head)
    nv, nn, ne, nt = head[1], head[2], head[3], head[5]
    at = body + 0x14
    floats = 3 * (nv + nn + ne)
    if at + 4 * floats + 20 * nt > len(s):
        raise NavBuildError("SAT tables run past the end")
    struct.pack_into(f">{floats}f", b, at, *struct.unpack_from(f"<{floats}f", s, at))
    at += 4 * floats
    struct.pack_into(f">{10 * nt}H", b, at, *struct.unpack_from(f"<{10 * nt}H", s, at))
    return bytes(b)


def events_to_gc(s: bytes, magic: bytes) -> bytes:
    """A Switch AEV / ITA table as the GameCube's 0x9C-byte big-endian entries (the fields gbox.re4_navmap reads)."""
    if s[:4] != magic or len(s) < 0x10:
        raise NavBuildError(f"not an {magic[:3].decode()} table")
    size = AEV_BYTES if magic == b"AEV\0" else ITA_BYTES
    version, count = struct.unpack_from("<HH", s, 4)
    if 0x10 + size * count > len(s):
        raise NavBuildError(f"{magic[:3].decode()}: {count} entries of {size:#x} bytes do not fit {len(s)}")
    out = bytearray(magic + struct.pack(">HH", version, count) + bytes(8))
    for i in range(count):
        e = s[0x10 + size * i:0x10 + size * (i + 1)]
        g = bytearray(GC_EVENT_BYTES)
        struct.pack_into(">2f", g, 0x08, *struct.unpack_from("<2f", e, 0x0C))       # zone floor y, height
        struct.pack_into(">8f", g, 0x14, *struct.unpack_from("<8f", e, 0x18))       # four (x, z) corners
        g[0x34:0x3C] = e[0x38:0x40]                                                  # 0x35 type, 0x36 index, 0x38 trigger
        g[0x5C:0x9C] = e[0x70:0xB0]                                                  # type data
        struct.pack_into(">4f", g, 0x5C, *struct.unpack_from("<4f", e, 0x70))       # x y z facing (a ladder) / x y z
        if magic == b"ITA\0":
            struct.pack_into(">3H", g, 0x78, *struct.unpack_from("<3H", e, 0x94))   # item, flag, amount
        out += g
    return bytes(out)


def esl_to_gc(s: bytes) -> bytes:
    """A Switch enemy set list (32-byte little-endian entries) as the GameCube's big-endian bytes."""
    b = bytearray(s)
    for i in range(len(s) // 32):
        at = 32 * i
        for off, fmt in ((0x08, "H"), (0x0C, "3h"), (0x12, "3h"), (0x18, "2H")):
            struct.pack_into(">" + fmt, b, at + off, *struct.unpack_from("<" + fmt, s, at + off))
    return bytes(b)


def room_files(udas: bytes) -> tuple[list[tuple[str, bytes]], dict]:
    """A Switch room pack -> its DAT slots [(ext, bytes)] with SAT / EAT / AEV / ITA in the GameCube layout (the rest
    as they are), and {ext: (slot, sha256)} of the converted slots' Switch bytes."""
    _pack, dat = pack_slots(udas)
    files, slots = [], {}
    for index, (ext, payload) in enumerate(dat.slots):
        if ext in ("SAT", "EAT", "AEV", "ITA") and ext not in slots:
            slots[ext] = (index, hashlib.sha256(payload).hexdigest())
        if ext in ("SAT", "EAT"):
            payload = sat_to_gc(payload)
        elif ext in ("AEV", "ITA"):
            payload = events_to_gc(payload, ext.encode() + b"\0")
        elif ext == "RTP":
            continue                                   # the enemies' route graph: another layout, not needed here
        files.append((ext, payload))
    if "SAT" not in slots:
        raise NavBuildError("the room pack has no SAT slot")
    return files, slots


# --- the grid -> the mesh -------------------------------------------------------------------------------------------

class _Union:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, a: int) -> int:
        p = self.p
        while p[a] != a:
            p[a] = p[p[a]]
            a = p[a]
        return a

    def union(self, a: int, b: int) -> None:
        a, b = self.find(a), self.find(b)
        if a != b:
            self.p[max(a, b)] = min(a, b)


def _floor_heights(col: dict, xz: np.ndarray, ref: np.ndarray, tol: float) -> np.ndarray:
    """The SAT floor's height under each (x, z) nearest its reference height (within tol), else the reference."""
    V, T, ny = col["verts"], col["tris"], col["normals"][:, 1]
    best = ref.astype(np.float64).copy()
    gap = np.full(len(xz), np.inf)
    for t in np.nonzero(ny >= 0.7)[0]:
        (x1, y1, z1), (x2, y2, z2), (x3, y3, z3) = V[T[t]]
        det = (z2 - z3) * (x1 - x3) + (x3 - x2) * (z1 - z3)
        if abs(det) < 1e-6:
            continue
        lo_x, hi_x = min(x1, x2, x3) - 1.0, max(x1, x2, x3) + 1.0
        lo_z, hi_z = min(z1, z2, z3) - 1.0, max(z1, z2, z3) + 1.0
        sel = np.nonzero((xz[:, 0] >= lo_x) & (xz[:, 0] <= hi_x) & (xz[:, 1] >= lo_z) & (xz[:, 1] <= hi_z))[0]
        if not len(sel):
            continue
        X, Z = xz[sel, 0], xz[sel, 1]
        l1 = ((z2 - z3) * (X - x3) + (x3 - x2) * (Z - z3)) / det
        l2 = ((z3 - z1) * (X - x3) + (x1 - x3) * (Z - z3)) / det
        l3 = 1.0 - l1 - l2
        inside = (l1 >= -1e-4) & (l2 >= -1e-4) & (l3 >= -1e-4)
        h = l1 * y1 + l2 * y2 + l3 * y3
        d = np.abs(h - ref[sel])
        take = inside & (d <= tol) & (d < gap[sel])
        idx = sel[take]
        best[idx], gap[idx] = h[take], d[take]
    return best


def build_mesh(g: N.NavGrid, col: dict, events: list[dict], *, max_side: int = MAX_SIDE,
               plane_tol: float = PLANE_TOL) -> dict:
    """The playable floor of a stage grid as {points (n, 3) mm, tris (m, 3), crossings [...], stats}."""
    nx, nz, cell = g.nx, g.nz, g.cell
    L = len(g.lc)
    ix, iz, lh = (g.lc % nx).astype(int), (g.lc // nx).astype(int), g.lh
    walk = (g.lr == 2) & ((g.ls == N.FREE) | (g.ls == N.NEAR))
    first, count = g.first, g.count

    def layer_at(jx: int, jz: int, h: float, ok, tol: float = N.STEP) -> int:
        if not (0 <= jx < nx and 0 <= jz < nz):
            return -1
        c = jz * nx + jx
        best, gap = -1, tol + 1e-6
        for k in range(int(first[c]), int(first[c] + count[c])):
            if ok[k] and abs(lh[k] - h) < gap:
                best, gap = k, abs(lh[k] - h)
        return best

    DIRS4 = ((1, 0), (-1, 0), (0, 1), (0, -1))
    nb = {d: np.full(L, -1, np.int64) for d in DIRS4}
    for k in np.nonzero(walk)[0]:
        for d in DIRS4:
            nb[d][k] = layer_at(ix[k] + d[0], iz[k] + d[1], lh[k], walk)
    px, mx, pz, mz = nb[(1, 0)], nb[(-1, 0)], nb[(0, 1)], nb[(0, -1)]

    # rectangles of one plane
    rect_of = np.full(L, -1, np.int64)
    rects: list[list[list[int]]] = []

    def planar(rows) -> bool:
        h00 = lh[rows[0][0]]
        a = lh[rows[0][1]] - h00 if len(rows[0]) > 1 else 0.0
        b = lh[rows[1][0]] - h00 if len(rows) > 1 else 0.0
        return all(abs(lh[k] - (h00 + a * i + b * j)) <= plane_tol
                   for j, row in enumerate(rows) for i, k in enumerate(row))

    for k in sorted(np.nonzero(walk)[0].tolist(), key=lambda k: (iz[k], ix[k], lh[k])):
        if rect_of[k] >= 0:
            continue
        row = [k]
        while len(row) < max_side:
            k2 = int(px[row[-1]])
            if k2 < 0 or rect_of[k2] >= 0 or not planar([row + [k2]]):
                break
            row.append(k2)
        rows = [row]
        while len(rows) < max_side:
            new = []
            for i, above in enumerate(rows[-1]):
                k2 = int(pz[above])
                if k2 < 0 or rect_of[k2] >= 0 or k2 in new or (i and int(px[new[-1]]) != k2):
                    new = None
                    break
                new.append(k2)
            if new is None or not planar(rows + [new]):
                break
            rows.append(new)
        rid = len(rects)
        for r in rows:
            for k2 in r:
                rect_of[k2] = rid
        rects.append(rows)

    # corner slots (4 per layer: 0 (ix, iz), 1 (ix+1, iz), 2 (ix+1, iz+1), 3 (ix, iz+1)) unified across linked cells
    uf = _Union(4 * L)
    for k in np.nonzero(walk)[0]:
        if px[k] >= 0:
            uf.union(4 * k + 1, 4 * int(px[k]) + 0)
            uf.union(4 * k + 2, 4 * int(px[k]) + 3)
        if pz[k] >= 0:
            uf.union(4 * k + 3, 4 * int(pz[k]) + 0)
            uf.union(4 * k + 2, 4 * int(pz[k]) + 1)

    def partner(k, side) -> int:
        n = int(side[k])
        return int(rect_of[n]) if n >= 0 else -1

    # each rectangle's boundary: [(slot, corner?, partner of the side cell after this point)]
    loops, needed = [], set()
    for rows in rects:
        h, w = len(rows), len(rows[0])
        pts = []                                           # (slot, is_corner)
        parts = []                                         # partner of the side cell following the point
        for i in range(w):                                 # bottom, +x
            pts.append((4 * rows[0][i] + 0, i == 0))
            parts.append(partner(rows[0][i], mz))
        for j in range(h):                                 # right, +z
            pts.append((4 * rows[j][w - 1] + 1, j == 0))
            parts.append(partner(rows[j][w - 1], px))
        for i in range(w - 1, -1, -1):                     # top, -x
            pts.append((4 * rows[h - 1][i] + 2, i == w - 1))
            parts.append(partner(rows[h - 1][i], pz))
        for j in range(h - 1, -1, -1):                     # left, -z
            pts.append((4 * rows[j][0] + 3, j == h - 1))
            parts.append(partner(rows[j][0], mx))
        n = len(pts)
        for q, (slot, corner) in enumerate(pts):
            if corner or parts[q] != parts[q - 1]:
                needed.add(uf.find(slot))
        loops.append(pts)

    # vertices: the needed classes, at their corner, the SAT floor height
    def corner_xz(slot):
        k, c = divmod(slot, 4)
        cx = ix[k] + (1 if c in (1, 2) else 0)
        cz = iz[k] + (1 if c in (2, 3) else 0)
        return g.x0 + cx * cell, g.z0 + cz * cell

    ref_sum, ref_n, cls_xz = {}, {}, {}
    for pts in loops:
        for slot, _corner in pts:
            r = uf.find(slot)
            if r in needed:
                ref_sum[r] = ref_sum.get(r, 0.0) + lh[slot // 4]
                ref_n[r] = ref_n.get(r, 0) + 1
                cls_xz.setdefault(r, corner_xz(slot))
    classes = sorted(needed)
    index = {r: i for i, r in enumerate(classes)}
    xz = np.array([cls_xz[r] for r in classes], np.float64).reshape(-1, 2)
    ref = np.array([ref_sum[r] / ref_n[r] for r in classes], np.float64)
    points = [(float(x), 0.0, float(z)) for x, z in xz]

    tris, tri_rect = [], []
    centres_xz, centres_ref, centre_of = [], [], {}
    for rid, pts in enumerate(loops):
        poly = []
        for slot, _corner in pts:
            r = uf.find(slot)
            if r in needed and (not poly or poly[-1] != index[r]):
                poly.append(index[r])
        if len(poly) > 1 and poly[0] == poly[-1]:
            poly.pop()
        if len(poly) < 3:
            continue
        if len(poly) == 4:
            tris += [(poly[0], poly[1], poly[2]), (poly[0], poly[2], poly[3])]
            tri_rect += [rid, rid]
            continue
        rows = rects[rid]
        x0r, z0r = g.x0 + ix[rows[0][0]] * cell, g.z0 + iz[rows[0][0]] * cell
        centre_of[rid] = len(points) + len(centres_xz)
        centres_xz.append((x0r + len(rows[0]) * cell / 2, z0r + len(rows) * cell / 2))
        centres_ref.append(float(np.mean([lh[k] for r in rows for k in r])))
        c = centre_of[rid]
        for q in range(len(poly)):
            tris.append((c, poly[q], poly[(q + 1) % len(poly)]))
            tri_rect.append(rid)
    all_xz = np.concatenate([xz, np.array(centres_xz, np.float64).reshape(-1, 2)])
    all_ref = np.concatenate([ref, np.array(centres_ref, np.float64)])
    heights = _floor_heights(col, all_xz, all_ref, N.STEP)
    points = [(float(x), float(y), float(z)) for (x, z), y in zip(all_xz, heights)]

    by_rect: dict[int, list[int]] = {}
    for t, rid in enumerate(tri_rect):
        by_rect.setdefault(rid, []).append(t)
    crossings = _crossings(g, events, walk, rect_of, points, tris, by_rect, layer_at)
    return {"points": points, "tris": tris, "crossings": crossings,
            "stats": {"walkable_cells": int(walk.sum()), "rectangles": len(rects), "fanned": len(centre_of)}}


def _tri_at(points, tris, by_rect, rid: int, x: float, z: float) -> int | None:
    """The triangle of rectangle rid that holds (x, z) (the nearest by centroid when none does)."""
    best, gap = None, math.inf
    for t in by_rect.get(int(rid), ()):
        (ax, _, az), (bx, _, bz), (cx, _, cz) = (points[v] for v in tris[t])
        d1 = (x - bx) * (az - bz) - (ax - bx) * (z - bz)
        d2 = (x - cx) * (bz - cz) - (bx - cx) * (z - cz)
        d3 = (x - ax) * (cz - az) - (cx - ax) * (z - az)
        if not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0)):
            return t
        d = math.hypot(x - (ax + bx + cx) / 3, z - (az + bz + cz) / 3)
        if d < gap:
            best, gap = t, d
    return best


def _near_edge(points, tri, p) -> int:
    def mid(e):
        a, b = points[tri[e]], points[tri[(e + 1) % 3]]
        return ((a[0] + b[0]) / 2, (a[2] + b[2]) / 2)
    return min(range(3), key=lambda e: math.hypot(mid(e)[0] - p[0], mid(e)[1] - p[2]))


def _crossings(g, events, walk, rect_of, points, tris, by_rect, layer_at) -> list[dict]:
    """The jump-overs (grid VAULT strips) and ladders (AEV type 0x10) as explicit links between triangles."""
    nx, cell = g.nx, g.cell
    ix, iz, lh = (g.lc % nx).astype(int), (g.lc // nx).astype(int), g.lh
    vault = (g.ls == N.VAULT) & (g.lr > 0)

    def centre(k):
        return g.x0 + (ix[k] + 0.5) * cell, g.z0 + (iz[k] + 0.5) * cell

    found: dict = {}
    for a in np.nonzero(walk)[0]:
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            v = layer_at(ix[a] + dx, iz[a] + dz, lh[a], vault)
            if v < 0:
                continue
            strip, b = [v], -1
            for step in range(2, VAULT_SPAN + 2):
                jx, jz = ix[a] + dx * step, iz[a] + dz * step
                w = layer_at(jx, jz, lh[strip[-1]], walk, tol=N.DROP_MAX)
                if w >= 0 and -N.DROP_MAX <= lh[w] - lh[a] <= N.STEP:   # level, or down through a window
                    b = w
                    break
                nxt = layer_at(jx, jz, lh[strip[-1]], vault)
                if nxt < 0:
                    break
                strip.append(nxt)
            if b < 0 or rect_of[a] == rect_of[b]:
                continue
            ax, az = centre(a)
            bx, bz = centre(b)
            key = (int(rect_of[a]), int(rect_of[b]))
            row = {"kind": "vault", "a": int(a), "b": int(b), "dir": (dx, dz), "width": len(strip),
                   "approach": (ax, float(lh[a]), az), "landing": (bx, float(lh[b]), bz),
                   "portal": ((ax + bx) / 2, float(max(lh[s] for s in strip)), (az + bz) / 2),
                   "drop": round(float(lh[a] - lh[b]), 1)}
            found.setdefault(key, []).append(row)
    out = []
    for (ra, rb), rows in sorted(found.items()):
        mx = sum(r["portal"][0] for r in rows) / len(rows)
        mz = sum(r["portal"][2] for r in rows) / len(rows)
        row = min(rows, key=lambda r: math.hypot(r["portal"][0] - mx, r["portal"][2] - mz))
        u = _tri_at(points, tris, by_rect, ra, row["approach"][0], row["approach"][2])
        v = _tri_at(points, tris, by_rect, rb, row["landing"][0], row["landing"][2])
        if u is None or v is None:
            continue
        out.append({"kind": "vault", "u": u, "v": v, "approach": row["approach"], "portal": row["portal"],
                    "landing": row["landing"], "drop_mm": row["drop"], "strip_cells": row["width"],
                    "cost": VAULT_COST, "verified": False})
    for e in events:
        if e.get("kind") != "ladder":
            continue
        bottom, top = e["pos"], e["top"]
        a = g.node_at(bottom[0], bottom[2], bottom[1], radius=3)
        b = g.node_at(top[0], top[2], top[1], radius=6)
        if a is None or b is None or not walk[a] or not walk[b] or abs(lh[b] - lh[a]) <= N.STEP:
            continue
        f = float(e.get("facing") or 0.0)
        stand = (float(bottom[0]), float(lh[a]), float(bottom[2]))
        foot = (stand[0] + LADDER_REACH * math.sin(f), stand[1], stand[2] + LADDER_REACH * math.cos(f))
        bx, bz = centre(b)
        land = (bx, float(lh[b]), bz)
        u = _tri_at(points, tris, by_rect, int(rect_of[a]), stand[0], stand[2])
        v = _tri_at(points, tris, by_rect, int(rect_of[b]), land[0], land[2])
        if u is None or v is None:
            continue
        rise = abs(land[1] - stand[1])
        base = {"kind": "ladder", "source": e.get("source"), "rungs": e.get("rungs"), "facing": round(f, 4),
                "cost": LADDER_COST + rise, "verified": False}
        out.append(dict(base, direction="up", u=u, v=v, approach=stand, portal=foot, landing=land))
        out.append(dict(base, direction="down", u=v, v=u, approach=land, portal=(foot[0], land[1], foot[2]),
                        landing=stand))
    for k, row in enumerate(out):
        row["edge"] = 3 * (k + 1) + _near_edge(points, tris[row["u"]], row["portal"])
    return out


# --- the stage file -------------------------------------------------------------------------------------------------

def _pack(a, dtype: str) -> str:
    return base64.b64encode(zlib.compress(np.ascontiguousarray(a).astype(dtype).tobytes(), 9)).decode()


def _wall_rows(col: dict) -> list[list[int]]:
    """The SAT's steep triangles as [x0, z0, x1, z1, y_low, y_high, attr, ax, ay, az, bx, by, bz, cx, cy, cz] (whole
    mm): the two vertices furthest apart in x / z (re4_navmap._wall_segments), for drawing and the coarse shot test,
    then the triangle itself (2026-11-10: the segment with its whole height span reads the empty half of a sloped or
    stepped facade as solid - 415 held shots in one Castle round - so the shot test confirms on the triangle)."""
    V, T, Nn, A = col["verts"], col["tris"], col["normals"], col["attr"]
    out = []
    for t in np.nonzero(np.abs(Nn[:, 1]) < WALL_NY)[0]:
        P = V[T[t]]
        i, j = max(((0, 1), (1, 2), (0, 2)), key=lambda q: (P[q[0], 0] - P[q[1], 0]) ** 2 + (P[q[0], 2] - P[q[1], 2]) ** 2)
        out.append([int(round(v)) for v in (P[i, 0], P[i, 2], P[j, 0], P[j, 2], P[:, 1].min(), P[:, 1].max())]
                   + [int(A[t])] + [int(round(v)) for v in P.reshape(-1)])   # + the triangle (x, y, z) x 3
    return out


def build_stage(udas: bytes, esl: bytes, room: str, *, esl_name: str | None = None, log=None) -> dict:
    """A Switch room pack and its Mercenaries set list -> the stage JSON (re4_nav reads it)."""
    log = log or (lambda *a: None)
    room = room.lower()
    files, slots = room_files(udas)
    t0 = time.time()
    st = N.build_stage(files, {f"etc/{esl_name or ESL_OF.get(room, 'omake01.esl')}": esl_to_gc(esl)}, room)
    log(f"{room}: GameCube navmap rules on the Switch collision, {time.time() - t0:.1f} s")
    col = N.sat_read(next(b for ext, b in files if ext == "SAT"))
    g = N.NavGrid.from_json(st["grid"])
    t0 = time.time()
    mesh = build_mesh(g, col, st["events"])
    pts, tris = mesh["points"], mesh["tris"]
    log(f"{room}: {len(pts)} points, {len(tris)} triangles, {len(mesh['crossings'])} crossings in {time.time() - t0:.1f} s")
    P = np.array(pts)
    area = 0.0
    for a, b, c in tris:
        (x1, _, z1), (x2, _, z2), (x3, _, z3) = pts[a], pts[b], pts[c]
        area += abs((x2 - x1) * (z3 - z1) - (x3 - x1) * (z2 - z1)) / 2
    bonuses = [{k: e[k] for k in ("kind", "pos", "seconds", "stand", "reachable", "source") if k in e}
               for e in st["events"] if e.get("kind") in ("time_bonus", "combo_bonus")]
    ladders = [{k: e[k] for k in ("pos", "top", "facing", "rungs", "source") if k in e}
               for e in st["events"] if e.get("kind") == "ladder"]
    sha = hashlib.sha256(udas).hexdigest()
    return {
        "format": FORMAT, "title_id": TITLE_ID, "game_id": GAME_ID, "room": room, "stage": ROOMS.get(room, room),
        "units": "mm", "y": "up", "heading": "atan2(dx, dz)",
        "source": {"room_file": f"romfs/bio4/st4/{room}.udas", "room_sha256": sha, "sat_slot": slots["SAT"][0],
                   "sat_sha256": slots["SAT"][1], "esl_file": f"romfs/bio4/etc/{esl_name or ESL_OF.get(room)}",
                   "esl_sha256": hashlib.sha256(esl).hexdigest(), "built": time.strftime("%Y-%m-%d"),
                   "rules": "gbox.re4_navmap.build_stage (GameCube navmap) on the Switch SAT; gbox.re4_switch_nav.build_mesh",
                   "rebuild": f"python -m gbox.re4_switch_nav build --st4 <bio4/st4> --etc <bio4/etc> --room {room}"},
        "params": {"cell": g.cell, "step": N.STEP, "clear": N.CLEAR, "max_side": MAX_SIDE, "plane_tol": PLANE_TOL,
                   "vault_span": VAULT_SPAN, "drop_max": N.DROP_MAX},
        "counts": {"points": len(pts), "tris": len(tris), "crossings": len(mesh["crossings"]),
                   "vaults": sum(c["kind"] == "vault" for c in mesh["crossings"]),
                   "ladders": sum(c["kind"] == "ladder" for c in mesh["crossings"]),
                   "walkable_cells": mesh["stats"]["walkable_cells"], "rectangles": mesh["stats"]["rectangles"],
                   "area_m2": round(area / 1e6, 1), "sat_tris": len(col["tris"]),
                   "sat_floor_tris": int((col["normals"][:, 1] >= 0.7).sum()),
                   "walls": int((np.abs(col["normals"][:, 1]) < WALL_NY).sum())},
        "bounds": {"x": [int(P[:, 0].min()), int(P[:, 0].max())], "z": [int(P[:, 2].min()), int(P[:, 2].max())],
                   "y": [int(P[:, 1].min()), int(P[:, 1].max())]},
        "encoding": "points: zlib+base64 little-endian int32 x, y, z (mm); tris: zlib+base64 little-endian int32 a, b, c",
        "points": _pack(np.round(P).astype(np.int64).ravel(), "<i4"),
        "tris": _pack(np.asarray(tris, np.int64).ravel(), "<i4"),
        "crossings": [{k: ([round(float(x)) for x in v] if isinstance(v, (tuple, list)) else v) for k, v in c.items()}
                      for c in mesh["crossings"]],
        "walls": _wall_rows(col),
        "bonuses": bonuses, "ladders": ladders,
        "spawns": {"count": len(st["spawns"]), "reachable": sum(bool(s.get("reachable")) for s in st["spawns"])},
    }


def write_stage(stage: dict, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = Path(out_dir) / f"{stage['room']}.json"
    path.write_text(json.dumps(stage, separators=(",", ":")) + "\n", encoding="utf-8")
    return path


# --- checks: the drawn floor, previews -----------------------------------------------------------------------------

def drawn_up_triangles(udas: bytes, min_ny: float = 0.6) -> np.ndarray:
    """The room's drawn, up-facing triangles in world mm, (n, 3, 3): every SMD instance's HD model placed as
    gbox.re4_stage_greybox places it (scale, then rotation about x, y, z: its assumption)."""
    from .re4_stage_greybox import room_scene
    from .re4_switch_assets import triangles
    scene = room_scene(udas)
    out = []
    for inst in scene.instances:
        if inst.model >= len(scene.models) or (inst.scale == 0).any():
            continue
        model = scene.models[inst.model]
        world = model.positions().astype(np.float64) @ inst.matrix().T + inst.position
        for faces in triangles(model.materials()):
            if not len(faces):
                continue
            P = world[np.asarray(faces)]
            n = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
            length = np.linalg.norm(n, axis=1)
            ok = length > 0
            ny = np.zeros(len(P))
            ny[ok] = n[ok, 1] / length[ok]
            out.append(P[np.abs(ny) >= min_ny])          # (winding unknown: either side up)
    return np.concatenate(out) if out else np.zeros((0, 3, 3))


def drawn_floor_check(udas: bytes, stage: dict, *, samples: int = 4000, window: float = 400.0, seed: int = 1) -> dict:
    """The mesh against the drawn floor: at triangle centres (a sample), the drawn up-facing surface nearest the mesh's
    height within +-window. d = drawn - collision (mm). The collision floor should lie at or just under the drawn one."""
    from .mercs.titles.re4_nav import from_json
    mesh = from_json(stage)
    drawn = drawn_up_triangles(udas)
    cell = 2000.0
    buckets: dict = {}
    lo, hi = drawn[:, :, [0, 2]].min(axis=1), drawn[:, :, [0, 2]].max(axis=1)
    for t in range(len(drawn)):
        for gx in range(int(math.floor(lo[t, 0] / cell)), int(math.floor(hi[t, 0] / cell)) + 1):
            for gz in range(int(math.floor(lo[t, 1] / cell)), int(math.floor(hi[t, 1] / cell)) + 1):
                buckets.setdefault((gx, gz), []).append(t)
    rng = np.random.default_rng(seed)
    picks = rng.choice(len(mesh.tris), size=min(samples, len(mesh.tris)), replace=False)
    diffs, missing = [], 0
    for t in picks:
        x, y, z = mesh.centre[t]
        cand = buckets.get((int(math.floor(x / cell)), int(math.floor(z / cell))))
        if not cand:
            missing += 1
            continue
        P = drawn[cand]
        (x1, y1, z1), (x2, y2, z2), (x3, y3, z3) = (P[:, k].T for k in range(3))
        det = (z2 - z3) * (x1 - x3) + (x3 - x2) * (z1 - z3)
        okd = np.abs(det) > 1e-6
        det = np.where(okd, det, 1.0)
        l1 = ((z2 - z3) * (x - x3) + (x3 - x2) * (z - z3)) / det
        l2 = ((z3 - z1) * (x - x3) + (x1 - x3) * (z - z3)) / det
        l3 = 1.0 - l1 - l2
        inside = okd & (l1 >= -1e-6) & (l2 >= -1e-6) & (l3 >= -1e-6)
        h = (l1 * y1 + l2 * y2 + l3 * y3)[inside]
        h = h[np.abs(h - y) <= window]
        if not len(h):
            missing += 1
            continue
        diffs.append(float(h[np.argmin(np.abs(h - y))] - y))
    d = np.array(diffs)
    q = (lambda p: round(float(np.percentile(d, p)), 1)) if len(d) else (lambda p: None)
    return {"samples": int(len(picks)), "with_drawn_floor": int(len(d)), "no_drawn_floor_within_window": missing,
            "window_mm": window, "drawn_minus_collision_mm": {"p5": q(5), "p25": q(25), "median": q(50), "p75": q(75),
                                                               "p95": q(95)},
            "within_50mm": round(float((np.abs(d) <= 50).mean()), 3) if len(d) else None,
            "collision_at_or_under_drawn": round(float((d >= -20).mean()), 3) if len(d) else None,
            "drawn_triangles_up": int(len(drawn))}


def render(stage: dict, png: Path, *, size: int = 2048, routes: int = 4, seed: int = 3, clearance: float = 350.0) -> dict:
    """A top-down preview (not the game): floor triangles shaded by height, the rim white, the SAT walls red (fences
    and sills amber), jump-overs magenta, ladders cyan, sample routes green with their corners yellow. +x is drawn to
    the left and +z up, as the tactical map draws it."""
    import random

    from PIL import Image, ImageDraw

    from .mercs.titles.re4_nav import from_json
    m = from_json(stage)
    xs, zs, ys = ([p[k] for p in m.points] for k in (0, 2, 1))
    x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
    scale = (size - 20) / max(x1 - x0, z1 - z0, 1.0)

    def at(x, z):
        return 10 + (x1 - x) * scale, 10 + (z1 - z) * scale
    img = Image.new("RGB", (size, size), (20, 20, 24))
    draw = ImageDraw.Draw(img)
    ylo, yhi = min(ys), max(ys)
    for t in m.tris:
        pts = [m.points[v] for v in t]
        f = (sum(p[1] for p in pts) / 3 - ylo) / max(1.0, yhi - ylo)
        draw.polygon([at(p[0], p[2]) for p in pts],
                     fill=(int(40 + 200 * f), int(120 + 80 * (1 - abs(f - .5) * 2)), int(210 - 170 * f)))
    for i, t in enumerate(m.tris):
        open_edges = {e for _v, e, _c in m.links[i] if e < 3}
        for e in range(3):
            if e not in open_edges:
                a, b = m.points[t[e]], m.points[t[(e + 1) % 3]]
                draw.line([at(a[0], a[2]), at(b[0], b[2])], fill=(255, 255, 255), width=1)
    for w in m.walls:
        draw.line([at(w[0], w[1]), at(w[2], w[3])], fill=(255, 200, 0) if w[6] & N.VAULT_BITS else (255, 60, 60))
    for c in m.crossing_rows.values():
        a, p, l = c["approach"], c["portal"], c["landing"]
        draw.line([at(a[0], a[2]), at(p[0], p[2]), at(l[0], l[2])],
                  fill=(255, 0, 255) if c["kind"] == "vault" else (0, 255, 255), width=3)
    rnd = random.Random(seed)
    comps: dict = {}
    for i in range(len(m.tris)):
        comps.setdefault(m.component(i), []).append(i)
    big = max(comps.values(), key=len)
    drawn = []
    for _ in range(routes):
        a, b = rnd.sample(big, 2)
        r = m.route(m.centre[a], m.centre[b], clearance=clearance)
        if not r:
            continue
        pts = [m.centre[a]] + [tuple(q) for q in r]
        draw.line([at(p[0], p[2]) for p in pts], fill=(0, 255, 0), width=3)
        for q in r:
            cx, cy = at(q[0], q[2])
            draw.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=(255, 255, 0))
        drawn.append({"waypoints": len(r), "metres": round(sum(math.dist(u, v) for u, v in zip(pts, pts[1:])) / 1000, 1),
                      "traversals": sum(isinstance(q, tuple) and hasattr(q, "approach") for q in r)})
    Path(png).parent.mkdir(parents=True, exist_ok=True)
    img.save(png)
    return {"png": str(png), "routes": drawn}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m gbox.re4_switch_nav", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="room packs + set lists -> the per-stage mesh JSONs")
    b.add_argument("--st4", type=Path, required=True, help="bio4/st4 (r400.udas ...), read only")
    b.add_argument("--etc", type=Path, required=True, help="bio4/etc (omake01.esl, omake02.esl), read only")
    b.add_argument("--room", action="append", help="r400 / r402 / r403 / r404 (default: all four)")
    b.add_argument("--out", type=Path, default=DATA_DIR)
    b.add_argument("--png", type=Path, help="also write a top-down preview per stage here")
    v = sub.add_parser("verify", help="the stage meshes against the drawn floor (SMD scene)")
    v.add_argument("--st4", type=Path, required=True)
    v.add_argument("--room", action="append")
    v.add_argument("--data", type=Path, default=DATA_DIR)
    v.add_argument("--png", type=Path)
    args = ap.parse_args(argv)
    rooms = args.room or list(ROOMS)
    report = {}
    for room in rooms:
        udas = (args.st4 / f"{room}.udas").read_bytes()
        if args.cmd == "build":
            esl = (args.etc / ESL_OF[room]).read_bytes()
            stage = build_stage(udas, esl, room, log=lambda *a: print(*a, file=sys.stderr))
            path = write_stage(stage, args.out)
            report[room] = {"file": str(path), "bytes": path.stat().st_size, "counts": stage["counts"],
                            "bounds": stage["bounds"]}
        else:
            stage = json.loads((args.data / f"{room}.json").read_text(encoding="utf-8"))
            if stage["source"]["room_sha256"] != hashlib.sha256(udas).hexdigest():
                print(f"{room}: the room pack is not the one the mesh was built from", file=sys.stderr)
            report[room] = {"drawn_floor": drawn_floor_check(udas, stage), "counts": stage["counts"]}
        if args.png:
            report[room]["preview"] = render(stage, args.png / f"{room}.png")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
