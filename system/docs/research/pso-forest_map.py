"""A generic collision corridor, so the Forest map can be internalised the way the city's was.

`pso_coop_town.Corridor` works for the city because the city is one flat plaza, and it hardcodes that:

```
for i in range(max(72, ...), min(152, ...)):      # x confined to east town
    for j in range(max(2, ...),  min(116, ...)):  # z confined to east town
self.base = {p for p,h in heights.items() if min(h) >= -.1 and max(h) <= 1.1}   # flat floor only
```

Against the Forest those bounds and that height window select **nothing** - measured: 1455 and 1475 triangles decoded, **0 walkable cells**. The triangles are fine; the filter is wrong for terrain.

This builder keeps the parts that generalise and drops the parts that do not:

* **upward faces** (`normal.y > .6`) become walkable cells **at whatever height they are** - the Forest has hills;
* a cell is rejected when its heights **span more than `LEVEL_SPREAD`** (an upper and a lower floor overlapping in one cell is ambiguous, and picking the max is how a bot walks off a cliff);
* **steep faces** become walls;
* **3x3 erosion** keeps the conservative static margin the city version uses;
* no fixed cell ranges - the grid is derived from the geometry's own bounds.

Output: triangle count, walkable and safe cell counts, bounds, and the safe cells, written to `forest-maps.json` for the loop to path-guide with.
"""
import json
import math
import sys
from collections import defaultdict

sys.path.insert(0, r"C:\_tools\gBox\system")

DISC = r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz"
OUT = r"D:\gBox\pso-ds\forest-maps.json"
TARGETS = ("Scene/map_forest01c.rel", "Scene/map_forest02c.rel")
SIZE = 2.5
LEVEL_SPREAD = 3.0


def build(triangles, size=SIZE):
    """Return (walkable, safe, bounds) for any collision set - no fixed cell ranges, no fixed height."""
    from gbox.psomap import _inside, _height, TRIGGER_FLAG

    heights, walls = defaultdict(list), set()
    xs, zs = [], []
    for a, b, c, flags, normal in triangles:
        if flags & TRIGGER_FLAG:
            continue
        if normal[1] > 0.6:
            low_i = math.floor(min(a[0], b[0], c[0]) / size)
            high_i = math.floor(max(a[0], b[0], c[0]) / size) + 1
            low_j = math.floor(min(a[2], b[2], c[2]) / size)
            high_j = math.floor(max(a[2], b[2], c[2]) / size) + 1
            for i in range(low_i, high_i + 1):
                for j in range(low_j, high_j + 1):
                    x, z = (i + 0.5) * size, (j + 0.5) * size
                    if _inside(x, z, a, b, c):
                        heights[(i, j)].append(_height(x, z, a, b, c))
                        xs.append(i)
                        zs.append(j)
        elif abs(normal[1]) <= 0.6:
            for p, q in ((a, b), (b, c), (c, a)):
                steps = max(1, math.ceil(math.hypot(q[0] - p[0], q[2] - p[2]) / 0.5))
                for k in range(steps + 1):
                    u = k / steps
                    walls.add((math.floor((p[0] + (q[0] - p[0]) * u) / size),
                               math.floor((p[2] + (q[2] - p[2]) * u) / size)))

    walkable = {cell for cell, hs in heights.items()
                if hs and (max(hs) - min(hs)) <= LEVEL_SPREAD} - walls
    safe = {cell for cell in walkable
            if all((cell[0] + i, cell[1] + j) in walkable for i in (-1, 0, 1) for j in (-1, 0, 1))}
    bounds = (min(xs), max(xs), min(zs), max(zs)) if xs else None
    return walkable, safe, bounds


def main() -> int:
    from gbox.gcdisc import GCDisc
    from gbox.psomap import collision

    disc = GCDisc(DISC)
    report = {}
    try:
        for rel in TARGETS:
            print(f"\n=== {rel} ===")
            try:
                data = disc.read(rel)
                triangles = collision(data)
            except Exception as error:                             # noqa: BLE001
                print("  failed:", type(error).__name__, error)
                continue
            print(f"  size {len(data)} | triangles {len(triangles)}")
            walkable, safe, bounds = build(triangles)
            print(f"  walkable cells {len(walkable)} | safe cells {len(safe)}")
            if bounds:
                print(f"  cell bounds x {bounds[0]}..{bounds[1]}  z {bounds[2]}..{bounds[3]}")
            if safe:
                realm = [(c[0] * SIZE, c[1] * SIZE) for c in safe]
                print(f"  world x {min(p[0] for p in realm):.0f}..{max(p[0] for p in realm):.0f}"
                      f"  z {min(p[1] for p in realm):.0f}..{max(p[1] for p in realm):.0f}")
            report[rel] = {"triangles": len(triangles), "walkable": len(walkable), "safe": len(safe),
                           "cells": [list(cell) for cell in safe]}
    finally:
        disc.f.close()

    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(report, handle)
    print(f"\nwrote {OUT}")
    return 0 if any(row["safe"] for row in report.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
