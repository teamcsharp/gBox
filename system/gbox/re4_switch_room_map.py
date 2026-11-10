"""RE4 (Switch, 010099A00BC1E000) Mercenaries rooms: #9342's walk map as the bot's table, one small JSON per stage
(`gbox/data/re4_switch_room_map/r4xx.json`, read by `gbox.mercs.titles.re4_room_map`).

#9342 (docs/research/re4-switch-mercs-collision.md / .json, written by Hermes) decoded each room's player collision
(DAT slot 1, SAT) into a 250 mm walk grid (`.` floor, `#` wall) and the room's wall segments (faces steeper than 60
degrees and taller than 1 m, each one 2D segment along the face's horizontal tangent, duplicates removed). Checked
2026-11-10 against the RomFS on lilspark (read-only) before any of it went in:

* the record layout, y up, millimetres: hold (the layout gbox.re4_switch_nav reads; the four rooms' vertex / triangle
  counts and the triangle table offsets agree);
* the wall segments: hold - every one of the doc's 482 / 477 / 707 / 352 (r400 / r402 / r403 / r404) is rebuilt by
  its stated rule from the SAT to the 0.1 mm the doc prints;
* the frame: hold in all four rooms - the bot's own live RAM positions (gbox-data/mercs/re4-sight-blocks.jsonl, the
  tactical map's Base round) lie on each room's floor with RAM y equal to the SAT floor's height (median 0 mm);
* the grid's `#` cells: do NOT hold. By the doc's own rule 4953 / 3963 / 6113 / 9721 of them have floor and no wall
  segment crossing them (each table's checks), and the bot stood on them live (Waterworld 16 of 22 sight-block
  positions, Base 75 of 83 tactical samples): taken as walls they would hold him still across whole rooms. Its `.`
  cells hold (each is floor by the rule).

So the table keeps what holds: the floor mask by the doc's rule (a cell is floor when its centre lies under a SAT
triangle with normal.y >= 0.5; every storey merged), and the doc's wall segments, each with the height span of the
triangles that give it (their lowest and highest y: the 2D segments alone would stack every storey's walls onto every
floor) and whether all of them are invisible blockers (attr 0x400: the player cannot pass them, a shot can -
re4_nav.BLOCKER_BIT). A `#` cell is then computed where it is used: no floor, or a wall within his body's height
crossing it.

    python -m gbox.re4_switch_room_map build --st4 <bio4/st4> --doc <re4-switch-mercs-collision.json> [--out DIR]
    (on lilspark: ~/gBox_alt/switch/romfs/010099A00BC1E000/bio4/st4; --stdout prints one room per line instead)
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import sys
import time
import zlib
from pathlib import Path

import numpy as np

from gbox import re4_navmap as N
from gbox.re4_switch_nav import room_files

FORMAT = "gbox.re4_switch_room_map/1"
TITLE_ID = "010099A00BC1E000"
ROOMS = {"r400": "Village", "r402": "Castle", "r403": "Base", "r404": "Waterworld"}
DATA_DIR = Path(__file__).resolve().parent / "data" / "re4_switch_room_map"
FLOOR_NY = 0.5                  # #9342: floor or a slope up to 60 degrees
WALL_NY, WALL_DY = 0.5, 1000.0  # #9342: steeper than 60 degrees and taller than 1 m
BLOCKER_BIT = 0x400             # re4_navmap / re4_nav: an invisible blocker (the player stops, a shot passes)
SAMPLE_MM = 62.5                # #9342: a segment is sampled this often to mark the cells it crosses
DOC = "docs/research/re4-switch-mercs-collision.md (#9342)"


def sat_of(udas: bytes) -> dict:
    """The room pack's player collision (DAT slot SAT) as re4_navmap.sat_read gives it (verts, tris, normals, attr)."""
    files, _slots = room_files(udas)
    return N.sat_read(next(b for ext, b in files if ext == "SAT"))


