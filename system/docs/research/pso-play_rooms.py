"""Room-to-room play: go to the next room, fight what is in the way, open doors, log every step.

The operator's diagnosis is exact - the bot "runs around in the same location ... sitting there shooting at the buttons". Measured: at the time of
writing the character stood 24 units from a `TObjDoor` with a `TObjDoorKey` beside it and **no enemies within 60 units**. A closed or key-locked door
with nothing to fight leaves the previous loop with only exploration, and exploration that repeatedly picks the same nearest centre looks exactly like
circling in place.

This loop fixes the behaviour rather than the symptom:

  * **a destination, not a wander**: the next room comes from the floor's room graph, nearest-unvisited first, and it is remembered so the same room is
    not chosen twice;
  * **doors are interacted with**: within reach of a door, press A (which opens an unlocked door in PSO) and log whether the door state changed; if it
    does not open after a few tries, the door is marked as needing a key and skipped for a while rather than attacked;
  * **enemies take priority** while travelling - lock one, close with short steps, swing, cast beyond melee reach;
  * **every action is logged** with its measurement, so the next diagnosis does not depend on watching it.

Door state is read from the entity's `+0x18C` field, which `pso_doors` documents as 0 closed / 2 open / 224 key / 240 special.
"""
import json
import math
import os
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import game_input as G                                             # noqa: E402
import nav3                                                        # noqa: E402
import pso_input                                                   # noqa: E402
import pso_operator2 as OP                                         # noqa: E402
import run2 as RUN                                                 # noqa: E402
import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, POS, HP = 0x8050D460, 256, 0x38, 0x32C
PLAYER, FLOOR = 0x8050EA10, 0x805D5FC0
ROOMS = Path(r"D:\gBox\pso-ds\routes")
LOG = r"D:\gBox\pso-ds\play_rooms.log"
STATE = Path(r"D:\gBox\pso-ds\play_rooms-state.json")
MELEE = 6.0
DOOR_REACH = 16.0


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def floor():
    return int.from_bytes(S.read_memory(FLOOR, 4), "big")


def player():
    pointer = int.from_bytes(S.read_memory(PLAYER, 4), "big")
    blob = S.read_memory(pointer + POS, 12)
    return struct.unpack(">fff", blob) if len(blob) == 12 else None


def entities(limit=80.0):
    me = player()
    if me is None:
        return [], []
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    foes, doors = [], []
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        try:
            name_pointer = int.from_bytes(S.read_memory(pointer, 4), "big")
            if not (0x80000000 <= name_pointer < 0x81800000):
                continue
            name = S.read_memory(name_pointer, 32).split(b"\x00")[0].decode("ascii", "replace")
            if not name:
                continue
            blob = S.read_memory(pointer, 0x340)
            if len(blob) < 0x340:
                continue
            x, y, z = struct.unpack(">fff", blob[POS:POS + 12])
            hp = struct.unpack(">H", blob[HP:HP + 2])[0]
            state = struct.unpack(">i", blob[0x18C:0x18C + 4])[0]
        except Exception:                                        # noqa: BLE001
            continue
        distance = math.dist((me[0], me[2]), (x, z))
        if distance > limit:
            continue
        if name.startswith(("TObjEne", "TEne", "TBoss")) and hp > 0:
            foes.append({"class": name, "x": x, "y": y, "z": z, "hp": hp, "distance": distance})
        elif "Door" in name:
            doors.append({"class": name, "x": x, "z": z, "state": state, "distance": distance})
    return sorted(foes, key=lambda row: row["distance"]), sorted(doors, key=lambda row: row["distance"])


def rooms_for(current):
    try:
        return json.loads((ROOMS / f"forest{current}-rooms-mesh.json").read_text(encoding="utf-8")).get("rooms") or []
    except Exception:                                            # noqa: BLE001
        return []


def state_load():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return {"visited": {}, "dead_doors": {}}


def state_save(state):
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")


