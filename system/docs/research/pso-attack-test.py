"""Test which attack form actually damages the enemy: a quick tap versus a held press, facing it.

The engaged Lappy stayed at HP 30 across 14 s of self-play attacks, so the attack is not landing. This measures HP before/after each form:
  1. a quick A tap (what self-play does);
  2. a held A press (0.35 s), which is how a person swings;
  3. a short step toward the enemy first (to face it), then the held press.
"""
import struct
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import learn_live as L                                             # noqa: E402
import map_exit as ME                                              # noqa: E402
import pso_input                                                   # noqa: E402
import run2 as RUN                                                 # noqa: E402
import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, POS, HP = 0x8050D460, 256, 0x38, 0x32C


def nearest_enemy():
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    point = ME.read_pos()
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
            if not name.startswith(("TObjEne", "TEne")):
                continue
            blob = S.read_memory(pointer, 0x340)
            if len(blob) < 0x340:
                continue
            x, y, z = struct.unpack(">fff", blob[POS:POS + 12])
            hp = struct.unpack(">H", blob[HP:HP + 2])[0]
        except Exception:                                        # noqa: BLE001
            continue
        distance = ((x - point[0]) ** 2 + (z - point[1]) ** 2) ** 0.5
        if best is None or distance < best[0]:
            best = (distance, {"class": name, "x": x, "y": y, "z": z, "hp": hp})
    return best


entry = nearest_enemy()
if entry is None:
    raise SystemExit("no enemy")
gap, enemy = entry
print(f"enemy {enemy['class']} hp {enemy['hp']} at {gap:.1f} units")

print("form 1: quick tap")
pso_input.tap("a", gap=0.4)
time.sleep(1.2)
after = nearest_enemy()
print(f"  hp now {after[1]['hp'] if after else 'gone'}")

print("form 2: held press 0.35 s")
pso_input.hold("a", 0.35)
time.sleep(1.2)
after = nearest_enemy()
print(f"  hp now {after[1]['hp'] if after else 'gone'}")

print("form 3: step toward it, then held press")
if after:
    RUN.run_to(ME.read_pos, (after[1]["x"], after[1]["z"]), tolerance=3.0, budget=6.0)
    pso_input.hold("a", 0.35)
    time.sleep(1.2)
    final = nearest_enemy()
    print(f"  hp now {final[1]['hp'] if final else 'gone'}, at "
          f"{final[0]:.1f} units" if final else "  enemy gone")
