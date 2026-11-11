"""Explore the level room by room, choosing exits from the MINIMAP and crossing them with the doorway routine.

This replaces aiming at room centres (which walks into walls) with the operator's rule: look at the map, take the doorway, go room to room.
Each iteration:
  1. read which room the character is in (collision-graph room map) and mark it visited;
  2. look for a warp class in the entity table - that is the teleporter to the next area -> walk to it and press A;
  3. flip any switch within reach;
  4. otherwise pick the next unvisited room, compare its world bearing with the minimap exit markers, and walk through the marker whose
     bearing matches - then loop.

Measured this round: map bearings are north-up and agree with world door bearings (marker -118 deg vs TObjDoor -110.3 deg, 7.7 deg).
All input goes through pso_input, so the operator lock always wins.
"""
import json
import math
import pathlib
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import door_pass2                                                  # noqa: E402
import explore as E                                                # noqa: E402
import map_exit as ME                                              # noqa: E402
import pso_input                                                   # noqa: E402
import session as S                                                # noqa: E402

FLOOR = 0x805D5FC0
STATE = Path(r"D:\gBox\pso-ds\explore2-state.json")
LOG = r"D:\gBox\pso-ds\explore2.log"


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return {"visited": [], "flips": [], "exits_used": 0}


def save_state(state):
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")


def bearing(point, target):
    return math.degrees(math.atan2(target[1] - point[1], target[0] - point[0]))


def pick_marker(point, room, markers):
    """The minimap marker whose bearing points at the chosen room, or (None, None) when the map shows no exits."""
    if not markers:
        return None, None
    room_bearing = bearing(point, room["centre"])
    best = None
    for marker in markers:
        error = abs(((marker["bearing"] - room_bearing) + 180) % 360 - 180)
        if best is None or error < best[0]:
            best = (error, marker)
    return best[0], best[1] if best else (None, None)


def connecting_door(current_room, target_room):
    """The doorway the room graph says links two rooms, or None."""
    try:
        data = json.loads(pathlib.Path(r"D:\gBox\pso-ds\routes\forest1-rooms.json").read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return None
    for door in data.get("doors", []):
        rooms = door.get("rooms") or []
        if len(rooms) >= 2 and {rooms[0], rooms[1]} == {current_room, target_room}:
            return door
    return None


def main(max_minutes=25.0):
    state = load_state()
    visited = set(state.get("visited", []))
    rooms = E.rooms()
    log(f"=== explore v2; visited {sorted(visited)}")
    started = time.time()
    while time.time() - started < max_minutes * 60:
        if int.from_bytes(S.read_memory(FLOOR, 4), "big") != 1:
            log("floor changed - warp fired")
            return 0
        if not pso_input.wait_until_ready(60.0):
            time.sleep(1.0)
            continue
        point = ME.read_pos()
        if point is None:
            time.sleep(0.3)
            continue
        current = E.room_of(point, rooms)
        if current not in visited:
            visited.add(current)
            state["visited"] = sorted(visited)
            save_state(state)
            log(f"entered room {current} at ({point[0]:.0f},{point[1]:.0f}); visited {sorted(visited)}")
        warps = E.entities(E.WARP_HINTS)
        if warps:
            warp = min(warps, key=lambda e: math.dist(point, (e["x"], e["z"])))
            log(f"TELEPORTER {warp['class']} at ({warp['x']:.0f},{warp['z']:.0f})")
            arrived, steps, final, reason = E.STEER.step_toward(
                pso_input.hold, ME.read_pos, (warp["x"], warp["z"]), tolerance=8.0, max_steps=25, log=None)
            log(f"  approach arrived={arrived} final={None if final is None else round(final)} ({reason})")
            pso_input.tap("a")
            time.sleep(3.0)
            if int.from_bytes(S.read_memory(FLOOR, 4), "big") != 1:
                log("took the teleporter")
                return 0
            continue
        switches = [s for s in E.entities(E.SWITCH_HINTS) if math.dist(point, (s["x"], s["z"])) < 28]
        if switches:
            switch = switches[0]
            log(f"switch {switch['class']} at ({switch['x']:.0f},{switch['z']:.0f}) in reach; pressing A")
            E.STEER.step_toward(pso_input.hold, ME.read_pos, (switch["x"], switch["z"]), tolerance=6.0,
                                max_steps=10, log=None)
            pso_input.tap("a")
            state["flips"].append({"class": switch["class"], "x": round(switch["x"]), "z": round(switch["z"]),
                                   "t": time.time()})
            save_state(state)
            continue
        candidates = [room for room in rooms if room["room"] not in visited] or \
                     [room for room in rooms if room["room"] != current]
        target_room = min(candidates, key=lambda room: math.dist(point, room["centre"]))
        markers = ME.exits_from_map()
        error, marker = pick_marker(point, target_room, markers)
        if marker is None:
            door = connecting_door(current, target_room["room"])
            if door is not None:
                log(f"no exit marker; room graph links {current} -> {target_room['room']} via "
                    f"{door['class']} at ({door['x']:.0f},{door['z']:.0f})")
                through, position, reason = door_pass2.approach(
                    door_pass2.GameDeps(), (door["x"], door["z"]), straight_steps=6, attempts=8)
                log(f"  through={through} at {None if position is None else tuple(round(v) for v in position)} ({reason})")
                continue
            log("no exit marker and no door edge; falling back to the room centre")
            E.STEER.step_toward(pso_input.hold, ME.read_pos, target_room["centre"], tolerance=25.0, max_steps=12, log=None)
            continue
        log(f"room {current} -> {target_room['room']}: exit marker bearing {marker['bearing']:+.0f} "
            f"(room bearing {bearing(point, target_room['centre']):+.0f}, error {error:.0f} deg)")
        exit_target = (point[0] + marker["dir"][0] * 50.0, point[1] + marker["dir"][1] * 50.0)
        through, position, reason = door_pass2.approach(door_pass2.GameDeps(), exit_target, straight_steps=6,
                                                       attempts=8)
        state["exits_used"] = state.get("exits_used", 0) + (1 if through else 0)
        save_state(state)
        log(f"  through={through} at {None if position is None else tuple(round(v) for v in position)} ({reason})")
    log("time budget spent")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(float(sys.argv[1]) if len(sys.argv) > 1 else 25.0))
