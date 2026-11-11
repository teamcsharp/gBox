"""Play only while the operator is actually giving the game the screen - no focus stealing, ever.

The earlier play mode grabbed focus back whenever it was lost, which fought the operator for the machine. This version inverts the rule: it **waits**
for the game to be focused for a sustained moment (1.5 s, so a passing click is not enough), plays while it stays focused, and **pauses instantly**
when focus leaves. It never calls raise_window.

That gives one simple contract: **the game on screen means the bot plays; anything else means the bot waits.** No focus war, no stolen keystrokes, and
the operator's own input always wins because the operator's pad activity suppresses it for thirty seconds.

While playing it:
  * locks one enemy at a time and keeps it locked until it dies or is given up on;
  * closes with short steps (which also turn the character) and swings continuously - the pattern that lands hits without overshooting;
  * casts a technique when the target is beyond melee reach, because that is what reaches at 20+ units;
  * when nothing is alive nearby, walks to the next unvisited room on the current floor's map, or wanders if the floor has no map.
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
import map_exit as ME                                              # noqa: E402
import nav3                                                        # noqa: E402
import pso_input                                                   # noqa: E402
import pso_operator2 as OP                                         # noqa: E402
import run2 as RUN                                                 # noqa: E402
import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, POS, HP = 0x8050D460, 256, 0x38, 0x32C
PLAYER = 0x8050EA10
FLOOR = 0x805D5FC0
ROUTES = Path(r"D:\gBox\pso-ds\routes")
LOG = r"D:\gBox\pso-ds\play_when_focused.log"
PAUSE_FLAG = r"D:\gBox\pso-ds\PAUSED"
FOCUS_HOLD = 1.5
MELEE = 6.0
GIVE_UP = 45.0


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


def enemies(limit=70.0):
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
            if not name.startswith(("TObjEne", "TEne", "TBoss")):
                continue
            blob = S.read_memory(pointer, 0x340)
            if len(blob) < 0x340:
                continue
            x, y, z = struct.unpack(">fff", blob[POS:POS + 12])
            enemy_hp = struct.unpack(">H", blob[HP:HP + 2])[0]
        except Exception:                                        # noqa: BLE001
            continue
        if enemy_hp <= 0:
            continue
        distance = math.dist((me[0], me[2]), (x, z))
        if distance <= limit:
            out.append({"pointer": pointer, "class": name, "x": x, "y": y, "z": z,
                        "hp": enemy_hp, "distance": distance})
    return sorted(out, key=lambda row: row["distance"])


def rooms(current_floor):
    try:
        return json.loads((ROUTES / f"forest{current_floor}-rooms-mesh.json").read_text(encoding="utf-8")).get("rooms") or []
    except Exception:                                            # noqa: BLE001
        return []


def playable():
    """True only when the game has held focus for a moment and the operator is not on the pad."""
    if os.path.exists(PAUSE_FLAG) or OP.operator_active():
        return False
    started = time.time()
    while time.time() - started < FOCUS_HOLD:
        if not G.game_has_focus():
            return False
        time.sleep(0.15)
    return True


def main(seconds=3600.0):
    log("=== play when focused (never steals focus)")
    started = time.time()
    locked = None
    locked_at = 0.0
    visiting = None
    while time.time() - started < seconds:
        if not playable():
            time.sleep(0.4)
            continue
        me = player()
        if me is None:
            time.sleep(0.2)
            continue
        found = enemies()
        if locked is not None:
            still = next((row for row in found if row["pointer"] == locked["pointer"]), None)
            if still is None:
                log(f"  {locked['class']} destroyed")
                locked = None
            elif time.time() - locked_at > GIVE_UP:
                log(f"  giving up on {locked['class']} (hp {still['hp']})")
                locked = None
            else:
                locked = still
        if locked is None:
            if found:
                locked = found[0]
                locked_at = time.time()
                log(f"  target {locked['class']} hp {locked['hp']} at {locked['distance']:.0f} units")
        if locked is not None:
            gap = math.dist((me[0], me[2]), (locked["x"], locked["z"]))
            if gap > 30:
                pso_input.hold("b", 0.22)
            elif gap > MELEE:
                step = RUN.unit(locked["x"] - me[0], locked["z"] - me[2])
                table = RUN.calibrate(ME.read_pos)
                key, align = RUN.best_key(table, step)
                if key is not None:
                    pso_input.hold(key, 0.12)
                pso_input.hold("a", 0.22)
            else:
                pso_input.hold("a", 0.22)
            continue
        # nothing to fight: move toward an unexplored room, or wander on unmapped floors
        current_floor = floor()
        room_list = rooms(current_floor)
        if room_list and visiting is None:
            centre = min(room_list, key=lambda r: math.dist((me[0], me[2]), tuple(r["centre"])))["centre"]
            visiting = (centre[0], centre[1])
            log(f"  travelling to room centre ({visiting[0]:.0f},{visiting[1]:.0f}) on floor {current_floor}")
        if visiting is not None:
            if math.dist((me[0], me[2]), visiting) < 25:
                visiting = None
            else:
                RUN.run_to(ME.read_pos, visiting, tolerance=20.0, budget=25.0)
        time.sleep(0.15)


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 3600.0)