def fight(target, budget=14.0):
    """Close on one enemy and hit it until it dies or the budget runs out."""
    started = time.time()
    initial = target["hp"]
    while time.time() - started < budget:
        if OP.operator_active():
            return
        me = player()
        if me is None:
            return
        foes, _doors = entities(limit=max(40.0, target["distance"] + 20))
        current = next((row for row in foes if row["class"] == target["class"]
                        and math.dist((row["x"], row["z"]), (target["x"], target["z"])) < 12), None)
        if current is None:
            log(f"    {target['class']} is gone")
            return
        gap = math.dist((me[0], me[2]), (current["x"], current["z"]))
        if gap > 30:
            pso_input.hold("b", 0.22)
        elif gap > MELEE:
            step = RUN.unit(current["x"] - me[0], current["z"] - me[2])
            table = RUN.calibrate(lambda: (player()[0], player()[2]) if player() else None)
            key, _align = RUN.best_key(table, step)
            if key is not None:
                pso_input.hold(key, 0.12)
            pso_input.hold("a", 0.22)
        else:
            pso_input.hold("a", 0.22)
        if current["hp"] < initial:
            log(f"    hit {current['class']}: {initial} -> {current['hp']} at {gap:.0f} units")
            initial = current["hp"]


def walk_to(goal, budget=30.0):
    me = player()
    if me is None:
        return False
    route, raw_cells, legs = nav3.plan_h((me[0], me[2]), goal, start_height=me[1])
    if not route:
        RUN.run_to(ME_point(), goal, tolerance=10.0, budget=budget)
        return True
    log(f"    route {raw_cells} cells -> {legs} legs")
    for waypoint in route[1:]:
        RUN.run_to(ME_point(), (waypoint[0], waypoint[1]), tolerance=8.0, budget=12.0)
        if OP.operator_active():
            return False
        # a door on the way is opened, not walked into
        _foes, doors = entities(limit=DOOR_REACH + 4)
        near = next((door for door in doors if door["distance"] <= DOOR_REACH
                     and door["state"] in (0, 240)), None)
        if near is not None:
            log(f"    door {near['class']} state {near['state']} at {near['distance']:.0f} units - pressing A")
            for attempt in range(3):
                pso_input.hold("a", 0.3)
                time.sleep(0.7)
                _f2, again = entities(limit=DOOR_REACH + 4)
                same = next((door for door in again if door["distance"] <= DOOR_REACH + 4), None)
                now = same["state"] if same else None
                log(f"      after A x{attempt + 1}: door state {now}")
                if now == 2:
                    break
    return True


def ME_point():
    import map_exit
    return map_exit.read_pos


def ensure_focus():
    """Restore and raise the app window, then confirm it really has focus.

    Returns True only when `game_has_focus()` says so, because `raise_window()` alone reports success on a minimised window while focus never arrives.
    """
    if G.game_has_focus():
        return True
    if OP.operator_active():
        return False
    try:
        import ctypes
        u = ctypes.windll.user32
        hwnd = G.app_window()
        if hwnd:
            u.ShowWindow(hwnd, 9)                 # SW_RESTORE from minimised
            u.SetForegroundWindow(hwnd)
    except Exception:                                            # noqa: BLE001
        pass
    if not G.game_has_focus():
        G.raise_window()                          # its own attach/focus path
    if G.game_has_focus():
        log("  held the window in front to play")
        return True
    return False


SWITCH_WORDS = ("Door", "Swtch", "Switch", "Key")
SWITCH_RANGE = 40.0


def switches():
    """Every switch-like entity in the area, nearest first."""
    me = player()
    if me is None:
        return []
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    out = []
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        try:
            name_pointer = int.from_bytes(S.read_memory(pointer, 4), "big")
            if not (0x80000000 <= name_pointer < 0x81800000):
                continue
            name = S.read_memory(name_pointer, 32).split(b"\x00")[0].decode("ascii", "replace")
            if not name or not any(word in name for word in SWITCH_WORDS):
                continue
            blob = S.read_memory(pointer, 0x340)
            if len(blob) < 0x340:
                continue
            x, y, z = struct.unpack(">fff", blob[POS:POS + 12])
            state = struct.unpack(">i", blob[0x18C:0x18C + 4])[0]
        except Exception:                                        # noqa: BLE001
            continue
        distance = math.dist((me[0], me[2]), (x, z))
        if state not in (0, 2, 224, 240):
            continue                                   # not a door state: a despawned or unrelated door entity
        if distance <= SWITCH_RANGE:
            out.append({"class": name, "x": x, "y": y, "z": z, "state": state, "distance": distance})
    return sorted(out, key=lambda row: row["distance"])


