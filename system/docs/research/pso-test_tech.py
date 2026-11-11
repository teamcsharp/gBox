"""Test whether a technique (B) is what one-shots enemies at range, rather than the attack button (A).

The operator's captured kills happened at 36.3 and 69.3 units with height differences up to 11.45, and no melee weapon reaches that far - but a
technique does. In PSO the A button attacks with the equipped weapon and the B button casts the technique on the active palette slot, so a
technique is the only action consistent with damage at 69 units.

This reads the enemy's HP, casts (B) and reads it again, then tries A for comparison, so the answer is measured rather than assumed.
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


def player():
    pointer = int.from_bytes(S.read_memory(PLAYER, 4), "big")
    blob = S.read_memory(pointer + POS, 12)
    return struct.unpack(">fff", blob) if len(blob) == 12 else None


def nearest(limit=120.0):
    me = player()
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
        distance = math.dist((me[0], me[2]), (x, z))
        if distance <= limit and (best is None or distance < best[0]):
            best = (distance, {"pointer": pointer, "class": name, "x": x, "y": y, "z": z, "hp": hp})
    return best


def hp_of(pointer):
    found = nearest()
    if not found:
        return None
    same = found[1] if found[1]["pointer"] == pointer else None
    if same is None:
        raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
        for index in range(MAX_ENTRIES):
            p = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
            if p == pointer and 0x80000000 <= p < 0x81800000:
                return struct.unpack(">H", S.read_memory(p + HP, 2))[0]
        return None
    return same["hp"]


# what techniques does the character have?
pointer = int.from_bytes(S.read_memory(PLAYER, 4), "big")
tech_bytes = S.read_memory(pointer + 0x2E7, 20)
print("technique slots:", list(tech_bytes))
print("non-zero techniques:", [(index, value) for index, value in enumerate(tech_bytes) if value])

entry = nearest()
if entry is None:
    raise SystemExit("no enemy in range")
distance, target = entry
print(f"\ntarget {target['class']} hp {target['hp']} at {distance:.1f} units")

print("\n-- casting with B (technique) --")
for attempt in range(4):
    pso_input.hold("b", 0.25)
    time.sleep(0.7)
    now = hp_of(target["pointer"])
    print(f"  B x{attempt + 1}: hp {now if now is not None else 'gone'}")
    if now is None or now < target["hp"]:
        print(f"  TECHNIQUE DAMAGE: {target['hp']} -> {now}")
        break

print("\n-- attacking with A for comparison --")
for attempt in range(2):
    pso_input.hold("a", 0.25)
    time.sleep(0.7)
    now = hp_of(target["pointer"])
    print(f"  A x{attempt + 1}: hp {now if now is not None else 'gone'}")
