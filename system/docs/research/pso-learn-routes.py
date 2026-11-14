"""Turn the operator's demonstrations into replayable route traces.

The operator records demonstrations by playing; each demo-*.jsonl holds player samples. Those samples are split into
room runs, simplified to one point every few units and written as route files in the same JSONL format the bounded
player's `walk --route-file` replays (rows {"x": .., "z": ..}). A route that the operator walked is therefore a route
the bot can replay exactly - no wall-humping, no motion model guessing.

    python pso-learn-routes.py            # scan mandate/demo-*.jsonl, write routes/learned/*.jsonl + index.json

Segments break on room change, a time gap (> 3 s idle), or a jump (> 45 units, i.e. a warp), so a demonstration
that walks and later fights is stored as separate movement legs.
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib

MANDATE = pathlib.Path(r"D:\gBox\pso-ds\mandate")
ROUTES = pathlib.Path(r"D:\gBox\pso-ds\routes\learned")
SPACING = 3.0            # one stored point every ~3 world units
GAP_S = 3.0              # an input pause longer than this ends the leg
JUMP = 45.0              # a position jump this large is a warp, not walking
MIN_POINTS = 4
MIN_SPAN = 8.0


def load_track(path):
    track = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        player = row.get("player") or (row.get("sample") or {}).get("player") or {}
        if player.get("x") is None or player.get("z") is None:
            continue
        track.append({"t": row.get("t"), "x": float(player["x"]), "z": float(player["z"]),
                      "room": player.get("room")})
    return track


def split_runs(track):
    runs, current = [], []
    for point in track:
        if current:
            previous = current[-1]
            gap = (point["t"] - previous["t"]) if point.get("t") is not None and previous.get("t") is not None else 0.0
            jump = math.hypot(point["x"] - previous["x"], point["z"] - previous["z"])
            if point["room"] != previous["room"] or gap > GAP_S or jump > JUMP:
                runs.append(current)
                current = []
        current.append(point)
    if current:
        runs.append(current)
    return runs


def simplify(points, spacing=SPACING):
    kept = [points[0]]
    travelled = 0.0
    for point in points[1:]:
        travelled += math.hypot(point["x"] - kept[-1]["x"], point["z"] - kept[-1]["z"])
        if travelled >= spacing:
            kept.append(point)
            travelled = 0.0
    if (abs(kept[-1]["x"] - points[-1]["x"]) + abs(kept[-1]["z"] - points[-1]["z"])) > 0.5:
        kept.append(points[-1])
    return kept


def main(argv=None):
    parser = argparse.ArgumentParser(description="convert recorded demonstrations into replayable route traces")
    parser.add_argument("--min-span", type=float, default=MIN_SPAN)
    args = parser.parse_args(argv)
    ROUTES.mkdir(parents=True, exist_ok=True)
    index = []
    for demo in sorted(MANDATE.glob("demo-*.jsonl")):
        if demo.name.endswith("-route.jsonl"):
            continue
        track = load_track(demo)
        if not track:
            continue
        for number, run in enumerate(split_runs(track), start=1):
            span = sum(math.hypot(b["x"] - a["x"], b["z"] - a["z"]) for a, b in zip(run, run[1:]))
            if len(run) < MIN_POINTS or span < args.min_span:
                continue
            waypoints = simplify(run)
            if len(waypoints) < 2:
                continue
            rooms = [point["room"] for point in run]
            target = ROUTES / f"{demo.stem}-r{number:02d}-room{rooms[0]}.jsonl"
            target.write_text("".join(json.dumps({"x": round(p["x"], 2), "z": round(p["z"], 2)}) + "\n"
                                      for p in waypoints), encoding="utf-8")
            index.append({"file": str(target), "demo": str(demo), "room_start": rooms[0],
                          "room_end": rooms[-1], "rooms": sorted({r for r in rooms if isinstance(r, int)}),
                          "start": [round(run[0]["x"], 1), round(run[0]["z"], 1)],
                          "end": [round(run[-1]["x"], 1), round(run[-1]["z"], 1)],
                          "points": len(waypoints), "length": round(span, 1),
                          "seconds": round((run[-1]["t"] - run[0]["t"]), 1) if run[0].get("t") is not None else None})
    (ROUTES / "index.json").write_text(json.dumps({"schema": "pso/learned-routes/1", "spacing": SPACING,
                                                    "routes": index}, indent=1), encoding="utf-8")
    print(json.dumps({"routes": len(index), "index": str(ROUTES / "index.json")}))
    for row in index:
        print(json.dumps(row)[:240])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
