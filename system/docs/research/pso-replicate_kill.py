"""Replicate the operator's demonstration: fire, and the enemy dies.

Their combat log shows one-shot kills at 11, 21, 36 and 69 units with height differences up to 11 - so neither exact range nor exact facing mattered,
because a single attack carries enough damage (crit + stacked weapon effects) to remove a Forest enemy outright. The bot's failures came from trying
to close and aim with melee when the weapon in hand already kills at range.

This fires at the nearest enemy repeatedly and records the HP series, so the same result either reproduces or the difference is visible.
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


def enemies(limit=120.0):
    me = player()
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
            hp = struct.unpack(">H", blob[HP:HP + 2])[0]
        except Exception:                                        # noqa: BLE001
            continue
        distance = math.dist((me[0], me[2]), (x, z))
        if distance <= limit:
            out.append({"pointer": pointer, "class": name, "x": x, "y": y, "z": z,
                        "hp": hp, "distance": distance})
    return sorted(out, key=lambda row: row["distance"])


print("weapons equipped:")
reply = S.controls("list", {}, timeout=40)
rows = (reply.get("inventory") if isinstance(reply, dict) else reply) or []
print("  ", [(r.get("name"), r.get("code")) for r in rows if r.get("equipped") and str(r.get("code", "")).startswith("00")])

found = enemies()
print(f"enemies in range: {[(row['class'], row['hp'], round(row['distance'])) for row in found[:4]]}")
if not found:
    raise SystemExit("no enemies - move closer or clear another room")
target = found[0]
print(f"\nfiring at {target['class']} hp {target['hp']} at {target['distance']:.0f} units")
for shot in range(10):
    if not pso_input.allowed():
        print("operator took the pad")
        break
    pso_input.hold("a", 0.28)
    time.sleep(0.42)
    now = enemies()
    same = next((row for row in now if row["pointer"] == target["pointer"]), None)
    print(f"  shot {shot + 1}: hp {same['hp'] if same else 'gone'}")
    if same is None or same["hp"] == 0:
        print("  KILLED by firing")
        break