def _centres_in(P2, ox: float, oz: float, cell: float, cols: int, rows: int):
    """(rows, cols) index arrays of the cells whose centre lies inside the 2D triangle P2 (3 x 2: x, z)."""
    x0, z0 = P2.min(0)
    x1, z1 = P2.max(0)
    c0, c1 = max(0, int(math.floor((x0 - ox) / cell - 0.5))), min(cols - 1, int(math.ceil((x1 - ox) / cell - 0.5)))
    r0, r1 = max(0, int(math.floor((z0 - oz) / cell - 0.5))), min(rows - 1, int(math.ceil((z1 - oz) / cell - 0.5)))
    if c1 < c0 or r1 < r0:
        return None
    cc, rr = np.meshgrid(np.arange(c0, c1 + 1), np.arange(r0, r1 + 1))
    X, Z = ox + (cc + 0.5) * cell, oz + (rr + 0.5) * cell
    a, b, c = P2

    def side(p, q):
        return (X - q[0]) * (p[1] - q[1]) - (p[0] - q[0]) * (Z - q[1])
    d1, d2, d3 = side(a, b), side(b, c), side(c, a)
    inside = ~(((d1 < 0) | (d2 < 0) | (d3 < 0)) & ((d1 > 0) | (d2 > 0) | (d3 > 0)))
    return rr[inside], cc[inside]


def floor_mask(col: dict, origin, cols: int, rows: int, cell: float = 250.0) -> np.ndarray:
    """#9342's floor rule on its grid: (rows, cols) bool, row 0 the smallest z, column 0 the smallest x."""
    V, T, ny = col["verts"], col["tris"], col["normals"][:, 1]
    out = np.zeros((rows, cols), bool)
    for t in np.nonzero(ny >= FLOOR_NY)[0]:
        got = _centres_in(V[T[t]][:, [0, 2]], float(origin[0]), float(origin[1]), cell, cols, rows)
        if got is not None:
            out[got] = True
    return out


def wall_triangles(col: dict) -> list[list]:
    """#9342's walls, one row per SAT triangle: [x0, z0, x1, z1, y low, y high, attr] - the 2D segment along the face's
    horizontal tangent (the triangle's vertices projected on it, at its centroid's offset), 0.1 mm."""
    V, T, Nn, A = col["verts"], col["tris"], col["normals"], col["attr"]
    out = []
    for t in range(len(T)):
        n = Nn[t]
        P = V[T[t]]
        lo, hi = float(P[:, 1].min()), float(P[:, 1].max())
        if not (abs(n[1]) < WALL_NY and hi - lo > WALL_DY):
            continue
        tan = np.array([-n[2], n[0]])
        norm = float(np.linalg.norm(tan))
        if norm < 1e-9:
            continue
        tan /= norm
        xz = P[:, [0, 2]]
        s = xz @ tan
        cen = xz.mean(0)
        off = cen - (cen @ tan) * tan
        a, b = off + s.min() * tan, off + s.max() * tan
        out.append([round(float(a[0]), 1), round(float(a[1]), 1), round(float(b[0]), 1), round(float(b[1]), 1),
                    round(lo, 1), round(hi, 1), int(A[t])])
    return out


def seg_key(s) -> tuple:
    """A 2D segment, either direction, to the whole mm (how the doc's printed 0.1 mm rows are matched)."""
    p, q = (round(s[0]), round(s[1])), (round(s[2]), round(s[3]))
    return (p, q) if p <= q else (q, p)


def crossed_cells(segs, origin, cols: int, rows: int, cell: float = 250.0) -> np.ndarray:
    """The cells a 2D segment passes through, sampled every SAMPLE_MM (#9342's rule)."""
    out = np.zeros((rows, cols), bool)
    for s in segs:
        L = math.hypot(s[2] - s[0], s[3] - s[1])
        k = max(1, int(math.ceil(L / SAMPLE_MM)))
        for j in range(k + 1):
            x, z = s[0] + (s[2] - s[0]) * j / k, s[1] + (s[3] - s[1]) * j / k
            c, r = int(math.floor((x - origin[0]) / cell)), int(math.floor((z - origin[1]) / cell))
            if 0 <= c < cols and 0 <= r < rows:
                out[r, c] = True
    return out


def pack_mask(mask: np.ndarray) -> str:
    return base64.b64encode(zlib.compress(np.packbits(mask.ravel().astype(np.uint8)).tobytes(), 9)).decode()


def doc_digest(doc: dict) -> str:
    """The research JSON's content hash (sorted keys: the same on a CRLF or an LF checkout)."""
    return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()


