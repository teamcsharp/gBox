"""Assign every set object to the room it stands in, for both forest floors.

The editor's first need after a room map is "what is in this room": the placement set holds the static objects (sensors, rocks, sound
sources, symbol-chat collision) and the mesh segmentation holds the rooms, so an object belongs to the room whose footprint contains it -
its nearest room cell, with the distance recorded so a misfit is visible instead of silent.

Output: `routes/room-contents.json`: per floor, per room, the objects it holds (class, position, distance to the room's nearest cell), plus
the objects that fall outside every room (which usually means a placement in an unused area).

Usage: python room_contents.py
"""
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROUTES = Path(r"D:\gBox\pso-ds\routes")


def rooms_for(floor):
    path = ROUTES / f"forest{floor}-rooms-mesh.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    objects = json.loads((ROUTES / "set-objects-floors.json").read_text(encoding="utf-8"))
    out = {}
    for floor_key, block in objects.items():
        graph = rooms_for(int(floor_key))
        if not graph:
            print(f"floor {floor_key}: no room graph")
            continue
        rooms = graph["rooms"]
        assignment = []
        for obj in block["objects"]:
            point = (obj["x"], obj["z"])
            best = (1e9, None)
            for room in rooms:
                for cx, cz in room["cell_list"]:
                    distance = math.dist(point, (cx, cz))
                    if distance < best[0]:
                        best = (distance, room["room"])
            assignment.append({"class": obj["class"], "x": obj["x"], "z": obj["z"],
                               "room": best[1], "distance": round(best[0], 1)})
        per_room = {}
        for row in assignment:
            if row["room"] is None:
                continue
            per_room.setdefault(str(row["room"]), []).append(row)
        outside = [row for row in assignment if row["room"] is None or row["distance"] > 60]
        out[floor_key] = {"set": block["set"], "rooms": {key: {"count": len(rows),
                                                               "classes": dict(Counter(r["class"] for r in rows)),
                                                               "objects": rows}
                                                          for key, rows in per_room.items()},
                          "outside_rooms": len(outside),
                          "total_objects": len(assignment)}
        print(f"\nfloor {floor_key} ({block['set']}): {len(assignment)} objects")
        for room in rooms:
            key = str(room["room"])
            rows = per_room.get(key, [])
            top = ", ".join(f"{name} x{count}" for name, count in Counter(r["class"] for r in rows).most_common(3))
            print(f"  room {room['room']:2d} ({room['cells']:5d} cells, centre "
                  f"({room['centre'][0]:7.1f},{room['centre'][1]:7.1f})): {len(rows):3d} objects  {top}")
        print(f"  objects outside every room (or > 60 units from one): {len(outside)} of {len(assignment)}")
    target = ROUTES / "room-contents.json"
    target.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("\nwrote", target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
