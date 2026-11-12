"""Which decoded room is the player standing in? Match the live position against every room's bounds.

Path-guiding needs one thing before anything else: the live world position has to be attributable to a specific collision file, so its walls can be loaded.
The 51 decoded rooms each have a bounding box in world coordinates. If the player's (x, z) falls inside exactly one of them, that is the room - no guessing
from room numbers, no assumption that a room index lines up with a file name.

Reports every candidate and, when more than one matches, the room number as a tiebreak.
"""
import json
import pathlib
import sys
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
ROUTES = pathlib.Path(r"D:\gBox\pso-ds\routes")


def rpc(sid, op, args):
    request = urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions/%s/rpc" % sid,
        data=json.dumps({"op": op, "args": args}).encode(), method="POST",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=30).read() or b"null")


def rooms():
    for path in sorted(ROUTES.glob("map_*c-mesh.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:                                          # noqa: BLE001
            continue
        bounds = data.get("bounds")
        if not bounds:
            continue
        yield path.stem, data["floor"], bounds, len(data.get("blocked") or [])


if __name__ == "__main__":
    sessions = json.loads(urllib.request.urlopen(urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"}), timeout=20).read())
    sessions = sessions if isinstance(sessions, list) else (sessions.get("items") or [])
    live = [row for row in sessions if row.get("state") in ("running", "starting")]
    print("live sessions:", len(live))
    if not live:
        raise SystemExit("no live session")

    sid = live[0]["session_id"]
    state = rpc(sid, "state", {"player_only": True})
    player = state.get("player") or {}
    x, z = player.get("x"), player.get("z")
    print(f"session {sid}")
    print(f"player at ({x:.1f}, {z:.1f}) room={player.get('room')} heading={player.get('heading_deg')}")

    all_rooms = list(rooms())
    print(f"\ndecoded rooms: {len(all_rooms)}")

    hits = []
    for stem, floor, bounds, blocked in all_rooms:
        (x0, z0), (x1, z1) = bounds
        inside = x0 <= x <= x1 and z0 <= z <= z1
        if inside:
            hits.append((stem, floor, bounds, blocked))

    print(f"rooms whose bounds contain the player: {len(hits)}")
    for stem, floor, bounds, blocked in hits:
        print(f"  {stem:38s} floor={floor:12s} bounds={bounds} walls={blocked}")

    if not hits:
        print("\nno room contains the position - the collision files are not in the same coordinate space")
        print("nearest five rooms by bounding-box centre:")
        ranked = sorted(all_rooms, key=lambda row: ((row[2][0][0] + row[2][1][0]) / 2 - x) ** 2
                        + ((row[2][0][1] + row[2][1][1]) / 2 - z) ** 2)
        for stem, floor, bounds, _ in ranked[:5]:
            cx = (bounds[0][0] + bounds[1][0]) / 2
            cz = (bounds[0][1] + bounds[1][1]) / 2
            print(f"  {stem:38s} centre ({cx:.0f}, {cz:.0f}) distance {((cx - x) ** 2 + (cz - z) ** 2) ** 0.5:.0f}")
