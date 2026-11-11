"""Direct CP17 attempt: walk to the exit and record the floor until it changes.

`mastery_run --cp17` gave each leg only 30 s, which is not enough when the runner has to work around terrain. This keeps going: plan from the live
position, walk to the exit with a generous budget, and write a floor sample every few seconds - the accept signal is a sample where the floor
becomes 2 while the character is on foot.
"""
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import map_exit as ME                                              # noqa: E402
import nav_fast as NAV                                             # noqa: E402
import pso_input                                                   # noqa: E402
import run2 as RUN                                                 # noqa: E402
import session as S                                                # noqa: E402

FLOOR = 0x805D5FC0
EXIT = (133.0, -48.1)
SERIES = Path(r"D:\gBox\pso-ds\evidence\cp17-floor-series.jsonl")
LOG = r"D:\gBox\pso-ds\cp17_direct.log"


def log(line, event=None):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")
    if event:
        SERIES.parent.mkdir(parents=True, exist_ok=True)
        with SERIES.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"t": round(time.time(), 2), **event}) + "\n")


def floor():
    return int.from_bytes(S.read_memory(FLOOR, 4), "big")


start_floor = floor()
start = ME.read_pos()
log(f"CP17 direct: floor {start_floor}, player {tuple(round(v, 1) for v in start)}, exit {EXIT}")
log(f"distance {math.dist(start, EXIT):.0f} units", {"event": "cp17_start", "floor": start_floor,
                                                     "start": [round(start[0], 1), round(start[1], 1)]})
for attempt in range(4):
    point = ME.read_pos()
    if point is None:
        break
    route, raw, simple = NAV.plan(point, EXIT)
    log(f"  attempt {attempt}: plan {raw} cells -> {simple} legs from "
        f"({point[0]:.0f},{point[1]:.0f}), {math.dist(point, EXIT):.0f} units out")
    if not route:
        log("  no route")
        break
    for waypoint in route[1:] or route:
        arrived, elapsed, final, travelled, cycles = RUN.run_to(
            ME.read_pos, (waypoint[0], waypoint[1]), tolerance=10.0, budget=60.0)
        now_floor = floor()
        position = ME.read_pos()
        log(f"    leg -> ({waypoint[0]:.0f},{waypoint[1]:.0f}): arrived={arrived} {elapsed:.0f}s "
            f"{travelled:.0f} units, floor {now_floor}, at "
            f"{tuple(round(v) for v in position) if position else None}",
            {"event": "cp17_leg", "leg": [round(waypoint[0]), round(waypoint[1])], "arrived": arrived,
             "floor": now_floor, "travelled": round(travelled)})
        if now_floor != start_floor:
            log(f"CP17 ACCEPT: floor changed {start_floor} -> {now_floor} while walking",
                {"event": "cp17_ACCEPT", "from": start_floor, "to": now_floor,
                 "at": [round(position[0]), round(position[1])] if position else None})
            raise SystemExit(0)
    if ME.read_pos() and math.dist(ME.read_pos(), EXIT) <= 12:
        log("reached the exit point but the floor has not changed yet; waiting 3 s")
        time.sleep(3.0)
        if floor() != start_floor:
            log(f"CP17 ACCEPT: floor {start_floor} -> {floor()} at the exit",
                {"event": "cp17_ACCEPT", "from": start_floor, "to": floor()})
            raise SystemExit(0)
log("CP17: no floor change observed in this run", {"event": "cp17_failed", "floor": floor()})
raise SystemExit(2)
