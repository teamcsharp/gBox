"""Play mode: hold the game's focus while playing, and yield the moment the operator takes the pad.

The focus gate protects the operator's typing, but it also means the bot is defenceless whenever another window is in front - which is what happened
when a Shark was left hitting a character that was standing still. The two requirements conflict: keys only reach the game when it has focus, and the
operator needs the PC.

This resolves it explicitly rather than silently:
  * while playing, if the game is not focused the bot **takes focus back** and says so in the log, so the behaviour is visible rather than mysterious;
  * if the operator has touched the pad within THIRTY seconds, the bot does not take focus and does not act - their control always wins;
  * the loop runs for a bounded time and stops on its own, and the PAUSED file stops it immediately.

So the bot plays properly while it is running, and the operator gets the machine back by touching the controller or by stopping the loop.
"""
import math
import struct
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import game_input as G                                             # noqa: E402
import map_bot as MB                                               # noqa: E402
import map_exit as ME                                              # noqa: E402
import nav3                                                        # noqa: E402
import pso_input                                                   # noqa: E402
import pso_operator2 as OP                                         # noqa: E402
import run2 as RUN                                                 # noqa: E402
import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, POS, HP = 0x8050D460, 256, 0x38, 0x32C
PLAYER = 0x8050EA10
MELEE = 7.0
LOG = r"D:\gBox\pso-ds\play_focus.log"
PAUSE_FLAG = r"D:\gBox\pso-ds\PAUSED"


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def player():
    pointer = int.from_bytes(S.read_memory(PLAYER, 4), "big")
    blob = S.read_memory(pointer + POS, 12)
    return struct.unpack(">fff", blob) if len(blob) == 12 else None


def player_hp():
    pointer = int.from_bytes(S.read_memory(PLAYER, 4), "big")
    return struct.unpack(">H", S.read_memory(pointer + HP, 2))[0]


def enemies(limit=90.0):
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


def ensure_focus():
    """Take focus back if the operator is not using the game. Returns True when the game has focus."""
    if G.game_has_focus():
        return True
    if OP.operator_active():
        return False                        # the operator is playing: never steal from them
    if G.raise_window():
        time.sleep(0.3)
        if G.game_has_focus():
            log("  took focus back to play")
            return True
    return False


def main(seconds=900.0):
    log(f"=== play mode: hp {player_hp()}, {len(enemies())} enemies in range")
    locked = None
    started = time.time()
    last_report = 0.0
    while time.time() - started < seconds:
        import os
        if os.path.exists(PAUSE_FLAG):
            log("PAUSED file present - stopping")
            break
        if OP.operator_active():
            time.sleep(0.5)
            continue
        if not ensure_focus():
            time.sleep(0.5)
            continue
        me = player()
        if me is None:
            time.sleep(0.2)
            continue
        found = enemies()
        if locked is not None:
            still = next((row for row in found if row["pointer"] == locked["pointer"]), None)
            if still is None:
                log(f"  {locked['class']} down")
                locked = None
            else:
                locked = still
        if locked is None:
            if not found:
                time.sleep(0.8)
                continue
            locked = found[0]
            log(f"  locking {locked['class']} hp {locked['hp']} at {locked['distance']:.0f} units")
        gap = math.dist((me[0], me[2]), (locked["x"], locked["z"]))
        if gap > 45:
            route, raw_cells, legs = nav3.plan_h((me[0], me[2]), (locked["x"], locked["z"]),
                                                 start_height=me[1], goal_height=locked["y"])
            if route:
                for waypoint in route[1:3]:
                    RUN.run_to(ME.read_pos, (waypoint[0], waypoint[1]), tolerance=8.0, budget=12.0)
                    if not pso_input.allowed():
                        break
            continue
        if gap > MELEE:
            pso_input.hold("b", 0.22)
            time.sleep(0.25)
        MB.attack_while_stepping((locked["x"], locked["z"]), swings=3)
        now = time.time()
        if now - last_report > 20:
            log(f"  fighting {locked['class']} hp {locked['hp']} at {gap:.0f} units; my hp {player_hp()}")
            last_report = now
    log(f"play mode finished: hp {player_hp()}")


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 900.0)
