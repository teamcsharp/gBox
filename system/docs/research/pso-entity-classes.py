"""List every entity class in the current scene from the entity table, highlighting warp/teleport/gate/door candidates.

The table at 0x8050D460 is what made boss HP readable; the same walk names every object in the arena, so an area-exit warp should
appear by class name with its world position.
"""
import json
import struct
import sys
import time
import urllib.request
from collections import Counter

sys.path.insert(0, r"C:\_tools\gBox\system")

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "75cf966f35164149-4ec5d512e3484b02"
TABLE, MAX_ENTRIES = 0x8050D460, 256
INTEREST = ("warp", "telep", "gate", "door", "portal", "exit", "lift", "pad", "sw")


def read(address, length):
    body = json.dumps({"op": "read_memory", "args": {"address": address, "length": length}}).encode()
    req = urllib.request.Request(f"{API}/api/sessions/{SID}/rpc", data=body, method="POST",
                                 headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                          "content-type": "application/json"})
    return bytes.fromhex(json.loads(urllib.request.urlopen(req, timeout=15).read() or b'""'))


def cstring(address, limit=48):
    raw = read(address, limit)
    return raw.split(b"\x00")[0].decode("ascii", "replace") if raw else ""


def main():
    raw = read(TABLE, MAX_ENTRIES * 4)
    rows = []
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        name_pointer = int.from_bytes(read(pointer, 4), "big")
        if not (0x80000000 <= name_pointer < 0x81800000):
            continue
        name = cstring(name_pointer)
        if not name:
            continue
        x, y, z = struct.unpack(">fff", read(pointer + 0x38, 12))
        rows.append({"index": index, "class": name, "pointer": pointer,
                     "x": round(x, 1), "y": round(y, 1), "z": round(z, 1)})
    print(f"entities: {len(rows)}; classes: {len(set(r['class'] for r in rows))}")
    print("class counts:", dict(Counter(r["class"] for r in rows).most_common(12)))
    print("\ninteresting classes:")
    hits = [r for r in rows if any(k in r["class"].lower() for k in INTEREST)]
    for row in hits[:40]:
        print(f"   [{row['index']:>3}] {row['class'][:32]:<32} pos=({row['x']:8.1f},{row['y']:7.1f},{row['z']:8.1f})")
    if not hits:
        print("   none; listing all classes with positions")
        for row in rows[:40]:
            print(f"   [{row['index']:>3}] {row['class'][:32]:<32} pos=({row['x']:8.1f},{row['y']:7.1f},{row['z']:8.1f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
