"""Internalise every Episode I interior room from the disc, then path on the real Cave 1 grid.

`D:\\gBox\\pso-ds\\rel\\` holds 172 collision RELs - every room of every area: cave01_00..05, machine01/02, ruins01/02, ancient01_03, forest, boss, lobby,
jungle, seabed, space. `psomap.collision` decodes a REL to triangles and `walkable_cells` reduces them to a grid, so the whole map can be internalised from
the disc instead of walked.

Each room is written to `routes/` in the shape the earlier Forest files use - floor, file, triangle count, and the **blocked** cells (walls) plus a walkable
index - because blocked cells are what pathfinding needs and they are far smaller than the full walkable set.

Then `pso_coop_nav.RoomMap` routes between two points on the decoded Cave 1 grid, which is the "used for pathguiding the bot" half.
"""
import json
import pathlib
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import psomap                                          # noqa: E402

REL = pathlib.Path(r"D:\gBox\pso-ds\rel")
OUT = pathlib.Path(r"D:\gBox\pso-ds\routes")

# Episode I interiors: the areas the campaign actually runs through.
PREFIXES = ("cave01", "cave02", "cave03", "machine01", "machine02", "ruins01", "ruins02",
            "ancient01", "ancient02", "ancient03")


def decode(path):
    data = path.read_bytes()
    tris = psomap.collision(data, be=True)
    walkable, blocked = psomap.walkable_cells(tris, size=10.0, step=6.0, body=18.0)
    return tris, walkable, blocked


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    targets = sorted(p for p in REL.glob("*.rel")
                     if any(p.stem[len("map_"):].startswith(prefix) for prefix in PREFIXES))
    print(f"{len(targets)} rooms to internalise across {len(PREFIXES)} areas")

    started = time.time()
    written, total_tris, total_blocked = 0, 0, 0
    per_area = {}
    for path in targets:
        try:
            tris, walkable, blocked = decode(path)
        except Exception as exc:                                   # noqa: BLE001
            print(f"  {path.name:32s} FAILED {type(exc).__name__}: {str(exc)[:60]}")
            continue
        stem = path.stem[len("map_"):]
        area = stem.rstrip("c")
        area = area.rstrip("_")
        record = {
            "floor": area,
            "file": path.name,
            "method": "psomap.collision -> walkable_cells(size=10, step=6, body=18)",
            "triangles": len(tris),
            # walls are what the router avoids; walkable is its complement on a 10-unit grid
            "blocked": sorted([int(x), int(z)] for x, z in blocked),
            "walkable_count": len(walkable),
            "bounds": [[min(c[0] for c in walkable), min(c[1] for c in walkable)],
                       [max(c[0] for c in walkable), max(c[1] for c in walkable)]] if walkable else None,
        }
        (OUT / f"{path.stem}-mesh.json").write_text(json.dumps(record), encoding="utf-8")
        written += 1
        total_tris += len(tris)
        total_blocked += len(blocked)
        key = area.split("_")[0]
        per_area[key] = per_area.get(key, 0) + 1

    print(f"\nwrote {written} room maps in {time.time() - started:.1f}s")
    print(f"  {total_tris} triangles, {total_blocked} blocked cells total")
    print("  per area:", ", ".join(f"{k}={v}" for k, v in sorted(per_area.items())))

    # --- now path on a real decoded room ---
    print("\n=== routing on the decoded grid ===")
    from gbox import pso_coop_nav

    sample = OUT / "map_cave01_00c-mesh.json"
    if not sample.is_file():
        sample = next(OUT.glob("map_cave01*-mesh.json"), None)
    if sample is None:
        raise SystemExit("no cave map written")

    record = json.loads(sample.read_text(encoding="utf-8"))
    print("room:", record["floor"], "| blocked cells:", len(record["blocked"]),
          "| walkable:", record["walkable_count"])
    walls = {tuple(cell) for cell in record["blocked"]}
    (low, high) = record["bounds"]
    print("bounds:", low, "->", high)

    room = pso_coop_nav.RoomMap(path=OUT / "cave-route-test.json", size=10.0, walls=walls)
    start = (low[0] + 5, low[1] + 5)
    goal = (high[0] - 5, high[1] - 5)
    print("start", start, "-> goal", goal)
    route = room.route(start, goal)
    if route:
        print(f"route found: {len(route)} points, ends at {route[-1]}")
        inside = [p for p in route if (int(p[0] // 10), int(p[1] // 10)) in walls]
        print("route points inside a wall cell:", len(inside))
    else:
        print("no route on this pair")
