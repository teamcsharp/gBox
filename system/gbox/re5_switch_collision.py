"""RE5 Switch Mercenaries stage collision: read the Havok packfile of s400..s407 and rasterise a walk grid.

Read-only. ``stage\\sNNN\\havok\\sNNN`` in each ``sNNN.arc`` is a zlib stream holding a Havok 5.5.0 packfile
(big-endian, 4-byte pointers) with one hkpRigidBody -> hkpMoppBvTreeShape -> hkpSimpleMeshShape. The mesh is
vertices (hkVector4 f32 x4, w = 1) and 16-byte triangles (i32 a, b, c, u16 welding info, u16 0).
Havok units are metres, up axis y. Nothing here touches a game file except to read it.
"""
from __future__ import annotations

import os
import struct
import zlib

HAVOK_MAGIC = bytes.fromhex("57e0e05710c0c010")
STAGES = {400: "Public Assembly", 401: "The Mines", 402: "Village", 403: "Ancient Ruins",
          404: "Experimental Facility", 405: "Missile Area", 406: "Ship Deck", 407: "Prison"}
CELL_MM = 250.0
WALL_MIN_HEIGHT_M = 1.0


def parse_packfile(b: bytes):
    """-> (data_section_start, [(offset, class_name)], {pointer_offset: target_offset})."""
    if b[:8] != HAVOK_MAGIC:
        raise ValueError("not a Havok packfile")
    nsec = struct.unpack(">I", b[20:24])[0]
    secs = {}
    for i in range(nsec):
        o = 0x40 + i * 0x30
        secs[b[o:o + 19].split(b"\0")[0].decode()] = struct.unpack(">7I", b[o + 20:o + 48])
    cn = secs["__classnames__"][0]
    start, lf, gf, vf, ex, _im, _end = secs["__data__"]
    objs = []
    for o in range(vf, ex, 12):
        s, _sec, n = struct.unpack(">3I", b[start + o:start + o + 12])
        if s == 0xFFFFFFFF:
            break
        objs.append((s, b[cn + n:cn + n + 80].split(b"\0")[0].decode()))
    fix = {}
    for o in range(lf, gf, 8):
        a, c = struct.unpack(">2I", b[start + o:start + o + 8])
        if a != 0xFFFFFFFF:
            fix[a] = c
    return start, objs, fix


def simple_meshes(b: bytes):
    """Every hkpSimpleMeshShape as (vertices [(x,y,z)], triangles [(a,b,c)])."""
    start, objs, fix = parse_packfile(b)
    out = []
    for s, name in objs:
        if name != "hkpSimpleMeshShape":
            continue
        nv = struct.unpack(">I", b[start + s + 0x1C:start + s + 0x20])[0]
        nt = struct.unpack(">I", b[start + s + 0x28:start + s + 0x2C])[0]
        vp, tp = fix[s + 0x18], fix[s + 0x24]
        verts = [struct.unpack(">3f", b[start + vp + 16 * i:start + vp + 16 * i + 12]) for i in range(nv)]
        tris = [struct.unpack(">3i", b[start + tp + 16 * i:start + tp + 16 * i + 12]) for i in range(nt)]
        if tris and (min(min(t) for t in tris) < 0 or max(max(t) for t in tris) >= nv):
            raise ValueError("triangle index outside the vertex array")
        out.append((verts, tris))
    return out


def load_stage(archive_dir: str, stage: int) -> bytes:
    from gbox import mt_arc
    arc = mt_arc.parse(open(os.path.join(archive_dir, "s%d.arc" % stage), "rb").read())
    for e in arc.entries:
        if e.name.endswith("\\havok\\s%d" % stage):
            return zlib.decompress(e.data)
    raise KeyError("no havok entry in s%d.arc" % stage)


def classify(verts, tris):
    """-> list of (a, b, c, normal(nx,ny,nz) or None) with the normal from the winding (a,b,c)."""
    out = []
    for a, b, c in tris:
        p, q, r = verts[a], verts[b], verts[c]
        u = (q[0] - p[0], q[1] - p[1], q[2] - p[2])
        v = (r[0] - p[0], r[1] - p[1], r[2] - p[2])
        n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        ln = (n[0] ** 2 + n[1] ** 2 + n[2] ** 2) ** 0.5
        out.append((a, b, c, None if ln < 1e-12 else (n[0] / ln, n[1] / ln, n[2] / ln)))
    return out


