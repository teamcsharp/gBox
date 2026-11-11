"""Tight melee: short steps toward the enemy, swinging continuously, so the character stays in reach.

Measured on the Shark fight: damage landed (85 -> 69) but only on one attempt in five, because `run_to` overshoots a moving target - the distance went
18 -> 12 -> 23 -> 12 -> 14 as the character ran past and came back. The enemy is reachable and the swing works; what fails is staying inside reach.

So this does the opposite of a long stride: every cycle it reads the enemy's position, takes a **0.12 s step** toward it (which also turns the
character, since PSO faces the direction of travel) and swings. Short steps mean the character cannot overshoot, and continuous swings mean the
enemy stays staggered - the stun-lock the operator described.

It logs every damaging hit so the exchange is visible, and stops when the operator takes the pad.
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
STEP = 0.12
SWING = 0.22
LOG = r"D:\gBox\pso-ds\melee_loop.log"


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def nearest():
    me = ME.read_pos()
    if me is None:
        return None
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
            best = (round(distance, 1), name, enemy_hp, (x, z), pointer)
    return best


def main(seconds=900.0):
    log("=== tight melee loop")
    started = time.time()
    memory = {}
    while time.time() - started < seconds:
        if not pso_input.allowed():
            time.sleep(0.25)
            continue
        target = nearest()
        if target is None:
            time.sleep(0.6)
            continue
        distance, name, enemy_hp, position, pointer = target
        previous = memory.get(pointer)
        if previous is not None and enemy_hp < previous:
            log(f"  hit {name}: {previous} -> {enemy_hp} at {distance} units")
        memory[pointer] = enemy_hp
        me = ME.read_pos()
        if me is None:
            continue
        # a short step toward the enemy both closes the gap and turns the character to face it
        step = RUN.unit(position[0] - me[0], position[1] - me[1])
        table = RUN.calibrate(ME.read_pos)
        key, align = RUN.best_key(table, step)
        if key is not None and distance > 3.0:
            pso_input.hold(key, STEP)
        pso_input.hold("a", SWING)
        time.sleep(0.12)


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 900.0)
