"""Name every entity in the room, so the bot can tell an enemy from a door.

`pso_class_registry` documents the identity rule: *"A class's vtable begins with a pointer to its registry slot (`TABLE_ADDRESS + index*4`)"*.
So for each entity: read its vtable (at +0x18), read that vtable's first word, and if the word lies inside the 240-slot class table, the index names the class.

That turns the 40 anonymous objects the table holds into named things - `TObjPlayer`, a switch, a door, or an enemy - which is the difference between a bot that
can pick a target and one that stands in a room taking hits.
"""
import json
import struct
import sys
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\.tmp")
sys.path.insert(0, r"C:\_tools\gBox\system")

import session as S                                                # noqa: E402
from gbox import pso_class_registry                              # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
TABLE, COUNT, STRUCT = 0x8050D460, 256, 0x340
POS, HP, ANGLE = 0x38, 0x330, 0x44
CLASS_TABLE = pso_class_registry.TABLE_ADDRESS
CLASS_SLOTS = pso_class_registry.SLOTS
NAMES = pso_class_registry.CLASS_NAMES


def rpc(sid, op, args):
    request = urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions/%s/rpc" % sid,
        data=json.dumps({"op": op, "args": args}).encode(), method="POST",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=30).read() or b"null")


def read(sid, address, length):
    try:
        return bytes.fromhex(rpc(sid, "read_memory", {"address": address, "length": length}))
    except Exception:                                             # noqa: BLE001
        return b""


def class_of(sid, vtable):
    """vtable -> class name through its first word (the registry slot pointer), or None."""
    if not (0x80000000 <= vtable < 0x81800000):
        return None, None
    word = read(sid, vtable, 4)
    if len(word) != 4:
        return None, None
    slot = struct.unpack(">I", word)[0]
    if not (CLASS_TABLE <= slot < CLASS_TABLE + CLASS_SLOTS * 4):
        return None, None
    index = (slot - CLASS_TABLE) // 4
    return index, NAMES[index] if index < len(NAMES) else f"class_{index:#04x}"


if __name__ == "__main__":
    rows = json.loads(urllib.request.urlopen(urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"}), timeout=20).read())
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    sid = next(row["session_id"] for row in rows if row.get("state") in ("running", "starting"))

    blob = read(sid, TABLE, COUNT * 4)
    pointers = struct.unpack(">%dI" % COUNT, blob)
    live = [(i, p) for i, p in enumerate(pointers) if 0x80000000 <= p < 0x81800000]
    print(f"session {sid}\n{len(live)} live entities\n")

    named, unnamed = [], []
    print("slot  ptr         vtable      class                      x        z       hp")
    for index, pointer in live:
        head = read(sid, pointer, 0x1C)
        if len(head) < 0x1C:
            continue
        vtable = struct.unpack_from(">I", head, 0x18)[0]
        body = read(sid, pointer + POS, 12)
        if len(body) != 12:
            continue
        x, y, z = struct.unpack(">fff", body)
        hp_raw = read(sid, pointer + HP, 2)
        hp = struct.unpack(">H", hp_raw)[0] if len(hp_raw) == 2 else -1
        cls_index, cls = class_of(sid, vtable)
        label = cls or f"?(vt 0x{vtable:08X})"
        (named if cls else unnamed).append((index, pointer, vtable, cls_index, cls, x, z, hp))
        print(f"{index:4d}  0x{pointer:08X}  0x{vtable:08X}  {label:26s} {x:8.1f} {z:8.1f} {hp:6d}")

    print(f"\nnamed: {len(named)}  unnamed: {len(unnamed)}")
    counts = {}
    for row in named:
        counts[row[4]] = counts.get(row[4], 0) + 1
    print("\nclass histogram:")
    for name, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {count:3d}  {name}")

    enemies = [row for row in named if row[4] and ("Enemy" in row[4] or "enemy" in row[4])]
    print(f"\nentities whose class name contains 'Enemy': {len(enemies)}")
    for row in enemies[:10]:
        print(f"  slot {row[0]} {row[4]} at ({row[5]:.0f}, {row[6]:.0f}) hp {row[7]}")
