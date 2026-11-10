"""RE5 (Switch, 010018100CD46000) Mercenaries stages: #9360's collision as the bot's table, one small JSON per stage
(`gbox/data/re5_switch_room_map/s40N.json`, read by `gbox.mercs.titles.re5_room_map`).

#9360 (docs/research/re5-switch-mercs-collision.md / .json and gbox/re5_switch_collision.py, written by Hermes) reads
each stage's Havok packfile (`stage\\s40N\\havok\\s40N` in ImgNX/Archive/s40N.arc) into a 250 mm walk grid and wall
segments, RE4's rules. Checked 2026-11-10 on lilspark (read-only) before any of it went in:

* the parser reproduces the doc's table (vertices, triangles, floor / blocked cells, wall segments) for all eight;
* the frame (game cm = Havok m x 100, no flip) and the archive names hold for seven: the bot's own live route of each
  stage - gbox-data/mercs/round_maps/<navigation signature>, the stage named by ss_ledger.SIGNATURES - stands on that
  archive's floor (99 % of 1500 samples within 30 cm, median 0 cm): s400 Public Assembly, s401 The Mines, s402 Village,
  s403 Ancient Ruins, s405 Missile Area, s406 Ship Deck (33 samples), s407 Prison;
* s404 does NOT hold for Experimental Facility: its live route (y 0.25 / -4.75 m) lies on none of s404's floors under
  any mirror or quarter turn. No table for it;
* the grid's `#` cells are cells a wall crosses (its rule holds), and the bot stands on them: 1.4 - 19 % of each
  stage's live samples (The Mines 287 of 1500). Taken as walls they would refuse where he walks; the walls themselves
  are what a walk must not cross.

So the table keeps: the floor mask by the parser's floor rule (normal y >= 0.5 by the winding, every storey merged)
and the parser's wall segments (the triangle's extreme points along its horizontal tangent, mm), each with the height
span of the triangles that give it (the 2D segments alone would stack every storey's walls onto every floor). The
Havok mesh has no invisible-blocker flag: every wall is solid to a shot too.

    python -m gbox.re5_switch_room_map build --archive <ImgNX/Archive> [--out DIR] [--stdout]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

from gbox import re5_switch_collision as C
from gbox.re4_switch_room_map import floor_mask, pack_mask

FORMAT = "gbox.re5_switch_room_map/1"
TITLE_ID = "010018100CD46000"
# the archives whose frame and name the live routes confirmed (s404 left out: see the docstring)
ARCHIVES = {400: "Public Assembly", 401: "The Mines", 402: "Village", 403: "Ancient Ruins", 405: "Missile Area",
            406: "Ship Deck", 407: "Prison"}
DATA_DIR = Path(__file__).resolve().parent / "data" / "re5_switch_room_map"
DOC = "docs/research/re5-switch-mercs-collision.md (#9360)"


def wall_spans(verts, tris) -> dict:
    """{segment (x0, z0, x1, z1) mm, as the parser keys it: (y low, y high) mm} over its wall triangles."""
    out: dict = {}
    V = np.asarray(verts, dtype=np.float64) * 1000.0
    for a, b, c, n in C.classify(verts, tris):
        if n is None or abs(n[1]) >= 0.5:
            continue
        p, q, r = V[a], V[b], V[c]
        ys = (p[1], q[1], r[1])
        if (max(ys) - min(ys)) / 1000.0 <= C.WALL_MIN_HEIGHT_M:
            continue
        t = np.array([-n[2], n[0]])
        pts = [np.array([p[0], p[2]]), np.array([q[0], q[2]]), np.array([r[0], r[2]])]
        k = [float(pt @ t) for pt in pts]
        lo, hi = pts[k.index(min(k))], pts[k.index(max(k))]
        key = (round(lo[0]), round(lo[1]), round(hi[0]), round(hi[1]))
        y0, y1 = out.get(key, (float("inf"), float("-inf")))
        out[key] = (min(y0, min(ys)), max(y1, max(ys)))
    return out


def build(havok: bytes, n: int) -> dict:
    """One stage's table from its Havok packfile (the parser's grid and segments, the floor, the walls' spans)."""
    (verts, tris), = C.simple_meshes(havok)
    g = C.walk_grid(verts, tris)
    origin, cols, rows = g["origin_mm"], g["cols"], g["rows"]
    normals = np.array([q if q is not None else (0.0, 0.0, 0.0) for *_, q in C.classify(verts, tris)])
    col = {"verts": np.asarray(verts, dtype=np.float64) * 1000.0, "tris": np.asarray(tris), "normals": normals}
    floor = floor_mask(col, origin, cols, rows, C.CELL_MM)
    spans = wall_spans(verts, tris)
    walls = [[float(s[0]), float(s[1]), float(s[2]), float(s[3]), round(spans[s][0]), round(spans[s][1]), 0]
             for s in g["wall_segments_mm"]]
    chars = np.array([list(r) for r in g["rows_chars"]])
    dot, hash_ = chars == ".", chars == "#"
    return {
        "format": FORMAT, "title_id": TITLE_ID, "room": f"s{n}", "stage": ARCHIVES.get(n, C.STAGES.get(n, "")),
        "units": "mm", "y": "up",
        "source": {"research": DOC, "archive_file": f"romfs/nativeNXx64/ImgNX/Archive/s{n}.arc",
                   "havok_sha256": hashlib.sha256(havok).hexdigest(), "built": time.strftime("%Y-%m-%d"),
                   "rebuild": f"python -m gbox.re5_switch_room_map build --archive <ImgNX/Archive> --stage {n}",
                   "kept": "the floor mask by the parser's floor rule and its wall segments with the height span of "
                           "the triangles that give them; its '#' cells are not kept (cells a wall crosses: the bot "
                           "stands on them)"},
        "grid": {"origin_mm": [float(origin[0]), float(origin[1])], "cell_mm": C.CELL_MM, "cols": cols, "rows": rows,
                 "encoding": "floor: zlib+base64 of numpy.packbits over rows x cols bits, row-major, row 0 the "
                             "smallest z, column 0 the smallest x, 1 = floor",
                 "floor": pack_mask(floor)},
        "walls_encoding": "[x0, z0, x1, z1, y low, y high, blocker] mm (the Havok mesh has no blocker flag: 0)",
        "walls": walls,
        "checks": {"vertices": len(verts), "triangles": len(tris), "parser_floor_cells": g["floor_cells"],
                   "parser_blocked_cells": g["blocked_cells"], "parser_wall_segments": len(g["wall_segments_mm"]),
                   "floor_cells": int(floor.sum()), "parser_floor_cells_without_floor": int((dot & ~floor).sum()),
                   "parser_blocked_cells_with_floor": int((hash_ & floor).sum())},
    }


