#!/usr/bin/env python3
"""One map format for every Mercenaries stage (#9528): gbox.mercs_map/1, built statically from the committed tables.

    python3 scripts/mercs_map_gen.py [--out gbox-data/mercs/maps] [--title re4|re5|all] [--svg]

Sources (read only; nothing is launched, no game file is touched):
  RE4 Switch: gbox/data/re4_switch_room_map/rNNN.json (#9342 SAT walls + floor mask) and
              gbox/data/re4_switch_nav/rNNN.json (crossings: vaults/ladders, time bonuses, ladders, spawn count).
  RE5 Switch: gbox/data/re5_switch_room_map/sNNN.json (#9360 Havok walls + floor mask).
  RE6 Switch: no collision table is committed -> no map, listed in GAPS (what would settle it).

Output per stage (gbox-data/mercs/maps/<title>/<stage>.json, units mm, y up, x/z ground plane):
  walls     [{a:[x,z], b:[x,z], y0, y1, kind: solid|blocker|walked}]            measured (copied from the table)
  floor     {cell_mm, origin_mm, area_m2, polygons: [[x,z]*4 ...]}              measured mask, merged into rectangles
  doorways  RE4: nav crossings (kind vault|ladder) ; RE5: WALKED wall segments   measured where the source has them
  chokepoints  floor gaps <= CHOKE_MM wide between two walls                       DERIVED (rule in 'derivation')
  cover     wall segments whose height span is COVER_LO..COVER_HI mm high          DERIVED candidate, not verified
  spawns    RE4: only a count (positions not in the table); RE5: not determined
  places    named nodes of the route graph (floor blocks "g<col>_<row>" + bonuses) 
  routes    {nodes, edges}: adjacent blocks joined when RoomMap.walk_block allows the walk between their centres
"""
from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
import sys
from pathlib import Path

SYSTEM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SYSTEM))

from gbox.mercs.core import room_map as core  # noqa: E402

