"""Find the real class pointer inside an entity, instead of assuming offset 0x18.

Assuming +0x18 named 0 of 125 entities, so that field is not the vtable. The registry's rule is that a class vtable's **first word** points at its slot in the class
table at 0x805D3138. So this searches each entity's first 0x60 bytes for a word that:

  1. looks like a code/data pointer (0x80000000-0x81800000), and
  2. whose own first word lies inside the 240-slot class table.

The offset that resolves the most entities is the class pointer, and each hit names the class. That is the identity the bot needs to tell an enemy from a door.
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
TABLE, COUNT = 0x8050D460, 256
POS, HP = 0x38, 0x330
CLASS_TABLE = pso_class_registry.TABLE_ADDRESS
CLASS_SLOTS = pso_class_registry.SLOTS
NAMES = pso_class_registry.CLASS_NAMES
HEAD = 0x60


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


if __name__ == "__main__":
    rows = json.loads(urllib.request.urlopen(urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"}), timeout=20).read())
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    sid = next(row["session_id"] for row in rows if row.get("state") in ("running", "starting"))

    blob = read(sid, TABLE, COUNT * 4)
    pointers = struct.unpack(">%dI" % COUNT, blob)
    live = [p for p in pointers if 0x80000000 <= p < 0x81800000]
    print(f"{len(live)} live entities; searching {HEAD:#x} bytes each\n")

    # first pass: count how often each offset yields a class-table hit
    votes = {}
    samples = {}
    for pointer in live:
        head = read(sid, pointer, HEAD)
        if len(head) != HEAD:
            continue
        for offset in range(0, HEAD - 4, 4):
            candidate = struct.unpack_from(">I", head, offset)[0]
            if not (0x80000000 <= candidate < 0x81800000):
                continue
            word = read(sid, candidate, 4)
            if len(word) != 4:
                continue
            slot = struct.unpack(">I", word)[0]
            if CLASS_TABLE <= slot < CLASS_TABLE + CLASS_SLOTS * 4:
                votes[offset] = votes.get(offset, 0) + 1
                samples.setdefault(offset, candidate)

    print("offset -> class-table hits:")
    for offset, count in sorted(votes.items(), key=lambda kv: -kv[1]):
        print(f"  +0x{offset:02X}: {count:3d} hits  (sample vtable 0x{samples[offset]:08X})")

    if not votes:
        raise SystemExit("\nno offset resolved a class; the identity rule does not apply to live objects")

    best = max(votes, key=votes.get)
    print(f"\nusing +0x{best:02X}\n")
    print("slot  ptr         class                      x        z       hp")
    histogram = {}
    for pointer in live:
        head = read(sid, pointer, max(HEAD, best + 4))
        if len(head) < best + 4:
            continue
        vtable = struct.unpack_from(">I", head, best)[0]
        word = read(sid, vtable, 4)
        if len(word) != 4:
            continue
        slot = struct.unpack(">I", word)[0]
        if not (CLASS_TABLE <= slot < CLASS_TABLE + CLASS_SLOTS * 4):
            continue
        index = (slot - CLASS_TABLE) // 4
        name = NAMES[index] if index < len(NAMES) else f"class_{index:#04x}"
        body = read(sid, pointer + POS, 12)
        if len(body) != 12:
            continue
        x, y, z = struct.unpack(">fff", body)
        hp_raw = read(sid, pointer + HP, 2)
        hp = struct.unpack(">H", hp_raw)[0] if len(hp_raw) == 2 else -1
        histogram[name] = histogram.get(name, 0) + 1
        print(f"{live.index(pointer):4d}  0x{pointer:08X}  {str(name):26s} {x:8.1f} {z:8.1f} {hp:6d}")

    print("\nclass histogram:")
    for name, count in sorted(histogram.items(), key=lambda kv: -kv[1]):
        print(f"  {count:3d}  {name}")
