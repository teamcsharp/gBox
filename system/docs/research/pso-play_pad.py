"""The bot, driving a virtual pad: no keyboard, no focus, no window.

Every keyboard route failed (rounds 1-3: virtual keys, scancodes, every target window, focused and unfocused), while the operator's controller always
worked and the app forwards a controller into the game. `vpad.py` makes the bot a controller, so this loop needs none of the keyboard machinery:

  * **calibrate** the stick once (four directions, measured against the character, because PSO is camera-relative);
  * **every cycle**: flip a switch if one is in reach, else fight the nearest enemy, else move to the next room;
  * **movement** is `pad.move(dx, dz)` - hold the stick for a fraction of a second toward the target;
  * **actions** are `pad.press("a")` (interact / attack) and `pad.press("b")` beyond melee reach (technique).

Nothing here calls `pso_input`, so nothing here depends on which window has focus. The operator's pad still wins: a recent press by them pauses the loop
for thirty seconds.
"""
import math
import os
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import nav3                                                        # noqa: E402
import pso_operator2 as OP                                         # noqa: E402
import session as S                                                # noqa: E402
import vpad                                                        # noqa: E402

TABLE, MAX_ENTRIES, POS, HP = 0x8050D460, 256, 0x38, 0x32C
PLAYER = 0x8050EA10
LOG = r"D:\gBox\pso-ds\play_pad.log"
ROUTES = Path(r"D:\gBox\pso-ds\routes")
MELEE = 6.0
SWITCH_RANGE = 120.0
SWITCH_WORDS = ("Door", "Swtch", "Switch", "Key")


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def player():
    pointer = int.from_bytes(S.read_memory(PLAYER, 4), "big")
    if not (0x80000000 <= pointer < 0x81800000):
        return None
    blob = S.read_memory(pointer + POS, 12)
    return struct.unpack(">fff", blob) if len(blob) == 12 else None


def read_pos():
    point = player()
    return (point[0], point[1], point[2]) if point else None


def entities():
    me = player()
    if me is None:
        return [], []
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    foes, switches = [], []
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
        if name.startswith(("TObjEne", "TEne", "TBoss")) and hp > 0 and distance <= 80:
            foes.append({"class": name, "x": y * 0 + x, "y": y, "z": z, "hp": hp, "distance": distance})
        elif any(word in name for word in SWITCH_WORDS) and distance <= SWITCH_RANGE:
            switches.append({"class": name, "x": x, "y": y, "z": z, "state": state, "distance": distance})
    return sorted(foes, key=lambda row: row["distance"]), sorted(switches, key=lambda row: row["distance"])


EXIT_WORDS = ("Portal", "Warp", "Exit", "Gate", "Teleport", "Vr", "Stair")


def exits():
    """Exit-like objects: the way out of the area, whatever the game calls it."""
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
            if not name or not any(word in name for word in EXIT_WORDS):
                continue
            blob = S.read_memory(pointer, 0x340)
            if len(blob) < 0x340:
                continue
            x, y, z = struct.unpack(">fff", blob[POS:POS + 12])
        except Exception:                                        # noqa: BLE001
            continue
        if name.startswith("TObjPlayer"):
            continue
        out.append({"class": name, "x": x, "y": y, "z": z,
                    "distance": math.dist((me[0], me[2]), (x, z))})
    return sorted(out, key=lambda row: row["distance"])


def rooms_for(current_floor):
    try:
        return json.loads((ROUTES / f"forest{current_floor}-rooms-mesh.json").read_text(encoding="utf-8")).get("rooms") or []
    except Exception:                                            # noqa: BLE001
        return []


def approach(pad, point, target, tolerance=3.0, seconds=0.35):
    """One pad-driven step toward a point. Returns the distance after it."""
    here = player()
    if here is None:
        return None
    gap = math.dist((here[0], here[2]), (target[0], target[1]))
    if gap <= tolerance:
        return gap
    pad.move(target[0] - here[0], target[1] - here[2], seconds=seconds)
    time.sleep(0.05)
    after = player()
    if after is None:
        return gap
    return math.dist((after[0], after[2]), (target[0], target[1]))


