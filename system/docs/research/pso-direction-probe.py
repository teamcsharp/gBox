"""Which key actually moves the character toward the enemy, and does the distance change at all?

Every fight tactic has failed on the same symptom: the gap to the enemy never closes. This removes every assumption - it reads the exact
positions, computes the bearing to the enemy, then holds each of the four directions for half a second and records how the distance changes. If
no key reduces the distance, the character is blocked and the fight is a movement problem, not a combat one.
"""
import math
import struct
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import map_exit as ME                                              # noqa: E402
import pso_input                                                   # noqa: E402
import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, POS, HP = 0x8050D460, 256, 0x38, 0x32C


def nearest_enemy(limit=60.0):
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
        distance = math.dist(point, (x, z))
        if distance <= limit and (best is None or distance < best[0]):
            best = (distance, {"class": name, "x": x, "y": y, "z": z, "hp": hp})
    return best


point = ME.read_pos()
entry = nearest_enemy()
if entry is None:
    raise SystemExit("no enemy")
gap, enemy = entry
print(f"player {tuple(round(v, 1) for v in point)}  enemy {enemy['class']} "
      f"({enemy['x']:.0f},{enemy['y']:.0f},{enemy['z']:.0f}) hp {enemy['hp']}  gap {gap:.1f}")
dx, dz = enemy["x"] - point[0], enemy["z"] - point[1]
print(f"bearing to enemy: dx {dx:+.1f}  dz {dz:+.1f}")

for key in ("up", "down", "left", "right"):
    before = ME.read_pos()
    pso_input.hold(key, 0.5)
    time.sleep(0.2)
    after = ME.read_pos()
    moved = math.dist(before, after)
    before_gap = math.dist(before, (enemy["x"], enemy["z"]))
    after_gap = math.dist(after, (enemy["x"], enemy["z"]))
    verdict = "toward" if after_gap < before_gap - 0.5 else ("away" if after_gap > before_gap + 0.5 else "sideways")
    print(f"  {key:<5} moved {moved:5.2f}  gap {before_gap:5.1f} -> {after_gap:5.1f}  {verdict}")
    point = after
    entry = nearest_enemy()
    if entry:
        enemy = entry[1]
