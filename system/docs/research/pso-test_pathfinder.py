"""Prove the room pathfinder works, and count how much map is already internalized.

`pso_coop_nav.RoomMap` is a bounded grid that learns blocked edges from `observe(before, after, intended, reliable)` and routes with A*
(`route`/`toward`). `Maps(root)` persists one per room key.

Two things this establishes, both without a running game:

1. **the pathfinder is correct** - a room with a wall across the middle, learned only from failed moves, must produce a route that goes around it, not through
   it, and must report no route when the goal is walled in;
2. **how much map exists on disk already** - the room maps the bot has internalised so far, which is the state of "analyzed, scanned and internalized".
"""
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import pso_coop_nav                                    # noqa: E402


def path_length(points):
    return sum(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 for a, b in zip(points, points[1:]))


if __name__ == "__main__":
    print("=== 1. pathfinder with a learned wall ===")
    with tempfile.TemporaryDirectory() as tmp:
        room = pso_coop_nav.RoomMap(path=pathlib.Path(tmp) / "room.json", size=12.0)
        print("  cell size:", room.size if hasattr(room, 'size') else '?')

        start, goal = (0.0, 0.0), (0.0, 60.0)
        print("  start", start, "goal", goal)

        direct = room.route(start, goal)
        print("  route on an open room:", "found" if direct else "none", "| points:", len(direct or []))

        # Learn a wall: every straight step across x ~ 0 at z between 20 and 40 is blocked.
        blocked = 0
        for z in range(20, 41, 2):
            before, after = (0.0, float(z)), (0.0, float(z))          # did not move
            room.observe(before, after, (0.0, 1.0), reliable=True)   # tried to go +z
            blocked += 1
        print(f"  learned {blocked} blocked steps across the middle")

        around = room.route(start, goal)
        print("  route after learning the wall:", "found" if around else "none", "| points:", len(around or []))
        if around:
            crossings = [p for p in around if abs(p[0]) < 1.0 and 20 <= p[1] <= 40]
            print("  points inside the wall span:", len(crossings), "(0 means it went around)")
            print("  path length:", round(path_length(around), 1))

        walled = room.route(start, (0.0, 21.0))
        print("  route to a point inside the wall:", "found" if walled else "none")

    print("\n=== 2. room maps already on disk ===")
    for candidate in (pathlib.Path(r"D:\gBox\pso-ds"), pathlib.Path(r"C:\_tools\gBox\system\gbox-data")):
        if not candidate.is_dir():
            continue
        found = list(candidate.rglob("*.json"))
        rooms = [p for p in found if "room" in p.name.lower() or "geometry" in p.name.lower() or "maps" in str(p.parent).lower()]
        print(f"  {candidate}: {len(rooms)} room/geometry files")
        for path in rooms[:6]:
            print(f"    {path.relative_to(candidate)}  ({path.stat().st_size} bytes)")
