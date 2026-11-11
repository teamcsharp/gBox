"""Find the door state field: aligned 4-byte words with small values, where the known-unlocked door differs from every other door.

The first pass matched positions/rotations/IDs. State fields are small integers, so this pass keeps only aligned 4-byte words whose
value is <= 64 (or -1) and prints the full value column across all doors for each candidate, so the pattern is visible.
"""
import json
import struct
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\system")

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "e731ee594dde4a89-cae9dad929a34d17"
TABLE, MAX_ENTRIES, STRUCT = 0x8050D460, 256, 0x340
KNOWN_UNLOCKED = (253.0, 92.0)


def read(address, length):
    body = json.dumps({"op": "read_memory", "args": {"address": address, "length": length}}).encode()
    for attempt in range(4):
        try:
            req = urllib.request.Request(f"{API}/api/sessions/{SID}/rpc", data=body, method="POST",
                                         headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                                  "content-type": "application/json"})
            return bytes.fromhex(json.loads(urllib.request.urlopen(req, timeout=12).read() or b'""'))
        except Exception:                                        # noqa: BLE001
            time.sleep(0.2)
    return b""


def cstring(address, limit=40):
    raw = read(address, limit)
    return raw.split(b"\x00")[0].decode("ascii", "replace") if raw else ""


def doors():
    raw = read(TABLE, MAX_ENTRIES * 4)
    out = []
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        name_pointer = int.from_bytes(read(pointer, 4), "big")
        if not (0x80000000 <= name_pointer < 0x81800000):
            continue
        name = cstring(name_pointer)
        if not name.startswith("TObjDoor"):
            continue
        blob = read(pointer, STRUCT)
        x, y, z = struct.unpack(">fff", blob[0x38:0x44])
        out.append({"index": index, "class": name, "x": x, "y": y, "z": z, "blob": blob})
    return out


def small_values(blob):
    values = {}
    for offset in range(0, len(blob) - 3, 4):
        (word,) = struct.unpack(">i", blob[offset:offset + 4])
        if -1 <= word <= 64:
            values[offset] = word
    return values


def main():
    rows = doors()
    target = None
    for row in rows:
        if ((row["x"] - KNOWN_UNLOCKED[0]) ** 2 + (row["z"] - KNOWN_UNLOCKED[1]) ** 2) ** 0.5 < 8:
            target = row
    if target:
        where = "index %d at (%.0f,%.0f)" % (target["index"], target["x"], target["z"])
    else:
        where = "NOT FOUND"
    print("doors %d; unlocked target: %s" % (len(rows), where))
    if target is None:
        return 2
    others = [r for r in rows if r is not target]
    target_values = small_values(target["blob"])
    candidates = []
    for offset, value in target_values.items():
        other_values = [small_values(r["blob"]).get(offset) for r in others]
        if value in other_values:
            continue
        candidates.append((offset, value, other_values))
    print(f"candidates (aligned words <=64 that differ from every other door): {len(candidates)}")
    for offset, value, other_values in candidates:
        print(f"  {hex(offset):>6} unlocked={value:>3}   others={other_values}")
    with open(r"D:\gBox\pso-ds\door-flags.json", "w", encoding="utf-8") as fh:
        json.dump({"unlocked": {"index": target["index"], "x": target["x"], "z": target["z"]},
                   "candidates": [{"offset": hex(o), "unlocked": v, "others": ov} for o, v, ov in candidates]},
                  fh, indent=1)
    print("wrote D:\\gBox\\pso-ds\\door-flags.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
