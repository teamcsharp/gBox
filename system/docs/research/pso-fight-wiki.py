"""Fight the way the wiki says: stand your ground and swing as the Booma walks into you.

Ephinea's Booma page: "Boomas will move towards players once their aggro radius has been entered or they've been struck. They'll walk directly
toward their target and begin attacking when they reach it." And for hunters: "it may be necessary to fight them with only normal attacks, or, if
using a longer weapon, attack just as they come into range."

So the tactic is not to chase a moving target. It is:
  1. turn toward the enemy (a short step toward it faces the character);
  2. stop and swing in a 3-hit combo rhythm when it is within reach;
  3. let it walk in - it comes to you.

This replaces `attack_while_stepping` for the fight step: stepping while swinging keeps the character moving past a target that is closing anyway.
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
REACH = 11.0                                                        # let it walk in this far
FACE_STEP = 0.12                                                    # a brief step turns the character toward the enemy


def nearest_enemy(point, limit=40.0):
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
            hp = struct.unpack(">H", blob[HP:HP + 2])[0]
        except Exception:                                        # noqa: BLE001
            continue
        distance = math.dist(point, (x, z))
        if distance <= limit and (best is None or distance < best[0]):
            best = (distance, {"class": name, "x": x, "z": z, "hp": hp})
    return best


def swing_combo(rounds=3, gap=0.42):
    """Normal attacks in rhythm - the wiki notes a mistimed combo lets the Booma counter."""
    for _ in range(rounds):
        if not pso_input.allowed():
            return
        pso_input.hold("a", 0.22)
        time.sleep(gap)


def fight(enemy, timeout=25.0):
    started = time.time()
    while time.time() - started < timeout:
        if not pso_input.allowed():
            return None
        point = ME.read_pos()
        if point is None:
            return None
        target = nearest_enemy(point, limit=40.0)
        if target is None:
            return "gone"
        gap, current = target
        if gap > REACH:
            # close the distance with real pathing, then stop and let it come
            RUN.run_to(ME.read_pos, (current["x"], current["z"]), tolerance=REACH - 1, budget=6.0)
            continue
        # face it with a brief step, then stand and swing
        move = RUN.unit(current["x"] - point[0], current["z"] - point[1])
        table = RUN.calibrate(ME.read_pos)
        key, align = RUN.best_key(table, move)
        if key is not None:
            pso_input.hold(key, FACE_STEP)
        swing_combo(rounds=3)
        after = nearest_enemy(ME.read_pos(), limit=40.0)
        if after is None:
            return "gone"
        if after[1]["hp"] < current["hp"]:
            print(f"    damage: {current['hp']} -> {after[1]['hp']}")
    return "timeout"


if __name__ == "__main__":
    print("== stand-and-swing fight test (wiki tactic)")
    point = ME.read_pos()
    entry = nearest_enemy(point)
    print("nearest:", entry)
    if entry:
        result = fight(entry[1])
        print("result:", result)
