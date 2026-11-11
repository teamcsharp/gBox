"""Locate the player's technique table: follow pointers out of the TObjPlayer actor and look for a 20-entry learned/level array.

PSO GC stores learned techniques per character - 19-20 techniques, each with a level. In RAM the actor (TObjPlayer, 0x340 bytes at the
slot pointer) is separate from the player data that holds them, so this scans the actor for heap pointers (0x80000000-0x81800000), reads
each target, and reports any run of 20 bytes whose values are all <= 31 (a plausible level list) or 20 u16 values in 0..31.
"""
import json
import struct
import sys
import time
import urllib.request

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "e731ee594dde4a89-cae9dad929a34d17"


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


def plausible_pointers(blob):
    out = []
    for offset in range(0, len(blob) - 3, 4):
        (value,) = struct.unpack(">I", blob[offset:offset + 4])
        if 0x80000000 <= value < 0x81800000 and value % 4 == 0:
            out.append((offset, value))
    return out


def scan_tech_run(blob, label, minimum_distinct=3):
    hits = []
    # byte runs
    for offset in range(0, len(blob) - 20):
        chunk = blob[offset:offset + 20]
        if all(v <= 31 for v in chunk) and len(set(chunk)) >= minimum_distinct:
            hits.append((label, offset, "bytes", chunk.hex()))
    # u16 runs (big endian)
    for offset in range(0, len(blob) - 40, 2):
        values = struct.unpack(">20H", blob[offset:offset + 40])
        if all(v <= 31 for v in values) and len(set(values)) >= minimum_distinct:
            hits.append((label, offset, "u16", ",".join(map(str, values))))
    return hits


def main():
    slot = int.from_bytes(read(0x8050EA10, 4), "big")
    actor = slot
    print(f"actor {actor:#x}")
    blob = read(actor, 0x340)
    pointers = plausible_pointers(blob)
    print(f"pointers inside the actor struct: {len(pointers)}")
    for offset, value in pointers:
        print(f"  +{offset:#05x} -> {value:#x}")
    hits = scan_tech_run(blob, "actor")
    print(f"tech-like runs inside the actor struct: {len(hits)}")
    for label, offset, kind, text in hits[:10]:
        print(f"  {label} +{offset:#05x} ({kind}): {text}")
    for offset, value in pointers[:12]:
        target = read(value, 0x400)
        if len(target) < 0x40:
            continue
        found = scan_tech_run(target, f"ptr@{offset:#x}->{value:#x}")
        if found:
            print(f"\nscanned {value:#x} ({len(target)} bytes): {len(found)} tech-like runs")
            for label, hit_offset, kind, text in found[:6]:
                print(f"  {label} +{hit_offset:#05x} ({kind}): {text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
