"""Choose the next doorway to cross: the nearest unexplored door, or the first hop toward a room that has one.

Uses the live session's full entity list (each door's ptr/room/x/z), the crossing log written by
`pso-door-crossings.py` (from-room -> door position -> to-room, per floor layout), and `visited.json`
(pso-progress-tracker.py). Two modes:

* the current room still has a door that has never been crossed -> return that door (nearest first);
* every door here is known -> BFS over the learned room graph to the nearest reachable room that still has an
  unexplored door, and return the **first hop's door** so the supervisor walks one doorway per chunk toward it.

The supervisor runs `pso-bounded.py walk --to <door> --through`, a doorway crossing, which the crossing tracker
records - so coverage improves every chunk even when the answer is "go back through a known door to continue".

    python pso-frontier.py --json
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import pathlib
import sys

OUT = pathlib.Path(r"D:\gBox\pso-ds\mandate")
ROUTES = pathlib.Path(r"D:\gBox\pso-ds\routes")
DOOR_WORDS = ("TODoor", "TObjDoor", "LazerFence", "Barrier", "Fence")
PANELS = ("TLazerFenceSw", "TObjDoorKey")
MATCH_RADIUS = 28.0


def load_router(key):
    """MapRouter over the live floor's walkable cells, so unreachable doors are never chosen as targets."""
    try:
        sys.path.insert(0, r"C:\_tools\gBox\system")
        sys.path.insert(0, r"C:\_tools\gBox\.tmp")
        from forest_route import MapRouter
        path = ROUTES / f"{key}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        row = data.get(next(iter(data))) if data else None
        if not row:
            return None
        return MapRouter(sorted(row["cells"]))
    except Exception:                                            # noqa: BLE001 - routing is an aid, never a dependency
        return None


def reachable(router, start, goal):
    if router is None:
        return True                                              # no map: do not forbid a target
    try:
        return router.route(start, goal) is not None
    except Exception:                                            # noqa: BLE001
        return True


def blocked_doors(key):
    """Doors whose collision route failed recently. Entries expire: a gate can open later (saturated flags, a wave
    cleared) and a route that failed now may succeed then, so this is a 15-minute veto, not a permanent one."""
    path = OUT / "door-blocked.json"
    if not path.exists():
        return {}
    try:
        raw = dict(json.loads(path.read_text(encoding="utf-8")).get(key) or {})
    except ValueError:
        return {}
    import time as _time
    now = _time.time()
    return {ptr: when for ptr, when in raw.items() if isinstance(when, (int, float)) and now - when < 900.0}


def mark_blocked(key, ptr):
    path = OUT / "door-blocked.json"
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
    data.setdefault(key, {})[str(ptr)] = __import__("time").time()
    path.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")


def log_event(record):
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "frontier.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def load_jsonl(path):
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def layout_key(floor):
    candidates = sorted(ROUTES.glob(f"live-map-floor{floor}-*.json"), key=lambda path: path.stat().st_mtime)
    return candidates[-1].stem if candidates else f"floor{floor}"


def door_entities(entities):
    doors = []
    for entity in entities:
        cls = str(entity.get("class") or "")
        if not any(word in cls for word in DOOR_WORDS):
            continue
        if cls in PANELS or cls.endswith("Sw"):
            continue                     # panels are pressed, not walked through
        try:
            doors.append({"ptr": str(entity.get("ptr")), "class": cls, "room": entity.get("room"),
                          "x": float(entity["x"]), "z": float(entity["z"])})
        except (KeyError, TypeError, ValueError):
            continue
    return doors


def nearest_door(doors, x, z):
    best = None
    for door in doors:
        distance = math.hypot(door["x"] - x, door["z"] - z)
        if best is None or distance < best[0]:
            best = (distance, door)
    return best


