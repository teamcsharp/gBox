"""citymap - decode the Pioneer 2 collision mesh into the same safe-cell grid the Forest route uses.

The city walk failed with the character bouncing between (105,154) and (131,160) while the warp door sat at
(254, 25): the plaza railing is between them and the tap controller has no map. Only the Forest grids were kept in
`forest-maps.json`; this builds the city's from the owned disc, with the same keys (`triangles`, `walkable`, `safe`,
`cells`) so `forest_route.MapRouter` can route it unchanged.

    python pso-citymap.py                       # write D:\\gBox\\pso-ds\\city-map.json
    python pso-citymap.py --route 105,160 254,25

The REL identity is pinned (size and sha256) before parsing, and the route is printed before anything walks it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox.gcdisc import GCDisc                 # noqa: E402
from gbox.psomap import collision, walkable_cells   # noqa: E402

DISC = pathlib.Path(r"D:\gBox\pso-ds\disc\pso.iso")
REL = "Scene/map_city00_00c.rel"
REL_SIZE = 70144
REL_SHA = "6d5f5d5d0ff9c18958d1ab577e5be9e6f83c66808537b085ca4c9d2cd97535ec"
OUT = pathlib.Path(r"D:\gBox\pso-ds\city-map.json")
# The Forest grid - and therefore `forest_route.MapRouter` - uses a 2.5-unit cell, so the city grid must too or the
# router's world->cell conversion is wrong (measured: a correct 10-unit grid routed "none" through a MapRouter that
# assumed 2.5, while the same component obviously contained both endpoints at 10 units).
CELL = 2.5


def decode(disc_path: pathlib.Path = DISC) -> dict:
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
    triangles = collision(data)
    floor, wall = walkable_cells(triangles, size=CELL)
    safe = sorted(floor - wall)
    return {"triangles": len(triangles), "walkable": sorted(floor), "safe": len(safe), "cells": safe,
            "source": REL, "sha256": digest, "cell": CELL}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="decode the city collision grid")
    parser.add_argument("--route", nargs=2, metavar=("X,Z", "X,Z"), default=None)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)

    grid = decode()
    print(f"{REL}: {grid['triangles']} triangles, {len(grid['walkable'])} walkable cells, {grid['safe']} safe")
    path = pathlib.Path(args.out)
    path.write_text(json.dumps({REL: grid}, indent=0), encoding="utf-8")
    print(f"wrote {path}")

    if args.route:
        sys.path.insert(0, r"C:\_tools\gBox\.tmp")
        from forest_route import MapRouter                       # the A* the Forest walk already used
        start = tuple(float(value) for value in args.route[0].split(","))
        goal = tuple(float(value) for value in args.route[1].split(","))
        router = MapRouter(grid["cells"])
        route = router.route(start, goal, limit=400000)
        print(f"route {start} -> {goal}: {len(route) if route else 'none'}")
        if route:
            for index, point in enumerate(route[:: max(1, len(route) // 12)]):
                print(f"  waypoint {index}: ({point[0]}, {point[1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
