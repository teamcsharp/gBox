"""Dump the LIVE loaded collision grid of the current field floor as a router map file.

This is the RAM half of the ROM/RAM -> 2D map bridge: the game has already parsed its own collision REL into
memory (root, allocation, mesh table), so reading that allocation and re-parsing it with the same
gbox.psomap loader that reads the disc files gives the exact triangles the character is walking on right now -
no layout guessing, no disc-file match. `gbox.pso_coop_geometry` already does this for the co-op lane but its
Provider refuses anything outside town/Forest and requires two players; this tool calls the same internals for
one player on any floor.

The output is the format `pso-bounded.py walk/play --map <file> --map-name <key>` consumes (2.5-unit cells, the
forest_route.MapRouter grid), so the existing route-following code walks the live floor.

    python pso-live-map.py            # writes routes/live-map-<floor>-<digest>.json, prints the key
    python pso-live-map.py --json     # same, machine-readable summary on one line
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\system")
from gbox import pso_coop_geometry as geom  # noqa: E402

BASE = "http://127.0.0.1:18765"
TOKEN = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token").read_text(encoding="utf-8").strip()
OUT_DIR = pathlib.Path(r"D:\gBox\pso-ds\routes")
CHUNK = 65536
CELL = 2.5                                     # forest_route.MapRouter.SIZE; keep the router unchanged


class Session:
    def __init__(self):
        rows = self.call("/api/sessions")
        rows = rows if isinstance(rows, list) else (rows.get("items") or [])
        live = [row for row in rows if row.get("state") in ("running", "starting") and row.get("adapter") == "dolphin"]
        if not live:
            raise SystemExit("no live dolphin session")
        self.sid = live[0]["session_id"]

    def call(self, path, payload=None, method="GET", timeout=90):
        request = urllib.request.Request(
            BASE + path,
            data=json.dumps(payload).encode() if payload is not None else None, method=method,
            headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                     "content-type": "application/json"})
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")

    def rpc(self, op, **args):
        return self.call(f"/api/sessions/{self.sid}/rpc", {"op": op, "args": args}, "POST")

    def read_memory(self, address, length):
        raw = self.rpc("read_memory", address=int(address), length=int(length))
        if not isinstance(raw, str):
            raise OSError(f"read failed at {address:#x}")
        return bytes.fromhex(raw)


def read_blob(session, base, size):
    chunks = [session.read_memory(base + offset, min(CHUNK, size - offset)) for offset in range(0, size, CHUNK)]
    blob = b"".join(chunks)
    if len(blob) != size:
        raise RuntimeError(f"short collision blob: {len(blob)} != {size}")
    return blob


def live_grid(session):
    """(floor, triangles_digest, grid, player) for the loaded floor; raises when geometry is unavailable."""
    player = (session.rpc("state") or {}).get("player") or {}
    if not player.get("ptr"):
        raise RuntimeError("no live player")
    root, base, size, manager = geom._roots(session)
    if not 0 < size <= 8 * 1024 * 1024:
        raise RuntimeError(f"collision allocation out of budget: {size}")
    table = geom._table(session, manager)
    blob = read_blob(session, base, size)
    triangles, digest = geom.parse_loaded(base, blob, table)
    if not triangles:
        raise RuntimeError("no collision triangles parsed")
    atlas = geom.Atlas(triangles)
    view = atlas.project(player)
    margin = None
    if not view:
        margin = geom.MarginViews(atlas)
        mview = margin._view(player)
        if mview and mview.get("safe"):
            rows = [[*cell, round(height, 4)] for cell, height in sorted(mview["safe"].items())]
            view = {"geometry_layer": mview.get("geometry_layer"),
                    "collision_grid": {"size": atlas.size, "floor": [row[:2] for row in rows], "walls": [],
                                       "heights": rows, "max_step": .75, "max_slope": .75, "recovery": True}}
    if not view:
        raise RuntimeError("player could not be projected onto the loaded collision")
    grid = view["collision_grid"]
    floor = int.from_bytes(session.read_memory(0x805D5FC0, 4), "big")
    return floor, digest, view.get("geometry_layer"), grid, player, len(triangles)


def expand_cells(grid):
    """Expand the grid's own cell size into the 2.5-unit cells forest_route.MapRouter expects."""
    size = float(grid.get("size") or CELL)
    factor = max(1, int(round(size / CELL)))
    cells = set()
    for cell in grid.get("floor") or []:
        x, z = int(cell[0]), int(cell[1])
        for dx in range(factor):
            for dz in range(factor):
                cells.add((x * factor + dx, z * factor + dz))
    return sorted(cells), size, factor


def main(argv=None):
    parser = argparse.ArgumentParser(description="dump the live floor collision grid as a route map")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=pathlib.Path)
    args = parser.parse_args(argv)
    session = Session()
    floor, digest, layer, grid, player, triangles = live_grid(session)
    cells, size, factor = expand_cells(grid)
    if not cells:
        raise SystemExit("live grid has no walkable cells")
    key = f"live-floor{floor}-{digest[:12]}"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = args.out or OUT_DIR / f"live-map-floor{floor}-{digest[:12]}.json"
    payload = {key: {"triangles": triangles, "walkable": len(cells), "safe": len(cells),
                     "cells": [[x, z] for x, z in cells],
                     "geometry_layer": layer, "digest": digest, "grid_size": size,
                     "recovery": bool(grid.get("recovery")),
                     "player": {k: player.get(k) for k in ("x", "y", "z", "room")}}}
    target.write_text(json.dumps(payload), encoding="utf-8")
    summary = {"map": str(target), "key": key, "cells": len(cells), "triangles": triangles,
               "grid_size": size, "factor": factor, "digest": digest, "floor": floor,
               "room": player.get("room"), "player": [player.get("x"), player.get("z")]}
    if args.json:
        print(json.dumps(summary))
    else:
        print(f"map {target}")
        print(f"key {key} | floor {floor} | triangles {triangles} | grid {size} -> {len(cells)} cells "
              f"(x{factor}) | room {player.get('room')} at ({player.get('x'):.0f},{player.get('z'):.0f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
