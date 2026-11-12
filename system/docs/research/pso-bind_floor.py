"""Bind the live session to a decoded area and its layouts, using the game's own floor table.

`pso_floor_map` pins floor -> area + layout names from the executable's table at 0x804C8FC0 (`FUN_80207E88`), so a floor id alone names the files. The live floor
id is at 0x805D5FC0.

That matters because the collision files are room-local while the player's position is in room space: to path-guide, the bot needs to know **which layout is
loaded**, not just which area. This resolves the floor, lists the candidate layouts, and reports the player's position against each candidate's bounds so the
remaining ambiguity is explicit rather than assumed.
"""
import json
import pathlib
import struct
import sys
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\.tmp")
sys.path.insert(0, r"C:\_tools\gBox\system")

import session as S                                                # noqa: E402
from gbox import pso_floor_map                                   # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
FLOOR = 0x805D5FC0
ROUTES = pathlib.Path(r"D:\gBox\pso-ds\routes")


def rpc(sid, op, args):
    request = urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions/%s/rpc" % sid,
        data=json.dumps({"op": op, "args": args}).encode(), method="POST",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=30).read() or b"null")


if __name__ == "__main__":
    sessions = json.loads(urllib.request.urlopen(urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"}), timeout=20).read())
    sessions = sessions if isinstance(sessions, list) else (sessions.get("items") or [])
    sid = next(row["session_id"] for row in sessions if row.get("state") in ("running", "starting"))

    raw = rpc(sid, "read_memory", {"address": FLOOR, "length": 4})
    floor = int.from_bytes(bytes.fromhex(raw), "big")
    print("live floor id:", floor)

    area = pso_floor_map.area_for_floor(floor)
    layouts = pso_floor_map.layouts_for_floor(floor)
    print("area:", area)
    print("layouts:", layouts)

    player = (rpc(sid, "state", {"player_only": True}) or {}).get("player") or {}
    x, z = player.get("x"), player.get("z")
    print(f"player ({x:.1f}, {z:.1f}) room={player.get('room')}")

    print("\ncandidate layouts, decoded, against the player position:")
    for layout in layouts:
        path = ROUTES / f"{layout}c-mesh.json"
        if not path.is_file():
            print(f"  {layout:16s} (not decoded)")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        bounds = data.get("bounds")
        walls = len(data.get("blocked") or [])
        if not bounds:
            print(f"  {layout:16s} no bounds")
            continue
        (x0, z0), (x1, z1) = bounds
        inside = x0 <= x <= x1 and z0 <= z <= z1
        print(f"  {layout:16s} bounds ({x0}, {z0})..({x1}, {z1}) walls={walls:5d} contains player: {inside}")

    print("\nnote: 'contains player: False' for all candidates means the layout is translated on load,")
    print("      so the room instance offset is the remaining unknown for path-guiding.")
