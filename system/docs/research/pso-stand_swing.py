"""Stand still and swing: the Booma closes on its own, so no movement is needed.

The wiki: "Boomas will move towards players once their aggro radius has been entered or they've been struck... and begin attacking when they reach
it." Pathing kept overshooting (the gap went 16.9 -> 12.2 -> 24.9 -> 51.8 because long strides carried the character past a moving target), so
this does the opposite: face the enemy with a tiny step, then stand and swing in a combo rhythm for as long as the enemy is in range.

If this damages the Beast, the fight is settled and the bot never needs to chase anything.
"""
import math
import struct
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import pso_input                                                   # noqa: E402
import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, POS, HP = 0x8050D460, 256, 0x38, 0x32C
PLAYER = 0x8050EA10
RANGE = 12.0


def player():
    pointer = int.from_bytes(S.read_memory(PLAYER, 4), "big")
    blob = S.read_memory(pointer + POS, 12)
    return struct.unpack(">fff", blob) if len(blob) == 12 else None


def nearest(limit=40.0):
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    me = player()
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
        distance = math.dist((me[0], me[2]), (x, z))
        if distance <= limit and (best is None or distance < best[0]):
            best = (distance, {"class": name, "x": x, "y": y, "z": z, "hp": hp})
    return best


print("== stand and swing")
started = time.time()
first_hp = None
swings = 0
while time.time() - started < 40:
    if not pso_input.allowed():
        time.sleep(0.3)
        continue
    entry = nearest()
    if entry is None:
        print(f"  t+{time.time() - started:4.0f}s: no enemy in range")
        time.sleep(0.5)
        continue
    gap, enemy = entry
    if first_hp is None:
        first_hp = enemy["hp"]
    me = player()
    if gap > RANGE:
        print(f"  t+{time.time() - started:4.0f}s: {enemy['class']} hp {enemy['hp']} at {gap:.0f} units - waiting for it")
        time.sleep(0.6)
        continue
    pso_input.hold("a", 0.22)
    swings += 1
    time.sleep(0.42)
    if swings % 3 == 0:
        after = nearest()
        print(f"  t+{time.time() - started:4.0f}s: {enemy['class']} hp {after[1]['hp'] if after else 'gone'} "
              f"at {after[0] if after else 0:.0f} units, height {abs(me[1] - enemy['y']):.1f}")
        if after is None or after[1]["hp"] < first_hp:
            print(f"  DAMAGE: {first_hp} -> {after[1]['hp'] if after else 'dead'}")
            break
print(f"swings: {swings}")
