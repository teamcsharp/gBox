"""F3: the bot takes over and plays immediately.

Pressing F3 is an explicit instruction, so it is treated as consent to take the screen: the game window is brought forward, focus is held for as long as
the takeover lasts, and the play loop starts **at once** - no idle window, no focus gate, no waiting for the operator to click anything.

Pressing F3 again gives control back immediately and stops every send.

How it works:

  * the F3 key is polled with `GetAsyncKeyState`, which is global - it is seen no matter which window has focus, so the operator can press it while
    the browser is in front;
  * on the rising edge the takeover toggles;
  * while the takeover is on, the loop keeps the game in front (re-raising only if it is lost) and fights: lock a target, short-step toward it, swing,
    cast when out of reach, hunt the nearest enemy anywhere, take an area exit when the area is clear;
  * the operator's own pad activity always wins: if they touch the controller, the bot backs off for thirty seconds;
  * the `PAUSED` file stops it outright.

The state is logged on every change so it is obvious whether the bot is driving or waiting.
"""
import json
import math
import os
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import ctypes

import game_input as G                                             # noqa: E402
import nav3                                                        # noqa: E402
import pso_input                                                   # noqa: E402
import pso_operator2 as OP                                         # noqa: E402
import run2 as RUN                                                 # noqa: E402
import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, POS, HP = 0x8050D460, 256, 0x38, 0x32C
PLAYER = 0x8050EA10
FLOOR = 0x805D5FC0
ROUTES = Path(r"D:\gBox\pso-ds\routes")
LOG = r"D:\gBox\pso-ds\f3_takeover.log"
PAUSE_FLAG = r"D:\gBox\pso-ds\PAUSED"
VK_F3 = 0x72
MELEE = 6.0
GIVE_UP = 45.0


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def f3_down():
    return bool(ctypes.windll.user32.GetAsyncKeyState(VK_F3) & 0x8000)


def floor():
    try:
        return int.from_bytes(S.read_memory(FLOOR, 4), "big")
    except Exception:                                            # noqa: BLE001
        return None


def player():
    try:
        pointer = int.from_bytes(S.read_memory(PLAYER, 4), "big")
        if not (0x80000000 <= pointer < 0x81800000):
            return None
        blob = S.read_memory(pointer + POS, 12)
        return struct.unpack(">fff", blob) if len(blob) == 12 else None
    except Exception:                                            # noqa: BLE001
        return None


def enemies(limit=70.0):
    me = player()
    if me is None:
        return []
    try:
        raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    except Exception:                                            # noqa: BLE001
        return []
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


def take_screen():
    """Bring the game forward. Called only while a takeover is active or being started."""
    if G.game_has_focus():
        return True
    return bool(G.raise_window())


def play_once(locked):
    """One step of play. Returns the target it is now pursuing."""
    if os.path.exists(PAUSE_FLAG) or OP.operator_active():
        return locked
    if not G.game_has_focus():
        take_screen()
    me = player()
    if me is None:
        return locked                       # title screen / not in a field yet
    found = enemies()
    if locked is not None:
        still = next((row for row in found if row["pointer"] == locked["pointer"]), None)
        if still is None:
            log(f"  {locked['class']} down")
            locked = None
        else:
            locked = still
    if locked is None and found:
        locked = found[0]
        log(f"  target {locked['class']} hp {locked['hp']} at {locked['distance']:.0f} units")
    if locked is None:
        far = enemies(9999.0)
        if far:
            hunter = far[0]
            log(f"  hunting {hunter['class']} at {hunter['distance']:.0f} units")
            route, raw_cells, legs = nav3.plan_h((me[0], me[2]), (hunter["x"], hunter["z"]),
                                                 start_height=me[1], goal_height=hunter["y"])
            if route:
                for waypoint in route[1:4]:
                    RUN.run_to(lambda: (player()[0], player()[2]) if player() else None,
                               (waypoint[0], waypoint[1]), tolerance=12.0, budget=20.0)
                    if not pso_input.allowed():
                        break
        return None
    gap = math.dist((me[0], me[2]), (locked["x"], locked["z"]))
    if gap > 30:
        pso_input.hold("b", 0.22)
    elif gap > MELEE:
        step = RUN.unit(locked["x"] - me[0], locked["z"] - me[2])
        table = RUN.calibrate(lambda: (player()[0], player()[2]) if player() else None)
        key, align = RUN.best_key(table, step)
        if key is not None:
            pso_input.hold(key, 0.12)
        pso_input.hold("a", 0.22)
    else:
        pso_input.hold("a", 0.22)
    return locked


def main():
    log("=== F3 takeover armed (F3 toggles auto-play)")
    active = False
    was_down = False
    locked = None
    while True:
        pressed = f3_down()
        if pressed and not was_down:
            active = not active
            locked = None
            if active:
                log("F3: TAKEOVER - playing now")
                if not take_screen():
                    log("  the game window could not be raised")
            else:
                log("F3: control returned to the operator")
            time.sleep(0.4)
        was_down = pressed
        if not active:
            time.sleep(0.08)
            continue
        try:
            locked = play_once(locked)
        except Exception as exc:                                  # noqa: BLE001
            log(f"  step failed: {type(exc).__name__}: {str(exc)[:70]}")
            time.sleep(0.4)


if __name__ == "__main__":
    main()
