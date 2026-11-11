"""Learn the operator's demonstrated routes from the recorded sessions.

Every demo session's state.jsonl holds a timestamped trail (x, z, floor) at 2 Hz. This concatenates each session into a polyline per
floor, simplifies it (a point every ~15 units) and records where the floor changed - which is the moment the operator took a teleporter.

The result is the operator's own route through the level, which the bot can follow directly instead of planning its own: exactly
"internalise the demonstration and replicate it".
"""
import json
import math
import sys
from pathlib import Path

DEMOS = Path(r"D:\gBox\pso-ds\demos")
OUT_DIR = Path(r"D:\gBox\pso-ds\learned")
OUT = OUT_DIR / "paths.json"
SAMPLE_STEP = 15.0


def read_session(path):
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:                                        # noqa: BLE001
            continue
        if row.get("x") is None or row.get("z") is None:
            continue
        rows.append(row)
    rows.sort(key=lambda r: r.get("t", 0))
    return rows


def simplify(points, step=SAMPLE_STEP):
    if not points:
        return []
    out = [points[0]]
    for point in points[1:]:
        if math.dist(point["p"], out[-1]["p"]) >= step:
            out.append(point)
    if out[-1] is not points[-1]:
        out.append(points[-1])
    return out


def main():
    sessions = sorted(DEMOS.glob("demo-*/state.jsonl"))
    learned = {}
    transitions = []
    print(f"sessions: {len(sessions)}")
    for path in sessions:
        rows = read_session(path)
        if len(rows) < 2:
            continue
        floor = rows[0].get("floor")
        trail = []
        for row in rows:
            point = (row["x"], row["z"])
            if row.get("floor") != floor:
                if trail:
                    points = simplify(trail)
                    learned.setdefault(str(floor), []).append({
                        "session": path.parent.name, "floor": floor,
                        "points": [[round(p["p"][0], 1), round(p["p"][1], 1)] for p in points],
                        "t0": trail[0]["t"], "t1": trail[-1]["t"],
                        "distance": round(sum(math.dist(a["p"], b["p"]) for a, b in zip(trail, trail[1:]))),
                    })
                transitions.append({"session": path.parent.name, "from_floor": floor,
                                    "to_floor": row.get("floor"), "at": [round(row["x"], 1), round(row["z"], 1)],
                                    "t": row.get("t")})
                floor = row.get("floor")
                trail = []
            trail.append({"p": point, "t": row.get("t")})
        if trail:
            points = simplify(trail)
            learned.setdefault(str(floor), []).append({
                "session": path.parent.name, "floor": floor,
                "points": [[round(p["p"][0], 1), round(p["p"][1], 1)] for p in points],
                "t0": trail[0]["t"], "t1": trail[-1]["t"],
                "distance": round(sum(math.dist(a["p"], b["p"]) for a, b in zip(trail, trail[1:]))),
            })
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"paths": learned, "floor_changes": transitions}, indent=1), encoding="utf-8")
    for floor, paths in sorted(learned.items()):
        total = sum(p["distance"] for p in paths)
        print(f"floor {floor}: {len(paths)} demonstrated runs, {total} units, "
              f"{sum(len(p['points']) for p in paths)} waypoints")
        for path in paths:
            print(f"  {path['session']}: {path['distance']:5d} units, {len(path['points']):3d} waypoints, "
                  f"{round(path['t1'] - path['t0'])}s")
    print(f"floor changes (teleporters taken): {len(transitions)}")
    for change in transitions:
        print(f"  {change['session']}: floor {change['from_floor']} -> {change['to_floor']} "
              f"at {change['at']}")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
