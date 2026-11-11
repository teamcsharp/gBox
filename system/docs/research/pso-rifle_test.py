"""Equip the rifle, drop the melee weapons, and fire at the wolf from range.

Codes measured by scanning the classes: 000600 Handgun, 000700 Rifle, 000800 Mechgun, 000900 Shot. A gun's A button fires at the target in front of
the character, so ranged combat replaces chasing a circling wolf.

This equips the rifle, unequips every other weapon, then fires a burst and reports the wolf's HP before and after - the check that ranged damage
actually lands.
"""
import json
import math
import struct
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import pso_input                                                   # noqa: E402
import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, POS, HP = 0x8050D460, 256, 0x38, 0x32C
PLAYER = 0x8050EA10


def inventory():
    reply = S.controls("list", {}, timeout=40)
    return (reply.get("inventory") if isinstance(reply, dict) else reply) or []


def nearest():
    pointer = int.from_bytes(S.read_memory(PLAYER, 4), "big")
    blob = S.read_memory(pointer + POS, 12)
    me = struct.unpack(">fff", blob)
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    best = None
    for index in range(MAX_ENTRIES):
        p = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= p < 0x81800000):
            continue
        try:
            np = int.from_bytes(S.read_memory(p, 4), "big")
            name = S.read_memory(np, 32).split(b"\x00")[0].decode("ascii", "replace")
            if not name.startswith(("TObjEne", "TEne")):
                continue
            b = S.read_memory(p, 0x340)
            x, y, z = struct.unpack(">fff", b[POS:POS + 12])
            hp = struct.unpack(">H", b[HP:HP + 2])[0]
        except Exception:                                        # noqa: BLE001
            continue
        d = math.dist((me[0], me[2]), (x, z))
        if best is None or d < best[0]:
            best = (d, {"class": name, "x": x, "z": z, "y": y, "hp": hp})
    return best


rows = inventory()
rifle = next((row for row in rows if str(row.get("code")) == "000700"), None)
print("rifle row:", rifle and {"slot": rifle.get("slot"), "id": rifle.get("id")})
if rifle:
    try:
        print("equip rifle:", json.dumps(S.controls("multi_equip", {"target": str(rifle["slot"]), "on": True}, timeout=60))[:140])
    except Exception as exc:                                      # noqa: BLE001
        print("equip refused:", str(exc)[:100])
for row in inventory():
    if row.get("equipped") and str(row.get("code", "")).startswith("00") and str(row.get("code")) != "000700":
        try:
            reply = S.controls("multi_equip", {"target": str(row.get("slot")), "on": False}, timeout=60)
            print(f"unequip {row.get('name')} slot {row.get('slot')}: {reply.get('message') if isinstance(reply, dict) else reply}")
        except Exception as exc:                                  # noqa: BLE001
            print(f"unequip {row.get('name')} refused: {str(exc)[:80]}")
        time.sleep(0.2)

entry = nearest()
print("\ntarget:", entry)
if entry:
    before_hp = entry[1]["hp"]
    for burst in range(4):
        pso_input.hold("a", 0.25)
        time.sleep(0.55)
        after = nearest()
        print(f"  burst {burst + 1}: nearest {after[0]:.1f} units hp {after[1]['hp'] if after else 'gone'}")
        if after is None or after[1]["hp"] < before_hp:
            print(f"  DAMAGE: {before_hp} -> {after[1]['hp'] if after else 'dead'}")
            break
