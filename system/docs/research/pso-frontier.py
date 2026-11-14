"""Choose the next unexplored doorway: the nearest door in the current room that has never been crossed.

Uses the live session's full entity list (each door's ptr/room/x/z), the crossing log written by
`pso-door-crossings.py` (from-room -> door position -> to-room, per floor layout), and `visited.json`
(pso-progress-tracker.py). Output is the door coordinate the bot should walk through; the supervisor runs
`pso-bounded.py walk --to <door> --through` for it, which is a doorway crossing (room change) and therefore also a new
crossing sample for the log - so coverage improves every chunk.

    python pso-frontier.py --json
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib

OUT = pathlib.Path(r"D:\gBox\pso-ds\mandate")
ROUTES = pathlib.Path(r"D:\gBox\pso-ds\routes")
DOOR_WORDS = ("TODoor", "TObjDoor", "LazerFence", "Barrier", "Fence")
MATCH_RADIUS = 28.0


def load_jsonl(path):
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def layout_key(floor, entities):
    candidates = sorted(ROUTES.glob(f"live-map-floor{floor}-*.json"), key=lambda path: path.stat().st_mtime)
    return candidates[-1].stem if candidates else f"floor{floor}"


def door_entities(entities):
    doors = []
    for entity in entities:
        cls = str(entity.get("class") or "")
        if not any(word in cls for word in DOOR_WORDS):
            continue
        # Panels are switches, not passages: TLazerFenceSw and TObjDoorKey are pressed, never walked through.
        if cls in ("TLazerFenceSw", "TObjDoorKey") or cls.endswith("Sw"):
            continue
        try:
            doors.append({"ptr": str(entity.get("ptr")), "class": cls, "room": entity.get("room"),
                          "x": float(entity["x"]), "z": float(entity["z"])})
        except (KeyError, TypeError, ValueError):
            continue
    return doors


def known_destinations(crossings, doors, floor, layout):
    """{(from_room, door_ptr): to_room} from crossings matched to the nearest door on the floor."""
    known = {}
    for row in crossings:
        if row.get("event") != "crossing" or row.get("floor") != floor:
            continue
        if row.get("layout") != layout:
            continue
        x, z = float(row.get("x") or 0), float(row.get("z") or 0)
        nearest = None
        for door in doors:
            distance = math.hypot(door["x"] - x, door["z"] - z)
            if nearest is None or distance < nearest[0]:
                nearest = (distance, door)
        if nearest and nearest[0] <= MATCH_RADIUS:
            known[(row.get("from_room"), nearest[1]["ptr"])] = row.get("to_room")
    return known


def main(argv=None):
    parser = argparse.ArgumentParser(description="pick the next never-crossed doorway")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    import urllib.request
    token = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token").read_text(encoding="utf-8").strip()
    base = "http://127.0.0.1:18765"

    def call(path, payload=None, method="GET"):
        request = urllib.request.Request(
            base + path, data=json.dumps(payload).encode() if payload is not None else None, method=method,
            headers={"authorization": "Bearer " + token, "x-gbox-actor": "agent",
                     "content-type": "application/json"})
        return json.loads(urllib.request.urlopen(request, timeout=60).read() or b"null")

    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    live = next((row for row in rows if row.get("state") in ("running", "starting")), None)
    if live is None:
        raise SystemExit("no live session")
    session_id = live["session_id"]
    state = call(f"/api/sessions/{session_id}/rpc", {"op": "state", "args": {}}, "POST") or {}
    player = state.get("player") or {}
    if not player.get("ptr"):
        raise SystemExit("no live player")
    raw_floor = call(f"/api/sessions/{session_id}/rpc", {"op": "read_memory",
                                                        "args": {"address": 0x805D5FC0, "length": 4}}, "POST")
    floor = int(raw_floor, 16) if isinstance(raw_floor, str) else None
    px, pz = float(player.get("x") or 0), float(player.get("z") or 0)
    room = player.get("room")
    entities = state.get("entities") or []
    doors = door_entities(entities)
    layout = layout_key(floor, entities)
    crossings = load_jsonl(OUT / "door-crossings.jsonl")
    known = known_destinations(crossings, doors, floor, layout)
    visited_path = OUT / "visited.json"
    visited = set()
    if visited_path.exists():
        try:
            visited = set(json.loads(visited_path.read_text(encoding="utf-8")).get(str(floor)) or [])
        except ValueError:
            visited = set()
    visited.add(room)
    candidates = []
    for door in doors:
        if door["room"] != room:
            continue
        distance = math.hypot(door["x"] - px, door["z"] - pz)
        if distance > 420.0:
            continue
        destination = known.get((room, door["ptr"]))
        if destination is None:
            candidates.append((0, distance, door, "never-crossed doorway"))
        elif destination not in visited:
            candidates.append((1, distance, door, f"doorway to unvisited room {destination}"))
    if not candidates:
        print(json.dumps({"door": None, "reason": "every known doorway in this room has been crossed", "floor": floor,
                          "room": room, "doors": len(doors), "crossings": len(crossings)}))
        return 0
    candidates.sort(key=lambda row: (row[0], row[1]))
    priority, distance, door, reason = candidates[0]
    result = {"door": [round(door["x"], 1), round(door["z"], 1)], "ptr": door["ptr"], "class": door["class"],
              "room": room, "floor": floor, "layout": layout, "distance": round(distance, 1),
              "reason": reason, "known_doorways": len(known), "crossings_logged": len(crossings)}
    if args.json:
        print(json.dumps(result))
    else:
        print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
