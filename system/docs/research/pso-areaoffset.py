"""areaoffset - find the world->file offset for the area the player is standing in.

`area-offsets.json` maps a collision file to a list of translations; the runner picks the one that lands the character
nearest walkable ground. The forest was solved by registration against recorded player steps ("the player's own
footsteps"), one area at a time. That method needs a trace of an area the bot has already walked.

This tool solves the same problem for an area **before** walking it, from the objects themselves: every placement in a
PSO room (doors, switches, containers, fences) sits on walkable ground, so the correct translation puts the visible
entities on walkable cells. It searches a coarse lattice, then refines it, and reports the score honestly (the fraction
of entities within one cell of walkable ground) instead of pretending a bad fit is a good one.

    python pso-areaoffset.py                        # current session, forest map
    python pso-areaoffset.py --map-map D:\\gBox\\pso-ds\\forest-map-v4.json --write
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import urllib.request

BASE = "http://127.0.0.1:18765"
TOKEN_PATH = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token")
OFFSETS = pathlib.Path(r"D:\gBox\pso-ds\area-offsets.json")


def log(message: str) -> None:
    print(str(message).encode("ascii", "replace").decode("ascii"), flush=True)


def token() -> str:
    return TOKEN_PATH.read_text(encoding="utf-8").strip()


def call(path, payload=None, method=None, timeout=20):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method or ("POST" if payload is not None else "GET"),
        headers={"authorization": "Bearer " + token(), "x-gbox-actor": "agent",
                 "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")


def live_session() -> str:
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    live = [row for row in rows if row.get("state") in ("running", "starting")]
    return live[0]["session_id"] if live else ""


def load_cells(path: pathlib.Path) -> tuple:
    grid = json.loads(path.read_text(encoding="utf-8"))
    name = next(iter(grid))
    return name, {tuple(cell) for cell in grid[name]["cells"]}


def score(cells: set, points: list, offset: tuple, tolerance: int = 1) -> float:
    dx, dz = offset
    hit = 0
    for x, z in points:
        gx, gz = round(x + dx), round(z + dz)
        if any((gx + i, gz + j) in cells
               for i in range(-tolerance, tolerance + 1) for j in range(-tolerance, tolerance + 1)):
            hit += 1
    return hit / max(len(points), 1)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="solve the area's world->file offset from its entities")
    parser.add_argument("--map-map", default=r"D:\gBox\pso-ds\forest-map-v4.json")
    parser.add_argument("--write", action="store_true", help="append the best offset to area-offsets.json")
    parser.add_argument("--min-score", type=float, default=0.5)
    parser.add_argument("--span", type=int, default=520)
    parser.add_argument("--step", type=int, default=10)
    args = parser.parse_args(argv)

    sid = live_session()
    if not sid:
        log("no live session")
        return 2
    state = call(f"/api/sessions/{sid}/rpc", {"op": "state", "args": {}})
    player = state.get("player") or {}
    room = player.get("room")
    points = [(float(e["x"]), float(e["z"])) for e in (state.get("entities") or [])
              if e.get("x") is not None and str(e.get("kind")) in ("gate", "object", "container")]
    if len(points) < 4:
        log(f"room {room}: only {len(points)} placed entities to register against")
        return 3
    name, cells = load_cells(pathlib.Path(args.map_map))
    log(f"room {room}: {len(points)} entities, {len(cells)} walkable cells in {name}")

    best = (-1.0, None)
    for dx in range(-args.span, args.span + 1, args.step):
        for dz in range(-args.span, args.span + 1, args.step):
            value = score(cells, points, (dx, dz))
            if value > best[0]:
                best = (value, (dx, dz))
    if best[1] is None:
        log("no candidate offsets")
        return 4
    # refine around the coarse winner
    bx, bz = best[1]
    for dx in range(bx - args.step, bx + args.step + 1, 2):
        for dz in range(bz - args.step, bz + args.step + 1, 2):
            value = score(cells, points, (dx, dz))
            if value > best[0]:
                best = (value, (dx, dz))
    log(f"best offset {best[1]} explains {100 * best[0]:.0f}% of the entities")
    if best[0] < args.min_score:
        log(f"score below --min-score {args.min_score:.0f}%: this area's geometry may not be in {name}")
        return 5
    if args.write:
        table = json.loads(OFFSETS.read_text(encoding="utf-8")) if OFFSETS.exists() else {}
        entry = table.setdefault(name, {"offsets": []})
        pair = [int(best[1][0]), int(best[1][1])]
        if pair not in entry["offsets"]:
            entry["offsets"].append(pair)
            OFFSETS.write_text(json.dumps(table, indent=1), encoding="utf-8")
            log(f"added {pair} for {name} (room {room})")
        else:
            log(f"{pair} already present for {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
