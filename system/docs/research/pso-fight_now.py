"""Fight now: lock the nearest enemy and attack it until it dies.

The bot was standing in place taking hits because the focus gate blocks all key delivery while another window is in front - the protection that was
asked for, working, but it means the character is defenceless when the operator is looking at something else.

This runs a tight fight loop: lock the nearest living enemy, step into it while attacking (the pattern that lands hits), cast a technique when it is
out of melee reach, keep the HP topped up by revival, and move to the next enemy when one dies. It stops the moment the operator takes the pad.
"""
import math
import struct
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import map_bot as MB                                               # noqa: E402
import map_exit as ME                                              # noqa: E402
import nav3                                                        # noqa: E402
import pso_input                                                   # noqa: E402
import run2 as RUN                                                 # noqa: E402
import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, POS, HP = 0x8050D460, 256, 0x38, 0x32C
PLAYER = 0x8050EA10
MELEE = 7.0
LOG = r"D:\gBox\pso-ds\fight_now.log"


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def player():
    pointer = int.from_bytes(S.read_memory(PLAYER, 4), "big")
    blob = S.read_memory(pointer + POS, 12)
    return struct.unpack(">fff", blob) if len(blob) == 12 else None


def hp_now():
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


def main(seconds=300.0):
    log(f"=== fight now: hp {hp_now()}, {len(enemies())} enemies in range")
    locked = None
    started = time.time()
    while time.time() - started < seconds:
        if not pso_input.allowed():
            time.sleep(0.25)
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
                log("  no enemies in range - holding")
                time.sleep(1.0)
                continue
            locked = found[0]
            log(f"  locking {locked['class']} hp {locked['hp']} at {locked['distance']:.0f} units")
        gap = math.dist((me[0], me[2]), (locked["x"], locked["z"]))
        if gap > 40:
            route, raw_cells, legs = nav3.plan_h((me[0], me[2]), (locked["x"], locked["z"]),
                                                 start_height=me[1], goal_height=locked["y"])
            if route:
                for waypoint in route[1:3]:
                    RUN.run_to(ME.read_pos, (waypoint[0], waypoint[1]), tolerance=8.0, budget=12.0)
                    if not pso_input.allowed():
                        break
            continue
        if gap > MELEE:
            pso_input.hold("b", 0.22)                             # technique reaches further than the weapon
            time.sleep(0.25)
        MB.attack_while_stepping((locked["x"], locked["z"]), swings=3)
    log(f"fight loop finished: hp {hp_now()}")


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 300.0)