def walk_grid(verts, tris, cell_mm=CELL_MM, wall_min_m=WALL_MIN_HEIGHT_M):
    """Rasterise to a grid. Same rules as docs/research/re4-switch-mercs-collision.md, in mm.

    '.' cell centre under a triangle with normal.y >= 0.5 and no wall segment crosses it; '#' a wall segment
    (|normal.y| < 0.5, vertical extent > wall_min_m) crosses a cell that has floor, or the centre is under a
    wall triangle; ' ' otherwise. Returns a dict with origin_mm, cols, rows, rows_chars, wall_segments_mm.
    """
    import numpy as np
    tri = classify(verts, tris)
    V = np.asarray(verts, dtype=np.float64) * 1000.0
    x0 = np.floor(V[:, 0].min() / cell_mm) * cell_mm
    z0 = np.floor(V[:, 2].min() / cell_mm) * cell_mm
    cols = int(np.ceil((V[:, 0].max() - x0) / cell_mm)) + 1
    rows = int(np.ceil((V[:, 2].max() - z0) / cell_mm)) + 1
    floor = np.zeros((rows, cols), bool)
    wallc = np.zeros((rows, cols), bool)
    cross = np.zeros((rows, cols), bool)

    def fill(grid, p, q, r):
        xs = (p[0], q[0], r[0]); zs = (p[2], q[2], r[2])
        c0 = max(int(np.ceil((min(xs) - x0) / cell_mm - 0.5)), 0)
        c1 = min(int(np.floor((max(xs) - x0) / cell_mm - 0.5)), cols - 1)
        r0 = max(int(np.ceil((min(zs) - z0) / cell_mm - 0.5)), 0)
        r1 = min(int(np.floor((max(zs) - z0) / cell_mm - 0.5)), rows - 1)
        if c1 < c0 or r1 < r0:
            return
        cx = x0 + (np.arange(c0, c1 + 1) + 0.5) * cell_mm
        cz = z0 + (np.arange(r0, r1 + 1) + 0.5) * cell_mm
        X, Z = np.meshgrid(cx, cz)
        d = (q[2] - r[2]) * (p[0] - r[0]) + (r[0] - q[0]) * (p[2] - r[2])
        if abs(d) < 1e-9:
            return
        l1 = ((q[2] - r[2]) * (X - r[0]) + (r[0] - q[0]) * (Z - r[2])) / d
        l2 = ((r[2] - p[2]) * (X - r[0]) + (p[0] - r[0]) * (Z - r[2])) / d
        m = (l1 >= 0) & (l2 >= 0) & (l1 + l2 <= 1)
        grid[r0:r1 + 1, c0:c1 + 1] |= m

    segs = set()
    for a, b, c, n in tri:
        if n is None:
            continue
        p, q, r = V[a], V[b], V[c]
        if n[1] >= 0.5:
            fill(floor, p, q, r)
        elif abs(n[1]) < 0.5:
            ys = (p[1], q[1], r[1])
            if (max(ys) - min(ys)) / 1000.0 > wall_min_m:
                fill(wallc, p, q, r)
                t = np.array([-n[2], n[0]])
                pts = [np.array([p[0], p[2]]), np.array([q[0], q[2]]), np.array([r[0], r[2]])]
                k = [float(pt @ t) for pt in pts]
                lo, hi = pts[k.index(min(k))], pts[k.index(max(k))]
                segs.add((round(lo[0]), round(lo[1]), round(hi[0]), round(hi[1])))
    step = cell_mm / 4.0
    for sx0, sz0, sx1, sz1 in segs:
        ln = ((sx1 - sx0) ** 2 + (sz1 - sz0) ** 2) ** 0.5
        n = max(int(ln / step), 1)
        t = np.linspace(0.0, 1.0, n + 1)
        ci = np.floor((sx0 + (sx1 - sx0) * t - x0) / cell_mm).astype(int)
        ri = np.floor((sz0 + (sz1 - sz0) * t - z0) / cell_mm).astype(int)
        ok = (ci >= 0) & (ci < cols) & (ri >= 0) & (ri < rows)
        cross[ri[ok], ci[ok]] = True
    blocked = (cross & floor) | (wallc & ~floor)
    chars = np.full((rows, cols), " ", dtype="<U1")
    chars[floor] = "."
    chars[blocked] = "#"
    return {"origin_mm": [float(x0), float(z0)], "cols": cols, "rows": rows,
            "rows_chars": ["".join(r) for r in chars], "wall_segments_mm": sorted(segs),
            "floor_cells": int(((chars == ".")).sum()), "blocked_cells": int((chars == "#").sum())}


