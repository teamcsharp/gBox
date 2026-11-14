"""route - turn a recorded trace into a replayable route.

`pso-controller.py` and `pso-record.py` write a trace while the operator plays (`demo-*.jsonl`, one sample per line with
`x`, `z`, `room`, `keys`). The relay only writes its route JSON when it exits, so a trace is the durable form; this
converter makes any trace immediately replayable:

    python pso-route.py D:\\gBox\\pso-ds\\bounded\\demo-20261113-115318.jsonl
    python pso-bounded.py walk --route-file D:\\gBox\\pso-ds\\bounded\\demo-20261113-115318.jsonl

It reports the path length, the rooms crossed and the waypoint count, and writes `<trace>.route.json` next to the trace
with the same shape the relay writes. A trace with several stops is split at the stops: a segment starts wherever the
operator stood still for `--stop-seconds`, so one recording can hold several distinct routes (a key press here, a door
there) instead of one blended line.
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys


def simplify(points: list, spacing: float) -> list:
    kept: list = []
    for x, z in points:
        if not kept or math.dist(kept[-1], (x, z)) >= spacing:
            kept.append((round(x, 1), round(z, 1)))
    return kept


def segments(rows: list, stop_seconds: float, move_units: float) -> list:
    """Split a trace wherever the operator stood still long enough to call it a stop."""
    out, current, still_since = [], [], None
    for row in rows:
        point = (float(row["x"]), float(row["z"]))
        if current and math.dist((current[-1]["x"], current[-1]["z"]), point) < move_units:
            still_since = still_since if still_since is not None else float(row["t"])
            if float(row["t"]) - still_since >= stop_seconds and len(current) > 1:
                out.append(current)
                current, still_since = [row], None
                continue
        else:
            still_since = None
        current.append(row)
    if current:
        out.append(current)
    return [seg for seg in out if len(seg) > 1]


def length(points: list) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="convert a recorded trace into replayable routes")
    parser.add_argument("trace", help="demo-*.jsonl written by pso-controller.py or pso-record.py")
    parser.add_argument("--spacing", type=float, default=8.0)
    parser.add_argument("--stop-seconds", type=float, default=8.0,
                        help="standing still this long starts a new segment")
    parser.add_argument("--move-units", type=float, default=1.5)
    args = parser.parse_args(argv)

    path = pathlib.Path(args.trace)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [row for row in rows if row.get("x") is not None and row.get("t") is not None]
    if len(rows) < 2:
        print(f"{path.name}: {len(rows)} usable sample(s) - nothing to convert")
        return 2

    pieces = segments(rows, args.stop_seconds, args.move_units)
    routes = []
    for index, piece in enumerate(pieces):
        points = [(float(row["x"]), float(row["z"])) for row in piece]
        waypoints = simplify(points, args.spacing)
        routes.append({"index": index, "samples": len(piece),
                       "seconds": round(float(piece[-1]["t"]) - float(piece[0]["t"]), 1),
                       "path_length": round(length(points), 1),
                       "rooms": sorted({row["room"] for row in piece if row.get("room") is not None}),
                       "start": [round(points[0][0], 1), round(points[0][1], 1)],
                       "end": [round(points[-1][0], 1), round(points[-1][1], 1)],
                       "waypoints": waypoints})
    out = {"trace": path.name, "spacing": args.spacing, "segments": routes,
           "path_length": round(sum(route["path_length"] for route in routes), 1),
           "rooms": sorted({room for route in routes for room in route["rooms"]})}
    target = path.with_suffix(".route.json")
    target.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"{path.name}: {len(rows)} samples, {len(routes)} segment(s), {out['path_length']:.0f} units, "
          f"rooms {out['rooms']}")
    for route in routes:
        print(f"  segment {route['index']}: {route['samples']} samples, {route['path_length']:.0f} units, "
              f"{route['start']} -> {route['end']}, {len(route['waypoints'])} waypoints")
    print(f"wrote {target}")
    return 0 if routes else 3


if __name__ == "__main__":
    sys.exit(main())
