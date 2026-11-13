"""forestmap - build Forest 1's routing grid from the owned disc, with a margin the character can actually use.

Why the stored grid had to be replaced. `forest-maps.json` has 90,986 safe cells but they are fragmented: at the
character's own position the nearest safe cell belonged to a component of size **1**, so A* returned `None` and the
follower silently fell back to a straight line - the orbit. Recomputed here:

    raw safe cells                100,280   one component of 99,823
    eroded by 2 cells (5 units)    87,265   route to the far side of Forest 1: 588 waypoints
    eroded by 4 cells (10 units)   74,815   route exists (609) but the character's corridor is gone from the grid
    eroded by 6 cells (15 units)   62,594   the map disconnects

10 units of margin therefore looks safer but is wrong: the nearest grid cell to the live character was 8.8-10.7 units
away, i.e. across a wall, and every route started on the other side of it. Five units keeps the character's corridor
in the grid (nearest cell 1.8 units) and still routes. That is what `--erode 2` produces, and with it a live walk went
232 units north and through a doorway (room 10 -> 11) where every previous attempt orbited in place.

    python pso-forestmap.py                       # writes D:\\gBox\\pso-ds\\forest-map-v4.json
    python pso-forestmap.py --erode 4 --out ...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox.gcdisc import GCDisc                    # noqa: E402
from gbox.psomap import collision, walkable_cells  # noqa: E402

DISC = pathlib.Path(r"D:\gBox\pso-ds\disc\pso.iso")
REL = "Scene/map_forest01c.rel"
REL_SIZE = 72096
REL_SHA = "0e7bc121a41e483e2c4d03bb031226461fecafb6c14ebfbeaab8ffe76ecfd2f5"
OUT = pathlib.Path(r"D:\gBox\pso-ds\forest-map-v4.json")
CELL = 2.5


def erode(cells: set, radius: int) -> set:
    """Keep only cells whose whole (2r+1)^2 neighbourhood is safe: a body-width margin."""
    if radius <= 0:
        return set(cells)
    out = set()
    for (x, z) in cells:
        for dx in range(-radius, radius + 1):
            for dz in range(-radius, radius + 1):
                if (x + dx, z + dz) not in cells:
                    break
            else:
                continue
            break
        else:
            out.add((x, z))
    return out


def decode(disc_path: pathlib.Path = DISC) -> tuple:
    disc = GCDisc(str(disc_path))
    try:
        if disc._r(0, 8) != b"GPOE8P\0\x02":
            raise SystemExit(f"{disc_path} is not the 3OE2 disc image")
        data = disc.read(REL)
    finally:
        disc.f.close()
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != REL_SIZE or digest != REL_SHA:
        raise SystemExit(f"{REL}: size {len(data)} sha {digest[:16]} does not match the pinned identity")
    return data, digest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="build Forest 1's routing grid")
    parser.add_argument("--erode", type=int, default=2, help="margin in cells (2 = 5 units, the usable one)")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)

    data, digest = decode()
    triangles = collision(data)
    floor, wall = walkable_cells(triangles, size=CELL)
    safe = erode(floor - wall, args.erode)
    grid = {REL: {"triangles": len(triangles), "walkable": len(floor), "safe": len(safe),
                  "cells": sorted(safe), "cell": CELL, "margin_cells": args.erode, "sha256": digest}}
    path = pathlib.Path(args.out)
    path.write_text(json.dumps(grid), encoding="utf-8")
    print(f"{REL}: {len(triangles)} triangles, {len(floor)} walkable, {len(floor - wall)} safe, "
          f"{len(safe)} after eroding {args.erode} cell(s) -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
