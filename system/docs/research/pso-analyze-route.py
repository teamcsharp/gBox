"""Analyse a recorded walk: build its walk graph, measure coverage, and emit a navigate mission.

The graph is the pathfinding view of what the player actually did: positions collapse into cells (default 8 units), consecutive
samples connect cells, and the report states how many cells/edges/components the walk covered, its length and its bounds. The
mission uses pso_chords.route_mission so the same walk can be replayed.

Usage: analyze_route.py <route.json> [--cell 8] [--out summary.json]
"""
import argparse
import json
import math
import sys
from collections import defaultdict, deque
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")

from gbox import pso_chords                                          # noqa: E402


def load_rows(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("rows") if isinstance(data, dict) else data
    return [r for r in (rows or []) if isinstance(r, dict) and r.get("x") is not None and r.get("z") is not None]


def cell_of(row, size):
    return (int(math.floor(row["x"] / size)), int(math.floor(row["z"] / size)), int(row.get("floor") or 0))


def analyse(rows, cell_size=8.0):
    cells = [cell_of(row, cell_size) for row in rows]
    nodes = set(cells)
    edges = defaultdict(set)
    length = 0.0
    for a, b in zip(rows, rows[1:]):
        if a.get("floor") != b.get("floor"):
            continue
        length += math.dist((a["x"], a["z"]), (b["x"], b["z"]))
        if cells[rows.index(a)] != cells[rows.index(b)]:
            pass
    for (ca, cb) in zip(cells, cells[1:]):
        if ca == cb:
            continue
        edges[ca].add(cb)
        edges[cb].add(ca)
    # connected components over the cell graph
    seen, components = set(), []
    for node in nodes:
        if node in seen:
            continue
        queue, group = deque([node]), []
        seen.add(node)
        while queue:
            current = queue.popleft()
            group.append(current)
            for neighbour in edges[current]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    queue.append(neighbour)
        components.append(group)
    xs = [r["x"] for r in rows]
    zs = [r["z"] for r in rows]
    floors = sorted({int(r.get("floor") or 0) for r in rows})
    return {
        "samples": len(rows),
        "cell_size": cell_size,
        "cells": len(nodes),
        "edges": sum(len(v) for v in edges.values()) // 2,
        "components": sorted((len(c) for c in components), reverse=True),
        "largest_component": max((len(c) for c in components), default=0),
        "length_units": round(length, 1),
        "bounds": {"x": [round(min(xs), 1), round(max(xs), 1)], "z": [round(min(zs), 1), round(max(zs), 1)]},
        "floors": floors,
        "turnarounds": sum(1 for a, b, c in zip(rows, rows[1:], rows[2:])
                           if (b["x"] - a["x"]) * (c["x"] - b["x"]) + (b["z"] - a["z"]) * (c["z"] - b["z"]) < 0),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("route")
    ap.add_argument("--cell", type=float, default=8.0)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    source = Path(args.route)
    rows = load_rows(source)
    summary = analyse(rows, args.cell)
    print(json.dumps(summary, indent=1))
    mission = pso_chords.route_mission(rows, game_id="436e0bb84d5337d1", name=source.stem,
                                       tolerance=args.cell, source=str(source))
    mission_path = source.with_name(source.stem + "-mission.json")
    mission_path.write_text(json.dumps(mission, indent=1), encoding="utf-8")
    print("mission waypoints:", mission["provenance"]["waypoints"], "->", mission_path)
    if args.out:
        Path(args.out).write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