def rle_row(row: str) -> str:
    """Run-length: '<char><count>' per run, space written as '_' ('_' never occurs in a cell)."""
    out, i = [], 0
    while i < len(row):
        j = i
        while j < len(row) and row[j] == row[i]:
            j += 1
        out.append(("_" if row[i] == " " else row[i]) + str(j - i))
        i = j
    return "".join(out)


def unrle_row(s: str) -> str:
    import re
    return "".join((" " if ch == "_" else ch) * int(n) for ch, n in re.findall(r"([._#])(\d+)", s))


def floor_heights_m(verts, tris, x_m, z_m):
    """Heights (m) of every ny >= 0.5 triangle containing (x, z), sorted."""
    hs = []
    for a, b, c, n in classify(verts, tris):
        if n is None or n[1] < 0.5:
            continue
        p, q, r = verts[a], verts[b], verts[c]
        d = (q[2] - r[2]) * (p[0] - r[0]) + (r[0] - q[0]) * (p[2] - r[2])
        if abs(d) < 1e-12:
            continue
        l1 = ((q[2] - r[2]) * (x_m - r[0]) + (r[0] - q[0]) * (z_m - r[2])) / d
        l2 = ((r[2] - p[2]) * (x_m - r[0]) + (p[0] - r[0]) * (z_m - r[2])) / d
        if l1 >= 0 and l2 >= 0 and l1 + l2 <= 1:
            hs.append(l1 * p[1] + l2 * q[1] + (1 - l1 - l2) * r[1])
    return sorted(hs)


def build_report(archive_dir: str) -> dict:
    """The whole s400..s407 report: counts, bounds and the RLE-encoded grids."""
    stages = {}
    for n, title in STAGES.items():
        (verts, tris), = simple_meshes(load_stage(archive_dir, n))
        cl = classify(verts, tris)
        g = walk_grid(verts, tris)
        xs, ys, zs = zip(*verts)
        stages["s%d" % n] = {
            "stage": title, "vertices": len(verts), "triangles": len(tris),
            "floor_tris": sum(1 for *_, q in cl if q and q[1] >= 0.5),
            "ceiling_tris": sum(1 for *_, q in cl if q and q[1] <= -0.5),
            "degenerate_tris": sum(1 for *_, q in cl if q is None),
            "bounds_m": {"x": [min(xs), max(xs)], "y": [min(ys), max(ys)], "z": [min(zs), max(zs)]},
            "grid": {"cell_mm": CELL_MM, "origin_mm": g["origin_mm"], "cols": g["cols"], "rows": g["rows"],
                     "floor_cells": g["floor_cells"], "blocked_cells": g["blocked_cells"],
                     "encoding": "row-major z then x; per row runs '<char><count>', '_'=no floor, '.'=floor, '#'=blocked",
                     "rows_rle": [rle_row(r) for r in g["rows_chars"]]},
            "wall_segments_mm": [list(s) for s in g["wall_segments_mm"]],
        }
    return {"title": "RE5 Switch No Mercy", "source": "stage\\sNNN\\havok\\sNNN in ImgNX/Archive/sNNN.arc",
            "format": "Havok 5.5.0 packfile, big-endian, 32-bit pointers; hkpSimpleMeshShape; units metres, y up",
            "stages": stages}


if __name__ == "__main__":
    import json
    import sys
    base = sys.argv[1]
    json.dump(build_report(base), open(sys.argv[2], "w"), separators=(",", ":"))
