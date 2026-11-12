"""Find the area's world offset by putting 125 live entities on walkable floor.

A single player sample cannot constrain an offset - any point fits somewhere. But the entity table holds **125 objects spread across hundreds of units**, and every one
of them sits on or above floor. So the correct (layout, offset) is the one where the most entities land on **walkable** cells of the decoded collision grid; a wrong
offset buries them in rock.

This is a much stronger constraint than the earlier attempts: it does not vote on placements (which are diluted by shared rooms) and it does not rely on the player
standing still. Every entity is evidence.

Reports the best offset per layout, how sharply it peaks against neighbouring offsets, and whether the player also lands on floor there.
"""
import collections
import json
import math
import struct
import sys
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\.tmp")
sys.path.insert(0, r"C:\_tools\gBox\system")

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
TABLE, COUNT, POS = 0x8050D460, 256, 0x38
ROUTES = r"D:\gBox\pso-ds\routes"
SIZE = 10.0
LAYOUTS = [f"map_cave01_0{i}" for i in range(6)]


def rpc(sid, op, args, timeout=30):
    request = urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions/%s/rpc" % sid,
        data=json.dumps({"op": op, "args": args}).encode(), method="POST",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")


def read(sid, address, length):
    try:
        return bytes.fromhex(rpc(sid, "read_memory", {"address": address, "length": length}))
    except Exception:                                              # noqa: BLE001
        return b""


def walkable_cells(path):
    data = json.load(open(path, encoding="utf-8"))
    walls = {tuple(cell) for cell in data.get("blocked") or []}
    (x0, z0), (x1, z1) = data["bounds"]
    cells = set()
    for x in range(math.floor(x0 / SIZE), math.floor(x1 / SIZE) + 1):
        for z in range(math.floor(z0 / SIZE), math.floor(z1 / SIZE) + 1):
            if (x, z) not in walls:
                cells.add((x, z))
    return cells, data["bounds"]


if __name__ == "__main__":
    sessions = json.loads(urllib.request.urlopen(urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"}), timeout=20).read())
    sessions = sessions if isinstance(sessions, list) else (sessions.get("items") or [])
    sid = next(row["session_id"] for row in sessions if row.get("state") in ("running", "starting"))

    blob = read(sid, TABLE, COUNT * 4)
    pointers = [p for p in struct.unpack(">%dI" % COUNT, blob) if 0x80000000 <= p < 0x81800000]
    entities = []
    for pointer in pointers:
        body = read(sid, pointer + POS, 12)
        if len(body) == 12:
            x, y, z = struct.unpack(">fff", body)
            if all(abs(v) < 100000 for v in (x, y, z)):
                entities.append((x, z))
    player = (rpc(sid, "state", {"player_only": True}) or {}).get("player") or {}
    print(f"entities: {len(entities)}  player ({player.get('x', 0):.0f}, {player.get('z', 0):.0f})")

    px = sum(e[0] for e in entities) / len(entities)
    pz = sum(e[1] for e in entities) / len(entities)
    print(f"entity centroid ({px:.0f}, {pz:.0f})")

    results = []
    for layout in LAYOUTS:
        path = f"{ROUTES}\\{layout}c-mesh.json"
        try:
            cells, bounds = walkable_cells(path)
        except Exception as exc:                                   # noqa: BLE001
            print(f"  {layout}: {type(exc).__name__}")
            continue
        (x0, z0), (x1, z1) = bounds
        rx, rz = (x0 + x1) / 2, (z0 + z1) / 2

        best = (0, 0.0, 0.0)
        scored = []
        for dx in range(-900, 901, 30):
            for dz in range(-900, 901, 30):
                ox, oz = dx, dz
                hits = 0
                for (ex, ez) in entities:
                    cell = (math.floor((ex - ox) / SIZE), math.floor((ez - oz) / SIZE))
                    if cell in cells:
                        hits += 1
                scored.append((hits, ox, oz))
                if hits > best[0]:
                    best = (hits, ox, oz)
        scored.sort(reverse=True)
        top = scored[0]
        runner = scored[1] if len(scored) > 1 else (0, 0, 0)
        player_cell = (math.floor((player["x"] - top[1]) / SIZE), math.floor((player["z"] - top[2]) / SIZE))
        print(f"  {layout:16s} best {top[0]:3d}/{len(entities)} on floor at ({top[1]}, {top[2]})  "
              f"runner-up {runner[0]:3d} at ({runner[1]}, {runner[2]})  player on floor: {player_cell in cells}")
        results.append((top[0], layout, top[1], top[2], runner[0], player_cell in cells))

    results.sort(reverse=True)
    print("\nranked:")
    for hits, layout, ox, oz, runner, player_ok in results:
        gap = hits - runner
        print(f"  {layout:16s} {hits:3d} entities  offset ({ox:5.0f}, {oz:5.0f})  "
              f"lead over runner-up {gap:+3d}  player on floor {player_ok}")

    if results:
        hits, layout, ox, oz, runner, player_ok = results[0]
        print(f"\nVERDICT: {layout} explains {hits} of {len(entities)} entities at offset ({ox}, {oz})")
        if hits < len(entities) * 0.6:
            print("  but fewer than 60% fit, so this is not a confident transform")
        elif hits - runner < 5:
            print("  and the runner-up is close, so the offset is not sharply determined")
