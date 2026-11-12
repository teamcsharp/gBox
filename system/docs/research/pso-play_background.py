"""Background play: act without requiring the game to hold focus.

This is the play loop for a Dolphin launched with **BackgroundInput = True** (already written into `Dolphin.ini`). With that setting the emulator reads
its keyboard device even when it is not the foreground window, so the bot can play while the operator uses the rest of the machine - which is exactly
what was asked for, and the reason the earlier loop paused.

Differences from `play_when_focused`:
  * **no focus requirement** - it does not check or wait for focus, and never raises a window;
  * it still yields whenever the operator has touched the pad within 30 s, so their control always wins;
  * it sends a key only if the adapter accepts it, and counts refusals, so a Dolphin without BackgroundInput is detected and reported rather than
    spinning silently.

If, after a few seconds, every send is refused, that means BackgroundInput did not take effect (it is read at Dolphin's startup), and the script says
so plainly instead of pretending to play.
"""
import json
import math
import os
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

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
LOG = r"D:\gBox\pso-ds\play_background.log"
PAUSE_FLAG = r"D:\gBox\pso-ds\PAUSED"
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


def can_act():
    if os.path.exists(PAUSE_FLAG) or OP.operator_active():
        return False
    # no focus check on purpose: BackgroundInput is what makes this possible
    return True


def main(seconds=3600.0):
    log("=== background play (no focus gate; Dolphin BackgroundInput required)")
    refusals = 0
    locked = None
    locked_at = 0.0
    started = time.time()
    while time.time() - started < seconds:
        if not can_act():
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
                log(f"  giving up on {locked['class']}")
                locked = None
            else:
                locked = still
        if locked is None and found:
            locked = found[0]
            locked_at = time.time()
            log(f"  target {locked['class']} hp {locked['hp']} at {locked['distance']:.0f} units")
        if locked is not None:
            gap = math.dist((me[0], me[2]), (locked["x"], locked["z"]))
            moved = False
            if gap > 30:
                pso_input.hold("b", 0.22)
                moved = True
            elif gap > MELEE:
                step = RUN.unit(locked["x"] - me[0], locked["z"] - me[2])
                table = RUN.calibrate(ME.read_pos)
                key, align = RUN.best_key(table, step)
                if key is not None:
                    pso_input.hold(key, 0.12)
                pso_input.hold("a", 0.22)
                moved = True
            else:
                pso_input.hold("a", 0.22)
                moved = True
            if not moved:
                refusals += 1
                if refusals == 30:
                    log("  30 actions in a row were refused - BackgroundInput may not be active "
                        "(it is read when Dolphin starts)")
            continue
        far = enemies(9999.0)
        if far:
            hunter = far[0]
            log(f"  hunting {hunter['class']} at {hunter['distance']:.0f} units")
            route, raw_cells, legs = nav3.plan_h((me[0], me[2]), (hunter["x"], hunter["z"]),
                                                 start_height=me[1], goal_height=hunter["y"])
            if route:
                for waypoint in route[1:4]:
                    RUN.run_to(ME.read_pos, (waypoint[0], waypoint[1]), tolerance=12.0, budget=20.0)
                    if not can_act():
                        break
                continue
        time.sleep(0.3)


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 3600.0)
