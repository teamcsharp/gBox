"""Fit each decoded room's world offset, so live positions can be used against its walls.

The player stands at (-188, -729) but no decoded room's bounds contain that point - the nearest centroid is 621 units away. PSO translates a room's collision
geometry into place when it loads, so `c.rel` coordinates are room-local and the live position is in room space. Path-guiding needs the offset.

The fit is empirical and falsifiable: sample the player while it moves, then for each room look for the translation that puts **the fewest sampled positions
inside a wall**. A room whose walls the player never stands in, under one consistent offset, is the room; a wrong room leaves samples buried in rock.

Offsets are searched in a coarse ring around the alignment of the two centroids, then refined.
"""
import json
import math
import pathlib
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
ROUTES = pathlib.Path(r"D:\gBox\pso-ds\routes")
SIZE = 10.0
SAMPLES = 40


def rpc(sid, op, args):
    request = urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions/%s/rpc" % sid,
        data=json.dumps({"op": op, "args": args}).encode(), method="POST",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=30).read() or b"null")


def load_room(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    walls = {tuple(cell) for cell in data.get("blocked") or []}
    bounds = data.get("bounds")
    return data.get("floor"), walls, bounds


if __name__ == "__main__":
    sessions = json.loads(urllib.request.urlopen(urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"}), timeout=20).read())
    sessions = sessions if isinstance(sessions, list) else (sessions.get("items") or [])
    sid = next(row["session_id"] for row in sessions if row.get("state") in ("running", "starting"))

    points = []
    print(f"sampling {SAMPLES} player positions...")
    for _ in range(SAMPLES):
        player = (rpc(sid, "state", {"player_only": True}) or {}).get("player") or {}
        if "x" in player and "z" in player:
            points.append((player["x"], player["z"]))
        time.sleep(0.25)
    unique = sorted(set(points))
    print(f"  {len(points)} samples, {len(unique)} distinct")
    if not unique:
        raise SystemExit("no positions")
    px = sum(p[0] for p in unique) / len(unique)
    pz = sum(p[1] for p in unique) / len(unique)
    print(f"  centroid ({px:.0f}, {pz:.0f})  spread "
          f"{max(p[0] for p in unique) - min(p[0] for p in unique):.0f} x "
          f"{max(p[1] for p in unique) - min(p[1] for p in unique):.0f}")

    results = []
    for path in sorted(ROUTES.glob("map_*c-mesh.json")):
        try:
            floor, walls, bounds = load_room(path)
        except Exception:                                          # noqa: BLE001
            continue
        if not walls or not bounds:
            continue
        (x0, z0), (x1, z1) = bounds
        rx, rz = (x0 + x1) / 2, (z0 + z1) / 2
        base_x, base_z = px - rx, pz - rz

        best = None
        for dx in range(-120, 121, 30):
            for dz in range(-120, 121, 30):
                ox, oz = base_x + dx, base_z + dz
                hits = sum(1 for (x, z) in unique
                           if (math.floor((x - ox) / SIZE), math.floor((z - oz) / SIZE)) in walls)
                if best is None or hits < best[0]:
                    best = (hits, ox, oz)
        results.append((best[0], path.stem, floor, best[1], best[2], len(unique)))

    results.sort()
    print("\nbest fits (wall hits out of samples, then offset):")
    for hits, stem, floor, ox, oz, total in results[:8]:
        print(f"  {hits:3d}/{total} walls  {stem:34s} floor={floor:12s} offset=({ox:.0f}, {oz:.0f})")

    if results and results[0][0] == 0:
        print(f"\nVERDICT: {results[0][1]} fits with zero wall hits - the player is in that room, "
              f"offset ({results[0][3]:.0f}, {results[0][4]:.0f})")
    else:
        best = results[0]
        print(f"\nno clean fit; best was {best[1]} with {best[0]}/{best[5]} samples inside a wall")
