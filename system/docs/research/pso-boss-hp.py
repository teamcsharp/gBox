"""Read boss HP straight from RAM through the semantic profile's entity table (CP18's accept signal).

Profile pso-gc-plus-us: entity table 0x8050D460 (256 pointers, null-terminated, struct 0x340); class name is a pointer-string at
+0x0; enemy/boss kinds match TBoss/TObjBoss/TObjEne with hp u16 @0x32C and hp_max u16 @0x2B8. This walks the table and prints every
boss/enemy entity with its HP, position and class, so "the boss's HP reaches 0" can be measured instead of inferred.
"""
import json
import struct
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\system")

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "75cf966f35164149-4ec5d512e3484b02"
TABLE = 0x8050D460
MAX_ENTRIES = 256
HP, HP_MAX = 0x32C, 0x2B8
PREFIXES = ("TBoss", "TObjBoss", "TObjEne")


def read(address, length):
    body = json.dumps({"op": "read_memory", "args": {"address": address, "length": length}}).encode()
    req = urllib.request.Request(f"{API}/api/sessions/{SID}/rpc", data=body, method="POST",
                                 headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                          "content-type": "application/json"})
    return bytes.fromhex(json.loads(urllib.request.urlopen(req, timeout=15).read() or b'""'))


def cstring(address, limit=48):
    raw = read(address, limit)
    return raw.split(b"\x00")[0].decode("ascii", "replace") if raw else ""


def entities():
    raw = read(TABLE, MAX_ENTRIES * 4)
    out = []
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if pointer == 0:
            continue
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        name_pointer = int.from_bytes(read(pointer, 4), "big")
        if not (0x80000000 <= name_pointer < 0x81800000):
            continue
        name = cstring(name_pointer)
        if not name:
            continue
        out.append({"index": index, "pointer": pointer, "class": name})
    return out


def entity_fields(pointer):
    hp = int.from_bytes(read(pointer + HP, 2), "big")
    hp_max = int.from_bytes(read(pointer + HP_MAX, 2), "big")
    x, y, z = struct.unpack(">fff", read(pointer + 0x38, 12))
    return {"hp": hp, "hp_max": hp_max, "x": round(x, 1), "y": round(y, 1), "z": round(z, 1)}


def boss_rows():
    rows = []
    for ent in entities():
        if any(ent["class"].startswith(prefix) for prefix in PREFIXES):
            rows.append({**ent, **entity_fields(ent["pointer"])})
    return rows


def main():
    for sample in range(6):
        rows = boss_rows()
        print(f"--- sample {sample} {time.strftime('%H:%M:%S')}: {len(rows)} boss/enemy entities")
        for row in rows[:12]:
            frac = f"{row['hp'] / row['hp_max']:.2f}" if row["hp_max"] else "-"
            print(f"   [{row['index']:>3}] {row['class'][:28]:<28} hp={row['hp']:>6}/{row['hp_max']:<6} ({frac}) "
                  f"pos=({row['x']:.1f},{row['y']:.1f},{row['z']:.1f})")
        time.sleep(6)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