def learned_graph(doors, crossings, floor, layout):
    """(known_destinations, adjacency): {(from_room, door_ptr): to_room}, {room: [(door, neighbour_room)]}."""
    known = {}
    adjacency = collections.defaultdict(list)
    for row in crossings:
        if row.get("event") != "crossing" or row.get("floor") != floor or row.get("layout") != layout:
            continue
        from_room, to_room = row.get("from_room"), row.get("to_room")
        match = nearest_door(doors, float(row.get("x") or 0), float(row.get("z") or 0))
        if match is None or match[0] > MATCH_RADIUS:
            continue                      # a crossing we cannot pin to a door teaches no edge
        door = match[1]
        known[(from_room, door["ptr"])] = to_room
        adjacency[from_room].append((door, to_room))
        known.setdefault((to_room, door["ptr"]), from_room)
        adjacency[to_room].append((door, from_room))
    return known, adjacency


def unfinished_doors(doors, room, known):
    return [door for door in doors if door["room"] == room and (room, door["ptr"]) not in known]


def route_to_unexplored(doors, adjacency, start_room, known):
    """BFS over learned room edges; returns (first_hop_door, first_hop_room, destination_room, hops) or None."""
    queue = collections.deque([(start_room, None, 0)])
    seen = {start_room}
    while queue:
        room, first_door, hops = queue.popleft()
        if room != start_room and unfinished_doors(doors, room, known):
            return first_door, room, room, hops
        for door, neighbour in adjacency.get(room, []):
            if neighbour in seen:
                continue
            seen.add(neighbour)
            queue.append((neighbour, first_door or door, hops + 1))
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description="pick the next unexplored doorway or the first hop toward one")
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
    doors = door_entities(state.get("entities") or [])
    layout = layout_key(floor)
    crossings = load_jsonl(OUT / "door-crossings.jsonl")
    known, adjacency = learned_graph(doors, crossings, floor, layout)
    router = load_router(layout)
    blocked = blocked_doors(layout)

    candidates = []
    for door in unfinished_doors(doors, room, known):
        distance = math.hypot(door["x"] - px, door["z"] - pz)
        if distance > 420.0 or door["ptr"] in blocked:
            continue
        if not reachable(router, (px, pz), (door["x"], door["z"])):
            mark_blocked(layout, door["ptr"])
            log_event({"at": __import__("time").time(), "event": "blocked", "layout": layout, "ptr": door["ptr"],
                       "class": door["class"], "door": [round(door["x"], 1), round(door["z"], 1)],
                       "room": room, "reason": "no collision route from the player"})
            continue
        candidates.append((distance, door))
    if candidates:
        candidates.sort(key=lambda row: row[0])
        distance, door = candidates[0]
        result = {"door": [round(door["x"], 1), round(door["z"], 1)], "ptr": door["ptr"],
                  "class": door["class"], "room": room, "floor": floor, "layout": layout,
                  "distance": round(distance, 1), "reason": "never-crossed doorway",
                  "known_doorways": len(known), "crossings_logged": len(crossings),
                  "routed": router is not None}
    else:
        route = route_to_unexplored(doors, adjacency, room, known)
        if route is not None:
            door, first_room, destination, hops = route
            if door["ptr"] in blocked or not reachable(router, (px, pz), (door["x"], door["z"])):
                mark_blocked(layout, door["ptr"])
                route = None
        if route is None:
            result = {"door": None, "reason": "no reachable room with an unexplored doorway",
                      "floor": floor, "room": room, "known_doorways": len(known)}
        else:
            door, first_room, destination, hops = route
            distance = math.hypot(door["x"] - px, door["z"] - pz)
            result = {"door": [round(door["x"], 1), round(door["z"], 1)], "ptr": door["ptr"],
                      "class": door["class"], "room": room, "floor": floor, "layout": layout,
                      "distance": round(distance, 1),
                      "reason": f"first hop toward room {destination} ({hops} hop(s)) which has unexplored doors",
                      "known_doorways": len(known), "crossings_logged": len(crossings),
                      "routed": router is not None}
    log_event({"at": __import__("time").time(), "event": "plan", **{k: v for k, v in result.items() if k != "door"},
               "door": result.get("door")})
    if args.json:
        print(json.dumps(result))
    else:
        print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