def press_switches():
    """Walk to the nearest switch and flip it: step toward it (which turns the character), then press A."""
    found = switches()
    if not found:
        return False
    target = found[0]
    log(f"  switch {target['class']} state {target['state']} at {target['distance']:.0f} units")
    if target["distance"] > 7:
        route, raw_cells, legs = nav3.plan_h((player()[0], player()[2]), (target["x"], target["z"]),
                                             start_height=player()[1], goal_height=target["y"])
        if route:
            for waypoint in route[1:4]:
                RUN.run_to(ME_point(), (waypoint[0], waypoint[1]), tolerance=5.0, budget=12.0)
                if OP.operator_active():
                    return True
    for attempt in range(8):
        me = player()
        if me is None:
            return True
        here = math.dist((me[0], me[2]), (target["x"], target["z"]))
        if here > 2.5:
            step = RUN.unit(target["x"] - me[0], target["z"] - me[2])
            table = RUN.calibrate(ME_point())
            key, _align = RUN.best_key(table, step)
            if key is not None:
                pso_input.hold(key, 0.12)
        pso_input.hold("a", 0.3)
        time.sleep(0.45)
        again = next((row for row in switches() if math.dist((row["x"], row["z"]),
                                                             (target["x"], target["z"])) < 8), None)
        state = again["state"] if again else None
        log(f"    step+press x{attempt + 1}: at {here:.1f} units, state {state}")
        if state == 2:
            log("    open")
            return True
    log("    still locked after eight step-and-press attempts - will come back to it")
    return True


def main(seconds=3600.0):
    log("=== room-to-room play")
    state = state_load()
    current_floor = None
    target_room = None
    started = time.time()
    while time.time() - started < seconds:
        if os.path.exists(r"D:\gBox\pso-ds\PAUSED") or OP.operator_active():
            time.sleep(0.5)
            continue
        if not ensure_focus():
            time.sleep(0.4)
            continue
        try:
            me = player()
            if me is None:
                time.sleep(1.0)
                continue
            here = floor()
            if here != current_floor:
                current_floor = here
                state["visited"] = {}
                target_room = None
                log(f"floor {here}")
            if press_switches():
                continue
            foes, doors = entities()
            if foes:
                log(f"  {len(foes)} enemies, nearest {foes[0]['class']} hp {foes[0]['hp']} at {foes[0]['distance']:.0f}")
                fight(foes[0])
                continue
            room_list = rooms_for(here)
            if room_list:
                visited = state.setdefault("visited", {})
                unseen = [room for room in room_list if str(room["room"]) not in visited]
                if target_room is None or str(target_room) in visited:
                    if not unseen:
                        log("  every room visited")
                        unseen = room_list
                        visited.clear()
                    target_room = min(unseen, key=lambda room: math.dist((me[0], me[2]), tuple(room["centre"])))["room"]
                target = next(room for room in room_list if room["room"] == target_room)
                log(f"  heading for room {target_room} at ({target['centre'][0]:.0f},{target['centre'][1]:.0f})")
                walk_to((target["centre"][0], target["centre"][1]))
                now_point = player()
                reached = now_point is not None and math.dist((now_point[0], now_point[2]),
                                                              tuple(target["centre"])) < 40
                attempts = state.setdefault("attempts", {})
                key = str(target_room)
                attempts[key] = attempts.get(key, 0) + 1
                if reached:
                    visited[key] = round(time.time(), 1)
                    log(f"  room {target_room} reached - marked visited")
                elif attempts[key] >= 2:
                    visited[key] = round(time.time(), 1)
                    log(f"  room {target_room} not reachable in {attempts[key]} attempts - moving on")
                else:
                    log(f"  room {target_room} attempt {attempts[key]} incomplete - will try once more")
                state_save(state)
                target_room = None
                continue
            # no room graph for this floor: walk to the nearest door and open it
            closed = [door for door in doors if door["state"] in (0, 240)]
            if closed:
                nearest = closed[0]
                log(f"  no map: walking to {nearest['class']} at {nearest['distance']:.0f} units")
                RUN.run_to(ME_point(), (nearest["x"], nearest["z"]), tolerance=6.0, budget=15.0)
                pso_input.hold("a", 0.3)
                time.sleep(0.6)
                continue
            time.sleep(1.0)
        except Exception as exc:                                  # noqa: BLE001
            log(f"  step failed: {type(exc).__name__}: {str(exc)[:80]}")
            time.sleep(1.0)


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 3600.0)