FORMAT = "gbox.mercs_map/1"
BLOCK_CELLS = 8            # a route-graph block: 8 x 8 floor cells (2000 mm)
BLOCK_MIN_FLOOR = 0.25     # a block is a place when at least this share of its cells is floor
CHOKE_MM = 1500.0          # a gap between two walls no wider than this is a chokepoint
COVER_LO, COVER_HI = 600.0, 1400.0
KIND = {core.SOLID: "solid", core.BLOCKER: "blocker", core.WALKED: "walked"}
DATA = SYSTEM / "gbox" / "data"
SOURCES = {
    "re4": {"title_id": "010099A00BC1E000", "dir": DATA / "re4_switch_room_map", "nav": DATA / "re4_switch_nav",
            "fmt": "gbox.re4_switch_room_map/1"},
    "re5": {"title_id": None, "dir": DATA / "re5_switch_room_map", "nav": None, "fmt": "gbox.re5_switch_room_map/1"},
}
GAPS = {
    "re4": ["spawn positions: the nav table carries only a count (spawns.count/reachable); the .esl set lists would settle it",
            "named places are grid blocks plus bonuses; the game's own room names are not in the tables",
            "walls are SAT segments of every storey merged; per-storey floors are not separated"],
    "re5": ["spawn positions: not in the Havok table; the stage's enemy layouts (s40N_emNN) would settle it",
            "bonus positions: only in the learned stage books under gbox-data, not in git",
            "Experimental Facility (s404): no table (its live route lies on none of s404's floors, #9360)",
            "walls are Havok triangles merged; per-storey floors are not separated"],
    "re6": ["no collision table is committed for s1200..s1209 (RE6 Switch); only a NavMesh and greybox research exist: "
            "a Havok/collision parser run over the RomFS on lilspark would settle it",
            "walls, doorways, cover, spawns: not determined"],
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def floor_rectangles(rm: core.RoomMap) -> list:
    """The floor mask as rectangles (row runs merged downwards when the same run repeats): [x0, z0, x1, z1] mm."""
    runs_prev: dict = {}
    rects: list = []
    for r in range(rm.rows + 1):
        runs: dict = {}
        c = 0
        while r < rm.rows and c < rm.cols:
            if rm.floor_at(rm.ox + (c + .5) * rm.cell, rm.oz + (r + .5) * rm.cell):
                s = c
                while c < rm.cols and rm.floor_at(rm.ox + (c + .5) * rm.cell, rm.oz + (r + .5) * rm.cell):
                    c += 1
                runs[(s, c)] = runs_prev.get((s, c), r)
            else:
                c += 1
        for run, r0 in runs_prev.items():
            if run not in runs:
                rects.append((run[0], r0, run[1], r))
        runs_prev = runs
    return [[round(rm.ox + c0 * rm.cell, 1), round(rm.oz + r0 * rm.cell, 1),
             round(rm.ox + c1 * rm.cell, 1), round(rm.oz + r1 * rm.cell, 1)] for c0, r0, c1, r1 in rects]


def _blocks(rm: core.RoomMap) -> dict:
    out = {}
    for br in range((rm.rows + BLOCK_CELLS - 1) // BLOCK_CELLS):
        for bc in range((rm.cols + BLOCK_CELLS - 1) // BLOCK_CELLS):
            n = tot = 0
            sx = sz = 0.0
            for r in range(br * BLOCK_CELLS, min(rm.rows, (br + 1) * BLOCK_CELLS)):
                for c in range(bc * BLOCK_CELLS, min(rm.cols, (bc + 1) * BLOCK_CELLS)):
                    tot += 1
                    x, z = rm.ox + (c + .5) * rm.cell, rm.oz + (r + .5) * rm.cell
                    if rm.floor_at(x, z):
                        n += 1
                        sx += x
                        sz += z
            if tot and n / tot >= BLOCK_MIN_FLOOR:
                out[(bc, br)] = (round(sx / n, 1), round(sz / n, 1))
    return out


def _feet_y(rm: core.RoomMap, p, r: float = 2500.0) -> float:
    """ESTIMATE of the floor height at p (the table has none): the commonest wall base (250 mm bins) within r, else 0.
    Walls stop a walk by their height above the feet, so a wrong storey only mis-blocks; flagged y_est in the nodes."""
    bins: dict = {}
    for k in rm.walls_near((p[0], 0, p[1]), (p[0], 0, p[1]), pad=r):
        w = rm.walls[k]
        if core._dist_seg(p[0], p[1], *w[:4]) <= r:
            b = round(w[4] / 250.0) * 250.0
            bins[b] = bins.get(b, 0) + 1
    return max(bins, key=bins.get) if bins else 0.0


def route_graph(rm: core.RoomMap, extra_places: list | None = None) -> dict:
    """Nodes = floor blocks at their floor centroid; an edge joins 4/8-neighbours when the walk between the centroids is
    allowed by the shared RoomMap rules (floor all the way, no wall at body height)."""
    blocks = _blocks(rm)
    ys = {k: _feet_y(rm, p) for k, p in blocks.items()}
    nodes = {f"g{bc}_{br}": {"pos": p, "kind": "block", "y_est": ys[(bc, br)]} for (bc, br), p in blocks.items()}
    edges = []
    for (bc, br), a in blocks.items():
        for dc, dr in ((1, 0), (0, 1), (1, 1), (1, -1)):
            b = blocks.get((bc + dc, br + dr))
            if b is None:
                continue
            ya = ys[(bc, br)]
            if rm.walk_block((a[0], ya, a[1]), (b[0], ya, b[1]), end_r=0.0, body_r=0.0) is None:
                edges.append([f"g{bc}_{br}", f"g{bc + dc}_{br + dr}", round(math.dist(a, b), 1)])
    for name, pos in (extra_places or []):
        best = min(blocks.items(), key=lambda kv: math.dist(kv[1], pos), default=None)
        nodes[name] = {"pos": [round(pos[0], 1), round(pos[1], 1)], "kind": "place"}
        if best is not None:
            edges.append([name, f"g{best[0][0]}_{best[0][1]}", round(math.dist(best[1], pos), 1)])
    return {"nodes": nodes, "edges": edges, "block_cells": BLOCK_CELLS}


def route(graph: dict, a: str, b: str):
    """Shortest named route a -> b on the graph: ([names], length_mm) or None."""
    adj: dict = {}
    for u, v, w in graph["edges"]:
        adj.setdefault(u, []).append((v, w))
        adj.setdefault(v, []).append((u, w))
    dist, prev, heap = {a: 0.0}, {}, [(0.0, a)]
    while heap:
        d, u = heapq.heappop(heap)
        if u == b:
            path = [b]
            while path[-1] != a:
                path.append(prev[path[-1]])
            return path[::-1], round(d, 1)
        if d > dist.get(u, math.inf):
            continue
        for v, w in adj.get(u, ()):
            if d + w < dist.get(v, math.inf):
                dist[v], prev[v] = d + w, u
                heapq.heappush(heap, (d + w, v))
    return None


def chokepoints(rm: core.RoomMap) -> list:  # noqa: C901
    """DERIVED: pairs of nearly parallel solid/blocker walls whose facing segments are <= CHOKE_MM apart (and wider than
    the body), reported at the midpoint. Candidate doorways/corridors; not verified in game."""
    out, seen = [], set()
    ws = [w for w in rm.walls if w[6] != core.WALKED and (w[5] - w[4]) >= 1000]
    for i, w in enumerate(ws):
        ax, az, bx, bz = w[:4]
        ln = math.hypot(bx - ax, bz - az)
        if ln < 300:
            continue
        mx, mz = (ax + bx) / 2, (az + bz) / 2
        nx, nz = -(bz - az) / ln, (bx - ax) / ln
        for side in (1, -1):
            for dist in (600, 900, 1200, CHOKE_MM):
                px, pz = mx + side * nx * dist, mz + side * nz * dist
                hit = next((o for o in ws if o is not w and core._dist_seg(px, pz, *o[:4]) < 60
                                         and abs((o[2] - o[0]) * nx + (o[3] - o[1]) * nz) < 0.35 * math.hypot(o[2] - o[0], o[3] - o[1])), None)
                if hit and rm.floor_at(mx + side * nx * dist / 2, mz + side * nz * dist / 2):
                    key = (round((mx + px) / 2 / 500), round((mz + pz) / 2 / 500))
                    if key not in seen:
                        seen.add(key)
                        out.append({"pos": [round((mx + px) / 2, 1), round((mz + pz) / 2, 1)], "width_mm": dist})
                    break
    return out


def build_stage(title: str, stage_file: Path) -> dict:
    src = SOURCES[title]
    data = json.loads(stage_file.read_text(encoding="utf-8"))
    if data.get("format") != src["fmt"]:
        raise ValueError(f"{stage_file.name}: format {data.get('format')!r}")
    rm = core.from_json(data)
    rects = floor_rectangles(rm)
    area = sum((r[2] - r[0]) * (r[3] - r[1]) for r in rects) / 1e6
    doorways, places, spawns = [], [], {"count": None, "positions": "not determined"}
    nav_file = None
    if src["nav"] is not None and (src["nav"] / stage_file.name).exists():
        nav_file = src["nav"] / stage_file.name
        nav = json.loads(nav_file.read_text(encoding="utf-8"))
        for c in nav.get("crossings", []):
            doorways.append({"kind": c["kind"], "from": [c["approach"][0], c["approach"][2]],
                             "to": [c["landing"][0], c["landing"][2]], "drop_mm": c.get("drop_mm"),
                             "source": "nav crossings"})
        for i, b in enumerate(nav.get("bonuses", [])):
            places.append((f"bonus{i}_{b['kind']}", (b["pos"][0], b["pos"][2])))
        spawns = {"count": nav.get("spawns", {}).get("count"), "reachable": nav.get("spawns", {}).get("reachable"),
                  "positions": "not determined"}
    else:
        doorways = [{"kind": "walked", "from": [w[0], w[1]], "to": [w[2], w[3]], "y0": w[4], "y1": w[5],
                     "source": "wall flag WALKED"} for w in rm.walls if w[6] == core.WALKED]
    graph = route_graph(rm, places)
    cover = [{"a": [w[0], w[1]], "b": [w[2], w[3]], "height_mm": round(w[5] - w[4], 1)}
             for w in rm.walls if w[6] == core.SOLID and COVER_LO <= (w[5] - w[4]) <= COVER_HI
             and math.hypot(w[2] - w[0], w[3] - w[1]) >= 500]
    return {
        "format": FORMAT, "title": title, "room": data["room"], "stage": data["stage"], "units": "mm", "y": "up",
        "source": {"room_map": f"gbox/data/{stage_file.parent.name}/{stage_file.name}", "room_map_sha256": _sha(stage_file),
                   "nav": (f"gbox/data/{nav_file.parent.name}/{nav_file.name}" if nav_file else None),
                   "origin_research": (data.get("source") or {}).get("research")},
        "bounds": {"x": [rm.ox, rm.ox + rm.cols * rm.cell], "z": [rm.oz, rm.oz + rm.rows * rm.cell]},
        "walls": [{"a": [w[0], w[1]], "b": [w[2], w[3]], "y0": w[4], "y1": w[5], "kind": KIND[w[6]]} for w in rm.walls],
        "floor": {"cell_mm": rm.cell, "origin_mm": [rm.ox, rm.oz], "area_m2": round(area, 1),
                  "polygons": [[[r[0], r[1]], [r[2], r[1]], [r[2], r[3]], [r[0], r[3]]] for r in rects]},
        "doorways": doorways, "chokepoints": chokepoints(rm), "cover": cover, "spawns": spawns,
        "places": {n: [round(p[0], 1), round(p[1], 1)] for n, p in places}, "routes": graph,
        "derivation": {"chokepoints": f"derived: parallel walls >=1000 mm tall, gap <= {CHOKE_MM:.0f} mm, floor between",
                       "cover": f"derived: SOLID wall >= 500 mm long, height span {COVER_LO:.0f}..{COVER_HI:.0f} mm",
                       "floor.polygons": "measured mask merged to rectangles (row runs, equal runs merged downwards)",
                       "routes": f"{BLOCK_CELLS}x{BLOCK_CELLS}-cell blocks (floor share >= {BLOCK_MIN_FLOOR}); edge = RoomMap.walk_block clear"},
        "gaps": list(GAPS[title]) + (["the floor mask covers the whole grid (no floor edge): the table does not say where "
                                     "the floor ends, walls only"] if len(rects) == 1 and area * 1e6 >= rm.cols * rm.rows * rm.cell ** 2 * 0.99 else []),
    }


def svg(m: dict, px: int = 1024) -> str:
    """The tactical map drawn from the unified JSON: floor, walls (solid dark, blocker red, walked green), doorways,
    route graph. Text only."""
    (x0, x1), (z0, z1) = m["bounds"]["x"], m["bounds"]["z"]
    s = px / max(x1 - x0, z1 - z0)

    def P(x, z):
        return f"{(x - x0) * s:.1f},{(z1 - z) * s:.1f}"
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{(x1 - x0) * s:.0f}" height="{(z1 - z0) * s:.0f}">',
           '<rect width="100%" height="100%" fill="#111"/>']
    for poly in m["floor"]["polygons"]:
        out.append(f'<polygon points="{" ".join(P(*p) for p in poly)}" fill="#2a3b4a"/>')
    for u, v, _ in m["routes"]["edges"]:
        a, b = m["routes"]["nodes"].get(u), m["routes"]["nodes"].get(v)
        if a and b:
            pa, pb = P(*a["pos"]).split(","), P(*b["pos"]).split(",")
            out.append(f'<line x1="{pa[0]}" y1="{pa[1]}" x2="{pb[0]}" y2="{pb[1]}" stroke="#4a8" stroke-width="0.5"/>')
    col = {"solid": "#ddd", "blocker": "#e44", "walked": "#4e4"}
    for w in m["walls"]:
        a, b = P(*w["a"]).split(","), P(*w["b"]).split(",")
        out.append(f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" stroke="{col[w["kind"]]}" stroke-width="1"/>')
    for d in m["doorways"]:
        a = P(*d["from"]).split(",")
        out.append(f'<circle cx="{a[0]}" cy="{a[1]}" r="2" fill="#fc0"/>')
    out.append("</svg>")
    return "\n".join(out)


def generate(out_dir: Path, titles=("re4", "re5"), draw: bool = False) -> dict:
    report = {}
    for t in titles:
        for f in sorted(SOURCES[t]["dir"].glob("*.json")):
            m = build_stage(t, f)
            d = Path(out_dir) / t
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{m['stage'].replace(' ', '_')}.json").write_text(json.dumps(m, separators=(",", ":")), encoding="utf-8")
            if draw:
                (d / f"{m['stage'].replace(' ', '_')}.svg").write_text(svg(m), encoding="utf-8")
            report[f"{t}/{m['stage']}"] = {"walls": len(m["walls"]), "rects": len(m["floor"]["polygons"]),
                                           "area_m2": m["floor"]["area_m2"], "doorways": len(m["doorways"]),
                                           "chokepoints": len(m["chokepoints"]), "cover": len(m["cover"]),
                                           "route_nodes": len(m["routes"]["nodes"]), "route_edges": len(m["routes"]["edges"])}
    report["re6"] = {"map": None, "gaps": GAPS["re6"]}
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(SYSTEM / "gbox-data" / "mercs" / "maps"))
    ap.add_argument("--title", default="all", choices=("re4", "re5", "all"))
    ap.add_argument("--svg", action="store_true")
    a = ap.parse_args(argv)
    titles = ("re4", "re5") if a.title == "all" else (a.title,)
    print(json.dumps(generate(Path(a.out), titles, a.svg), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
