"""Route certificate for CP17: prove the planned walk to Forest 1's exit is actually walkable, leg by leg.

The contract's accept test needs the floor to change by walking. Before walking it, this proves the geometry is sound:

  * every leg is a straight line whose samples all fall in free collision cells (line_free over the real cell grid);
  * the final waypoint reaches the exit the operator used, within a cell or two;
  * the legs are listed with their lengths so the expected run time at the measured 27 units/s can be stated.

If any leg fails the line test the certificate fails: that would mean the planner's string-pulling produced a shortcut across a wall.
"""
import json
import math
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import nav_fast as NAV

START = (-57.0, 197.5)                                             # the operator's floor-1 run start
EXIT = (133.0, -48.1)                                              # the Forest 1 -> Forest 2 warp from their play
SPEED = 27.0                                                       # measured runner throughput, units/s
OUT = r"D:\gBox\pso-ds\cp17-route-certificate.txt"


def main():
    free = NAV.cells(1)
    print(f"floor 1 free cells: {len(free)}")
    route, raw_count, simple_count = NAV.plan(START, EXIT)
    print(f"plan: {raw_count} cell waypoints -> {simple_count} legs")
    if not route:
        print("NO ROUTE: the exit is not reachable from the start in the free-cell graph")
        return 2
    lines = [f"start {START} exit {EXIT}",
             f"free cells {len(free)}, raw waypoints {raw_count}, legs {len(route)}"]
    total = 0.0
    failures = 0
    for index in range(1, len(route)):
        a, b = tuple(route[index - 1]), tuple(route[index])
        length = math.dist(a, b)
        clear = NAV.line_free(free, a, b)
        total += length
        status = "clear" if clear else "BLOCKED"
        if not clear:
            failures += 1
        line = (f"  leg {index:2d}: ({a[0]:7.1f},{a[1]:7.1f}) -> ({b[0]:7.1f},{b[1]:7.1f})  "
                f"{length:7.1f} units  {status}")
        print(line)
        lines.append(line)
    last = tuple(route[-1])
    reached = math.dist(last, EXIT)
    seconds = total / SPEED
    summary = (f"total {total:.0f} units, {len(route) - 1} legs, {failures} blocked legs, "
               f"final waypoint {reached:.1f} units from the exit, expected {seconds:.0f} s at {SPEED:.0f} units/s")
    print(summary)
    lines.append(summary)
    lines.append("CERTIFICATE " + ("PASS" if failures == 0 and reached <= 20.0 else "FAIL"))
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    print("wrote", OUT)
    return 0 if failures == 0 and reached <= 20.0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