def build(udas: bytes, room: str, doc: dict) -> dict:
    """One room's table from its pack and #9342's JSON (see the module docstring)."""
    d = doc["rooms"][room]
    g = d["walk_grid"]
    origin, cell, cols, rows = g["origin_mm"], float(g["cell_mm"]), int(g["cols"]), int(g["rows"])
    col = sat_of(udas)
    floor = floor_mask(col, origin, cols, rows, cell)
    tris = wall_triangles(col)
    by: dict = {}
    for row in tris:
        by.setdefault(seg_key(row), []).append(row)
    walls, missing = [], []
    for s in d["wall_segments_mm_x0_z0_x1_z1"]:
        rows_ = by.get(seg_key(s))
        if not rows_:
            missing.append(s)
            continue
        lo, hi = min(r[4] for r in rows_), max(r[5] for r in rows_)
        blocker = int(all(r[6] & BLOCKER_BIT for r in rows_))
        walls.append([float(s[0]), float(s[1]), float(s[2]), float(s[3]), round(lo), round(hi), blocker])
    cells = g["cells"]
    doc_grid = np.frombuffer(cells.encode(), np.uint8).reshape(rows, cols)
    doc_floor, doc_wall = doc_grid == ord("."), doc_grid == ord("#")
    crossed = crossed_cells([w[:4] for w in walls], origin, cols, rows, cell)
    sha = hashlib.sha256(udas).hexdigest()
    return {
        "format": FORMAT, "title_id": TITLE_ID, "room": room, "stage": ROOMS.get(room, room), "units": "mm", "y": "up",
        "source": {"research": DOC, "research_sha256": doc_digest(doc), "room_file": f"romfs/bio4/st4/{room}.udas",
                   "room_sha256": sha, "built": time.strftime("%Y-%m-%d"),
                   "rebuild": f"python -m gbox.re4_switch_room_map build --st4 <bio4/st4> --doc <json> --room {room}",
                   "kept": "the floor mask by #9342's floor rule (rebuilt from the SAT) and #9342's wall segments with "
                           "the height span and blocker flag of the triangles that give them; #9342's '#' cells are "
                           "not kept (they do not follow its own rule: see the checks)"},
        "grid": {"origin_mm": [int(origin[0]), int(origin[1])], "cell_mm": cell, "cols": cols, "rows": rows,
                 "encoding": "floor: zlib+base64 of numpy.packbits over rows x cols bits, row-major, row 0 the "
                             "smallest z, column 0 the smallest x, 1 = floor",
                 "floor": pack_mask(floor)},
        "walls_encoding": "[x0, z0, x1, z1, y low, y high, blocker] mm; blocker 1: every triangle of it is an "
                          "invisible blocker (attr 0x400)",
        "walls": walls,
        "checks": {
            "doc_segments": len(d["wall_segments_mm_x0_z0_x1_z1"]), "doc_segments_rebuilt": len(walls),
            "doc_segments_not_rebuilt": missing[:20],
            "wall_triangles": len(tris), "blockers": sum(w[6] for w in walls),
            "floor_cells": int(floor.sum()), "doc_floor_cells": int(doc_floor.sum()),
            "doc_floor_cells_without_floor": int((doc_floor & ~floor).sum()),
            "doc_wall_cells": int(doc_wall.sum()),
            "doc_wall_cells_rule_floor_uncrossed": int((doc_wall & floor & ~crossed).sum()),
            "doc_wall_cells_without_floor": int((doc_wall & ~floor).sum()),
            "rule_wall_cells": int((floor & crossed).sum()),
        },
    }


def write_room(table: dict, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{table['room']}.json"
    path.write_text(json.dumps(table, separators=(",", ":")) + "\n", encoding="utf-8")
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="gbox.re4_switch_room_map", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="the rooms' tables from the RomFS's room packs and #9342's JSON")
    b.add_argument("--st4", required=True, type=Path)
    b.add_argument("--doc", required=True, type=Path)
    b.add_argument("--room", action="append", choices=sorted(ROOMS))
    b.add_argument("--out", type=Path, default=DATA_DIR)
    b.add_argument("--stdout", action="store_true", help="print one room's JSON per line instead of writing files")
    a = ap.parse_args(argv)
    doc = json.loads(a.doc.read_text(encoding="utf-8"))
    for room in a.room or sorted(ROOMS):
        table = build((a.st4 / f"{room}.udas").read_bytes(), room, doc)
        if a.stdout:
            print(json.dumps(table, separators=(",", ":")))
        else:
            print(write_room(table, a.out), json.dumps(table["checks"]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