def boot(pad, limit=120):
    """Press through the title and menus until a character exists. Returns True when one does."""
    me = player()
    if me is not None:
        return True
    log("no character yet - pressing through the title and menus")
    for attempt in range(limit):
        pad.press("start", 0.2)
        time.sleep(1.0)
        pad.press("a", 0.25)
        time.sleep(0.8)
        me = player()
        if me is not None:
            log(f"character appeared after {attempt + 1} rounds of start+A")
            return True
        if attempt % 10 == 9:
            log(f"  still no character after {attempt + 1} attempts")
    log("gave up waiting for a character")
    return False


def main(seconds=3600.0):
    log("=== pad-driven play")
    pad = vpad.Pad()
    if not boot(pad):
        log("no character to play - stopping")
        return 2
    log("calibrating the stick against the character")
    table = pad.calibrate(read_pos)
    for name, move in table.items():
        log(f"  stick {name}: moved ({move[0]:+.1f}, {move[1]:+.1f})")
    if not table:
        log("calibration produced nothing - is the game in the field?")
        return 1
    started = time.time()
    target_room = None
    start_floor = int.from_bytes(S.read_memory(0x805D5FC0, 4), "big")
    log(f"starting on floor {start_floor}")
    while time.time() - started < seconds:
        if os.path.exists(r"D:\gBox\pso-ds\PAUSED") or OP.operator_active():
            time.sleep(0.6)
            continue
        me = player()
        if me is None:
            time.sleep(1.0)
            continue
        here_floor = int.from_bytes(S.read_memory(0x805D5FC0, 4), "big")
        if here_floor != start_floor:
            log(f"AREA CLEARED: floor {start_floor} -> {here_floor}")
            start_floor = here_floor
        way_out = exits()
        if way_out:
            log(f"exit {way_out[0]['class']} at {way_out[0]['distance']:.0f} units")
            for _ in range(30):
                gap = approach(pad, me, (way_out[0]["x"], way_out[0]["z"]), tolerance=2.5, seconds=0.4)
                pad.press("a", 0.3)
                time.sleep(0.4)
                now_floor = int.from_bytes(S.read_memory(0x805D5FC0, 4), "big")
                if now_floor != start_floor:
                    log(f"AREA CLEARED: floor {start_floor} -> {now_floor}")
                    start_floor = now_floor
                    break
                if gap is not None and gap < 3:
                    break
            continue
        foes, switches = entities()
        live = [switch for switch in switches if switch["state"] != 2]
        if live:
            target = live[0]
            log(f"switch {target['class']} state {target['state']} at {target['distance']:.0f} units")
            for attempt in range(10):
                gap = approach(pad, me, (target["x"], target["z"]), tolerance=2.5)
                pad.press("a", 0.28)
                time.sleep(0.25)
                _f, again = entities()
                now = next((row for row in again if row["class"] == target["class"]
                            and math.dist((row["x"], row["z"]), (target["x"], target["z"])) < 8), None)
                state = now["state"] if now else None
                log(f"  step+press x{attempt + 1}: at {gap if gap is None else round(gap, 1)} units, state {state}")
                if state == 2 or now is None:
                    log("  switch handled")
                    break
            continue
        if foes:
            target = foes[0]
            log(f"enemy {target['class']} hp {target['hp']} at {target['distance']:.0f} units")
            for attempt in range(12):
                gap = approach(pad, me, (target["x"], target["z"]), tolerance=3.0)
                pad.press("a", 0.3)
                if gap is not None and gap > 25:
                    pad.press("b", 0.3)
                time.sleep(0.2)
                _f, _s = entities()
                still = next((row for row in _f if row["class"] == target["class"]), None)
                if still is None:
                    log("  enemy down")
                    break
                target = still
            continue
        room_list = rooms_for(int.from_bytes(S.read_memory(0x805D5FC0, 4), "big"))
        if room_list:
            if target_room is None:
                target_room = min(room_list, key=lambda room: math.dist((me[0], me[2]), tuple(room["centre"])))["room"]
            room = next(row for row in room_list if row["room"] == target_room)
            centre = (room["centre"][0], room["centre"][1])
            log(f"heading for room {target_room}")
            for _ in range(40):
                gap = approach(pad, me, centre, tolerance=20.0, seconds=0.4)
                if gap is None or gap < 25:
                    log(f"  room {target_room} reached")
                    target_room = None
                    break
                if OP.operator_active():
                    break
            else:
                log("  could not reach it - trying another room")
                target_room = None
            continue
        time.sleep(0.8)
    pad.reset()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(float(sys.argv[1]) if len(sys.argv) > 1 else 3600.0))
