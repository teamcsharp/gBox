"""Map the player-data block at TObjPlayer+0xC00: known base stats first, then hunt the technique array.

Known: +0xC00 is the character base-stats u16 block in the order atp mst evp hp dfp ata lck (pso_mods_tool.BASE_STATS/STATS).
This dumps 2 KB from there, prints the stats it can identify, then reports every candidate technique array: a run of 19-20 bytes (or
u16s) whose values are all <= 31, with a summary of how many are non-zero - a Lv 2 HUmar should have very few or none learned, so the
pattern to look for is an all-zero 20-run bracketed by plausible fields.
"""
import json
import struct
import sys
import time
import urllib.request

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "e731ee594dde4a89-cae9dad929a34d17"
BASE = 0xC00
STATS = ["atp", "mst", "evp", "hp", "dfp", "ata", "lck"]


def read(address, length):
    body = json.dumps({"op": "read_memory", "args": {"address": address, "length": length}}).encode()
    for _ in range(3):
        try:
            req = urllib.request.Request(f"{API}/api/sessions/{SID}/rpc", data=body, method="POST",
                                         headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                                  "content-type": "application/json"})
            return bytes.fromhex(json.loads(urllib.request.urlopen(req, timeout=10).read() or b'""'))
        except Exception:                                        # noqa: BLE001
            time.sleep(0.12)
    return b""


def main():
    actor = int.from_bytes(read(0x8050EA10, 4), "big")
    print(f"actor {actor:#x}; player data at {actor + BASE:#x}")
    blob = read(actor + BASE, 0x800)
    if len(blob) < 0x100:
        print("read failed")
        return 2
    print("\nbase stats at +0xC00 (u16):")
    for index, name in enumerate(STATS):
        value = struct.unpack(">H", blob[2 * index:2 * index + 2])[0]
        print(f"  {name:>4} = {value}")
    print("\nfirst 128 bytes hex:")
    for row in range(0, 128, 16):
        chunk = blob[row:row + 16]
        print(f"  +{BASE + row:#06x}  {chunk.hex(' ')}  {''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)}")
    print("\nu16 grid +0xC00..+0xC80:")
    for row in range(0, 0x80, 16):
        values = struct.unpack(">8H", blob[row:row + 16])
        print(f"  +{BASE + row:#06x}  " + " ".join(f"{v:5d}" for v in values))
    # candidate technique arrays
    print("\ncandidate 20-byte technique arrays (all values <= 31, at least 15 zeros):")
    found = 0
    for offset in range(0, len(blob) - 20):
        chunk = blob[offset:offset + 20]
        if all(v <= 31 for v in chunk) and sum(1 for v in chunk if v == 0) >= 15:
            print(f"  +{BASE + offset:#06x}  {chunk.hex(' ')}")
            found += 1
            if found >= 25:
                break
    print(f"  ({found} shown)")
    print("\ncandidate 20 x u16 arrays (all values <= 31):")
    found = 0
    for offset in range(0, len(blob) - 40, 2):
        values = struct.unpack(">20H", blob[offset:offset + 40])
        if all(v <= 31 for v in values):
            print(f"  +{BASE + offset:#06x}  " + ",".join(map(str, values)))
            found += 1
            if found >= 15:
                break
    print(f"  ({found} shown)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
