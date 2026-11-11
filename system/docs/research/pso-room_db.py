"""Build the room database: every room of every floor, with what it contains and what it connects to.

The operator wants the bot to know these maps cold, and notes that a level has at most about three layout variants - so a room must be recorded
against the LAYOUT it belongs to, not just the floor number.

Each room record combines everything already measured:

  * geometry: centre, bounds, cell count and the cell list (from the mesh segmentation);
  * heights: min/max/median floor height in the room (from the validated height table);
  * contents: the placed set objects inside it, by class and count (from the set decode);
  * connections: which other rooms it shares a doorway with (from the boundary cells);
  * observations: whether the bot or the operator has been seen in it, and when.

Layout identity is a hash of the room graph plus the set file, so a different variant of the same floor gets its own entry instead of corrupting the
old one.

Output: D:\\gBox\\pso-ds\\rooms\\floor<N>-<signature>.json plus a merged index.
"""
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import nav_fast as NAV                                             # noqa: E402

ROUTES = Path(r"D:\gBox\pso-ds\routes")
OUT_DIR = Path(r"D:\gBox\pso-ds\rooms")
INDEX = OUT_DIR / "index.json"
OBSERVED = Path(r"D:\gBox\pso-ds\selfplay2-state.json")


def load(name, default=None):
    try:
        return json.loads((ROUTES / name).read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return default if default is not None else {}


def heights(floor):
    raw = load(f"forest{floor}-heights.json", {})
    table = {}
    for key, value in raw.items():
        try:
            x, z = key.split(",")
            table[(int(x), int(z))] = float(value)
        except Exception:                                        # noqa: BLE001
            continue
    return table


def objects(floor):
    raw = load("set-objects-floors.json", {})
    block = raw.get(str(floor)) or {}
    return block.get("objects") or []


def signature(rooms, floor):
    payload = json.dumps(rooms, sort_keys=True).encode() + str(floor).encode()
    set_path = ROUTES / "set-objects-floors.json"
    if set_path.exists():
        payload += set_path.read_bytes()
    return hashlib.sha256(payload).hexdigest()[:12]


def build(floor):
    graph = load(f"forest{floor}-rooms-mesh.json", {})
    rooms = graph.get("rooms") or []
    doors = graph.get("doors") or []
    height_table = heights(floor)
    placed = objects(floor)
    if not rooms:
        return None

    # which rooms each boundary cell joins
    links = {}
    for door in doors:
        pair = door.get("rooms") or []
        for room in pair:
            others = [other for other in pair if other != room]
            links.setdefault(room, set()).update(others)

    records = []
    for room in rooms:
        cells = [tuple(cell) for cell in room.get("cell_list") or []]
        index_of = lambda cell: (int(math.floor(cell[0] / 10.0)), int(math.floor(cell[1] / 10.0)))
        cell_heights = [height_table[index_of(cell)] for cell in cells if index_of(cell) in height_table]
        ys = sorted(cell_heights)
        in_room = [obj for obj in placed
                   if any(abs(obj["x"] - cell[0]) <= 5 and abs(obj["z"] - cell[1]) <= 5 for cell in cells)]
        records.append({
            "room": room["room"],
            "centre": room["centre"],
            "bounds": room.get("bounds"),
            "cells": room.get("cells"),
            "cell_list": cells,
            "height": {"min": round(ys[0], 1) if ys else None,
                       "max": round(ys[-1], 1) if ys else None,
                       "median": round(ys[len(ys) // 2], 1) if ys else None},
            "objects": dict(Counter(obj["class"] for obj in in_room)),
            "object_count": len(in_room),
            "connects_to": sorted(links.get(room["room"], [])),
        })

    observed = []
    try:
        observed = json.loads(OBSERVED.read_text(encoding="utf-8")).get("visited") or []
    except Exception:                                            # noqa: BLE001
        pass

    sig = signature(rooms, floor)
    payload = {"floor": floor, "signature": sig, "rooms": records,
               "doorway_cells": len(doors), "visited_by_bot": observed,
               "source": f"forest{floor}-rooms-mesh.json"}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"floor{floor}-{sig}.json"
    out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return payload, out


def main():
    index = {}
    for floor in (1, 2, 3):
        built = build(floor)
        if not built:
            print(f"floor {floor}: no room graph")
            continue
        payload, out = built
        index[str(floor)] = {"signature": payload["signature"], "rooms": len(payload["rooms"]),
                             "file": out.name, "doorways": payload["doorway_cells"]}
        print(f"floor {floor}: {len(payload['rooms'])} rooms, {payload['doorway_cells']} doorway cells "
              f"-> {out.name}")
        for room in payload["rooms"]:
            connections = room["connects_to"]
            heights_text = (f"{room['height']['min']:.1f}..{room['height']['max']:.1f}"
                            if room["height"]["min"] is not None else "?")
            print(f"   room {room['room']:2d}  {room['cells']:5d} cells  heights {heights_text:<16} "
                  f"objects {room['object_count']:3d}  connects {connections}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(index, indent=1), encoding="utf-8")
    print("\nwrote", INDEX)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
