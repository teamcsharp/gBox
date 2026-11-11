"""Explore Forest 1 room by room until the area warp (the teleporter to the next level) appears, then walk into it.

The operator's loop: go room to room through unexplored rooms, flip switches, and reach the teleporter. This implements exactly that:

  1. rooms come from the collision-graph room map (forest1-rooms.json, 9 rooms with their cells);
  2. every room entered is marked visited; the next target is the nearest UNVISITED room, reached by steering toward its centre
     (the room graph is connected through doorways, so a straight steer crosses the threshold);
  3. on arriving in a room, the entity table is scanned: a class containing "Warp" is the teleporter -> walk to it and press A;
     switch classes (TLazerFenceSw / TOSwitchAttackSub) -> the flip routine runs;
  4. every entry and every flip is logged, so a run is reviewable.

Input honours the v2 operator lock: it pauses whenever the operator takes the controller and resumes 3 s after they stop.
"""
import json
import math
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import game_input as G                                             # noqa: E402
import pso_operator2 as OP                                         # noqa: E402
import session as S                                                # noqa: E402
import steer2 as STEER                                             # noqa: E402

TABLE, MAX_ENTRIES, POS = 0x8050D460, 256, 0x38
FLOOR = 0x805D5FC0
ROOMS_FILE = Path(r"D:\gBox\pso-ds\routes\forest1-rooms.json")
STATE = Path(r"D:\gBox\pso-ds\explore-state.json")
LOG = r"D:\gBox\pso-ds\explore.log"
WARP_HINTS = ("Warp", "warp")
SWITCH_HINTS = ("TLazerFenceSw", "TOSwitchAttackSub", "TOSwitch")


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def read_pos():
    pointer = int.from_bytes(S.read_memory(0x8050EA10, 4), "big")
    if not pointer:
        return None
    blob = S.read_memory(pointer + POS, 12)
    if len(blob) != 12:
        return None
    x, _y, z = struct.unpack(">fff", blob)
    return (x, z)


import pso_input

hold = pso_input.hold
tap = pso_input.tap


def entities(hints=None):
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    out = []
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        name_pointer = int.from_bytes(S.read_memory(pointer, 4), "big")
        if not (0x80000000 <= name_pointer < 0x81800000):
            continue
        name = S.read_memory(name_pointer, 32).split(b"\x00")[0].decode("ascii", "replace")
        if hints and not any(hint in name for hint in hints):
            continue
        blob = S.read_memory(pointer + POS, 12)
        if len(blob) != 12:
            continue
        x, y, z = struct.unpack(">fff", blob)
        out.append({"index": index, "class": name, "x": x, "y": y, "z": z})
    return out


def rooms():
    data = json.loads(ROOMS_FILE.read_text(encoding="utf-8"))
    return [{"room": row["room"], "centre": tuple(row["centre"]), "cells": [tuple(c) for c in row["cell_list"]]}
            for row in data["rooms"]]


def room_of(point, room_list):
    best = None
    for room in room_list:
        distance = math.dist(point, room["centre"])
        if best is None or distance < best[0]:
            best = (distance, room["room"])
    return best[1] if best else None


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return {"visited": [], "flips": []}


def save_state(state):
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")


def main(max_minutes=25.0):
    room_list = rooms()
    state = load_state()
    visited = set(state.get("visited", []))
    log(f"=== explore; rooms {[r['room'] for r in room_list]}, visited {sorted(visited)}")
    started = time.time()
    while time.time() - started < max_minutes * 60:
        if int.from_bytes(S.read_memory(FLOOR, 4), "big") != 1:
            log("floor changed - a warp fired")
            return 0
        while OP.operator_active():
            time.sleep(0.3)
        point = read_pos()
        if point is None:
            time.sleep(0.3)
            continue
        here = room_of(point, room_list)
        if here is not None and here not in visited:
            visited.add(here)
            state["visited"] = sorted(visited)
            save_state(state)
            log(f"entered room {here} at ({point[0]:.0f},{point[1]:.0f}); visited {sorted(visited)}")
        warps = entities(WARP_HINTS)
        if warps:
            warp = min(warps, key=lambda e: math.dist(point, (e["x"], e["z"])))
            distance = math.dist(point, (warp["x"], warp["z"]))
            log(f"TELEPORTER FOUND: {warp['class']} at ({warp['x']:.0f},{warp['z']:.0f}), {distance:.0f} units")
            arrived, steps, final, reason = STEER.step_toward(hold, read_pos, (warp["x"], warp["z"]),
                                                             tolerance=8.0, max_steps=25, log=log,
                                                             on_stuck=lambda n: (tap("b"), True)[1])
            log(f"  approach: arrived={arrived} final={final:.0f} ({reason})")
            if arrived or (final is not None and final < 14):
                tap("a")
                time.sleep(3.0)
                if int.from_bytes(S.read_memory(FLOOR, 4), "big") != 1:
                    log("telported to the next area")
                    return 0
            continue
        switches = entities(SWITCH_HINTS)
        near_switch = [s for s in switches if math.dist(point, (s["x"], s["z"])) < 30]
        if near_switch:
            switch = near_switch[0]
            log(f"switch {switch['class']} at ({switch['x']:.0f},{switch['z']:.0f}) is close; walking and pressing A")
            STEER.step_toward(hold, read_pos, (switch["x"], switch["z"]), tolerance=7.0, max_steps=12, log=log)
            tap("a")
            state["flips"].append({"class": switch["class"], "x": round(switch["x"]), "z": round(switch["z"]),
                                   "t": time.time()})
            save_state(state)
            continue
        candidates = [room for room in room_list if room["room"] not in visited] or \
                     [room for room in room_list if room["room"] != here]
        if not candidates:
            log("all rooms visited and no teleporter in the table")
            return 2
        target = min(candidates, key=lambda room: math.dist(point, room["centre"]))
        log(f"heading for unvisited room {target['room']} centre ({target['centre'][0]:.0f},{target['centre'][1]:.0f})")
        STEER.step_toward(hold, read_pos, target["centre"], tolerance=25.0, max_steps=20, log=None,
                          on_stuck=lambda n: (tap("b"), True)[1])
    log("time budget spent")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(float(sys.argv[1]) if len(sys.argv) > 1 else 25.0))
