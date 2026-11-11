"""Close on the nearest enemy and strike it until it dies - a single, correct fight.

Measured: with focus, `run_to` moved the character 12.96 units, and the nearest enemy sits at the same height 16 units away, so the fight is a matter
of closing and swinging rather than anything exotic. This closes to four units and swings twice per round, reporting the enemy's HP each round so
damage is visible rather than assumed.
"""
import math
import struct
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import map_exit as ME                                              # noqa: E402
import pso_input                                                   # noqa: E402
import run2 as RUN                                                 # noqa: E402
import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, POS, HP = 0x8050D460, 256, 0x38, 0x32C


def nearest():
    me = ME.read_pos()
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    best = None
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
        distance = math.dist((me[0], me[1]), (x, z))
        if best is None or distance < best[0]:
            best = (distance, name, enemy_hp, (x, z), y)
    return best


def main(rounds=12):
    first = nearest()
    if first is None:
        print("no enemies")
        return 1
    print("target:", first[1], "hp", first[2], "at", round(first[0], 1), "units")
    initial = first[2]
    for attempt in range(rounds):
        if not pso_input.allowed():
            print("  not allowed (operator or focus)")
            time.sleep(0.5)
            continue
        target = nearest()
        if target is None:
            print(f"  target gone after {attempt} rounds")
            return 0
        distance, name, enemy_hp, position, enemy_y = target
        if distance > 5.0:
            RUN.run_to(ME.read_pos, position, tolerance=3.5, budget=8.0)
        pso_input.hold("a", 0.25)
        time.sleep(0.30)
        pso_input.hold("a", 0.25)
        time.sleep(0.30)
        after = nearest()
        current = after[2] if after else 0
        print(f"  round {attempt + 1}: {name} hp {current} at "
              f"{after[0] if after else 0:.1f} units")
        if after is None or current < initial:
            if after is None:
                print("  KILLED")
                return 0
            initial = current
            print("  damage landed")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
