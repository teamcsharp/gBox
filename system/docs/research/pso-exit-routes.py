"""Extract the operator's approach path to each teleporter, from the run that ended in a floor change.

`learn_paths.py` records the floor changes (where the operator warped) but not the path that led there. This re-reads the demos, finds the
run that ended at a floor change, and saves the last `span` units of it as an approach route - the operator's own path into the teleporter.

Output: D:\\gBox\\pso-ds\\learned\\exit-routes.json with {floor: [[x,z], ...]} ready for follow_path-style driving.
"""
import json
import math
import sys
from pathlib import Path

DEMOS = Path(r"D:\gBox\pso-ds\demos")
OUT = Path(r"D:\gBox\pso-ds\learned\exit-routes.json")
SPAN = 260.0                                                        # how much of the approach to keep, in units


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
        if row.get("x") is not None and row.get("z") is not None:
            rows.append(row)
    rows.sort(key=lambda r: r.get("t", 0))
    return rows


def tail(points, span):
    """The last `span` units of a polyline."""
    kept = [points[-1]]
    total = 0.0
    for index in range(len(points) - 2, -1, -1):
        step = math.dist(points[index], points[index + 1])
        total += step
        kept.append(points[index])
        if total >= span:
            break
    kept.reverse()
    return kept


def simplify(points, step=12.0):
    out = [points[0]]
    for point in points[1:]:
        if math.dist(point, out[-1]) >= step:
            out.append(point)
    if out[-1] != points[-1]:
        out.append(points[-1])
    return out


def main():
    exits = {}
    detail = []
    for path in sorted(DEMOS.glob("demo-*/state.jsonl")):
        rows = read_session(path)
        for index in range(1, len(rows)):
            if rows[index].get("floor") == rows[index - 1].get("floor"):
                continue
            before_floor = rows[index - 1].get("floor")
            run = [(r["x"], r["z"]) for r in rows[:index] if r.get("floor") == before_floor]
            if len(run) < 2:
                continue
            approach = simplify(tail(run, SPAN))
            warp_at = (rows[index]["x"], rows[index]["z"])
            exits.setdefault(str(before_floor), []).append({
                "session": path.parent.name, "floor": before_floor,
                "warp_at": [round(warp_at[0], 1), round(warp_at[1], 1)],
                "approach": [[round(p[0], 1), round(p[1], 1)] for p in approach],
                "length": round(sum(math.dist(a, b) for a, b in zip(approach, approach[1:]))),
            })
            detail.append((path.parent.name, before_floor, warp_at, len(approach)))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(exits, indent=1), encoding="utf-8")
    print(f"exit approaches found: {len(detail)}")
    for session, floor, warp, count in detail:
        print(f"  {session}: floor {floor} -> warp at ({warp[0]:.1f},{warp[1]:.1f}) with {count} approach waypoints")
    for floor, routes in exits.items():
        print(f"floor {floor}: {len(routes)} exit routes")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
