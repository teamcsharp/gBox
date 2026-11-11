"""Follow the operator's demonstrated route.

`learn_paths.py` turns the recorded sessions into polylines per floor (D:\\gBox\\pso-ds\\learned\\paths.json), and the floor-change events
record where the operator took a teleporter - measured this round at (536.4,-566.4) and (133.0,-48.1) on Forest 1.

This joins the loop the operator asked for: take their demonstrated path for the current floor, start from the nearest waypoint, and drive
through the rest with the fast runner. No planning, no probing of unexplored space - the bot walks where the operator walked.

Modes:
  python follow_path.py --show        report the chosen route and where it enters (no input)
  python follow_path.py               walk it
"""
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import map_exit as ME                                              # noqa: E402
import pso_input                                                   # noqa: E402
import run2 as RUN                                                 # noqa: E402
import session as S                                                # noqa: E402

PATHS = Path(r"D:\gBox\pso-ds\learned\paths.json")
FLOOR = 0x805D5FC0
LOG = r"D:\gBox\pso-ds\follow_path.log"


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def floor():
    return int.from_bytes(S.read_memory(FLOOR, 4), "big")


def load():
    try:
        return json.loads(PATHS.read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return {"paths": {}, "floor_changes": []}


def choose_route(data, current_floor, position):
    """The longest demonstrated run on this floor, entered at the closest of its waypoints."""
    runs = data.get("paths", {}).get(str(current_floor)) or []
    if not runs:
        return None, None
    best = max(runs, key=lambda run: run.get("distance", 0))
    points = [tuple(p) for p in best["points"]]
    start_index = min(range(len(points)), key=lambda i: math.dist(points[i], position))
    return best, (points, start_index)


def main(show_only=False, tolerance=14.0):
    data = load()
    point = ME.read_pos()
    current = floor()
    if point is None:
        log("no player position")
        return 2
    route, entry = choose_route(data, current, point)
    if route is None:
        log(f"no demonstrated route for floor {current}")
        return 2
    points, start_index = entry
    remaining = points[start_index:]
    log(f"floor {current}: following {route['session']} ({route['distance']} units, "
        f"{len(points)} waypoints), entering at waypoint {start_index} "
        f"({points[start_index][0]:.0f},{points[start_index][1]:.0f})")
    if show_only:
        for index, waypoint in enumerate(remaining[:12]):
            log(f"  {index}: ({waypoint[0]:7.1f},{waypoint[1]:7.1f})")
        changes = [c for c in data.get("floor_changes", []) if c.get("from_floor") == current]
        for change in changes:
            log(f"  teleporter seen on this floor at {change['at']}")
        return 0
    started = time.time()
    travelled = 0.0
    for index, waypoint in enumerate(remaining):
        if floor() != current:
            log(f"  floor changed to {floor()} - route done")
            break
        before = ME.read_pos()
        arrived, elapsed, final, moved, cycles = RUN.run_to(ME.read_pos, waypoint, tolerance=tolerance)
        travelled += moved
        log(f"  waypoint {start_index + index + 1}/{len(points)} -> "
            f"({waypoint[0]:.0f},{waypoint[1]:.0f}): arrived={arrived} {elapsed:.1f}s {moved:.0f} units "
            f"({None if final is None else round(final)} left)")
        if not arrived and before is not None and ME.read_pos() is not None:
            if math.dist(before, ME.read_pos()) < 3.0:
                log("  stuck on a waypoint; skipping it")
    elapsed = time.time() - started
    speed = travelled / max(0.001, elapsed)
    log(f"done: {travelled:.0f} units in {elapsed:.1f}s ({speed:.1f} units/s), floor now {floor()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(show_only="--show" in sys.argv))
