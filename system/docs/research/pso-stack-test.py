"""Test whether the five stacked weapons are what stops the attack landing.

`multi_equip` reports "Weapon effects stacked" and five copies are equipped. A weapon whose effect is applied five times may leave the attack
animation or its damage callback in a state the game ignores, which would explain an enemy at 13 units whose HP never moves even though movement
input works. This unequips four of the five, then swings again and reads the enemy HP.
"""
import json
import struct
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import map_exit as ME                                              # noqa: E402
import pso_input                                                   # noqa: E402
import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, POS, HP = 0x8050D460, 256, 0x38, 0x32C


def inventory():
    reply = S.controls("list", {}, timeout=40)
    return (reply.get("inventory") if isinstance(reply, dict) else reply) or []


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


rows = inventory()
weapons = [row for row in rows if str(row.get("code", "")).startswith("00") and row.get("equipped")]
print(f"equipped weapons: {[(row.get('slot'), row.get('name')) for row in weapons]}")
for row in weapons[1:]:
    try:
        reply = S.controls("multi_equip", {"target": str(row.get("slot")), "on": False}, timeout=60)
        print(f"  unequip slot {row.get('slot')}: {reply.get('message') if isinstance(reply, dict) else reply}")
    except Exception as exc:                                      # noqa: BLE001
        print(f"  unequip slot {row.get('slot')} refused: {str(exc)[:80]}")
    time.sleep(0.3)
rows = inventory()
print(f"equipped now: {[(row.get('slot'), row.get('name')) for row in rows if row.get('equipped')]}")

entry = nearest_enemy()
print(f"\nenemy before: hp {entry[1]['hp']} at {entry[0]:.1f} units" if entry else "no enemy")
for attempt in range(6):
    pso_input.hold("a", 0.3)
    time.sleep(1.0)
    entry = nearest_enemy()
    if entry is None:
        print("  enemy gone")
        break
    print(f"  swing {attempt + 1}: hp {entry[1]['hp']} at {entry[0]:.1f} units")
    if entry[1]["hp"] < 30:
        print("  DAMAGE LANDED")
        break