def route_steps(round_maps: Path, stage: str) -> list:
    """The bot's own walked steps on a stage (cm): consecutive samples of every round map under its navigation
    signature (gbox-data/mercs/round_maps/<title>/<signature>/*.json, route rows [t, x, z, y]) at most 0.3 s and 150 cm
    apart (5 cm at least), on one level (30 cm)."""
    from gbox.mercs.ss_ledger import SIGNATURES
    out, seen = [], set()
    for sig in (s for s, name in SIGNATURES.items() if name == stage):
        for f in sorted(Path(round_maps).glob(f"{sig}/*.json")):
            try:
                rows = [(q[0], q[1], q[3], q[2]) for q in json.loads(f.read_text(encoding="utf-8")).get("route") or ()
                        if len(q) >= 4]
            except (OSError, ValueError, TypeError, IndexError):
                continue
            for a, b in zip(rows, rows[1:]):
                d = ((b[1] - a[1]) ** 2 + (b[3] - a[3]) ** 2) ** 0.5
                if not (0 < b[0] - a[0] <= 0.3) or not 5.0 <= d <= 150.0 or abs(b[2] - a[2]) > 30.0:
                    continue
                key = (round(a[1] / 20), round(a[3] / 20), round(b[1] / 20), round(b[3] / 20))
                if key not in seen:
                    seen.add(key)
                    out.append((a[1:], b[1:]))
    return out


def mark_walked(table: dict, steps) -> dict:
    """The walls the bot's own walked steps (cm pairs) cross within his body's height, flagged walked-through (2) in
    the table: the collision's doors, gates and props he walks through (combine, never block what he has walked).
    checks.walked_through: {wall index: steps}."""
    from gbox.mercs.core import room_map as RM
    rm = RM.from_json(table)
    hits: dict = {}
    for a, b in steps:
        hit = rm.wall_crossed(tuple(v * 10.0 for v in a), tuple(v * 10.0 for v in b))
        if hit is not None:
            k = rm.walls.index(hit[0])
            hits[k] = hits.get(k, 0) + 1
    for k in hits:
        table["walls"][k][6] = RM.WALKED
    table["checks"]["walked_steps"] = len(steps)
    table["checks"]["walked_through"] = {str(k): n for k, n in sorted(hits.items())}
    table["walls_encoding"] = ("[x0, z0, x1, z1, y low, y high, flag] mm; flag 0 solid (the Havok mesh has no "
                               "invisible-blocker flag), 2 walked through: the bot's own live steps crossed it")
    return table


def write_stage(table: dict, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{table['room']}.json"
    path.write_text(json.dumps(table, separators=(",", ":")) + "\n", encoding="utf-8")
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="gbox.re5_switch_room_map", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="the stages' tables from the RomFS's stage archives")
    b.add_argument("--archive", required=True, type=Path)
    b.add_argument("--stage", action="append", type=int, choices=sorted(ARCHIVES))
    b.add_argument("--out", type=Path, default=DATA_DIR)
    b.add_argument("--stdout", action="store_true", help="print one stage's JSON per line instead of writing files")
    b.add_argument("--round-maps", type=Path, help="gbox-data/mercs/round_maps/010018100CD46000: the walls the bot's "
                                                   "own steps crossed are flagged walked-through")
    a = ap.parse_args(argv)
    for n in a.stage or sorted(ARCHIVES):
        table = build(C.load_stage(str(a.archive), n), n)
        if a.round_maps:
            table = mark_walked(table, route_steps(a.round_maps, ARCHIVES[n]))
        if a.stdout:
            print(json.dumps(table, separators=(",", ":")))
        else:
            print(write_stage(table, a.out), json.dumps(table["checks"]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
