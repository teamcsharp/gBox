"""Find the PSO GameCube player-data block: follow the actor's pointers and look for the character name and a tech array.

The Dreamcast module's layout does not apply to the GameCube version. For GC this walks the TObjPlayer actor, follows every plausible
heap pointer two levels deep, and prints any block that contains the character's name (UTF-16BE or ASCII) or a run of 19-20 small bytes
that could be technique levels.
"""
import json
import struct
import sys
import time
import urllib.request

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "e731ee594dde4a89-cae9dad929a34d17"
NAME = "BQF"


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


def pointers(blob):
    out = []
    for offset in range(0, len(blob) - 3, 4):
        (value,) = struct.unpack(">I", blob[offset:offset + 4])
        if 0x80000000 <= value < 0x81800000 and value % 4 == 0:
            out.append((offset, value))
    return out


def find_name(blob):
    utf16 = NAME.encode("utf-16-be")
    ascii_form = NAME.encode("ascii")
    hits = []
    index = blob.find(utf16)
    while index >= 0:
        hits.append(("utf16", index))
        index = blob.find(utf16, index + 1)
    index = blob.find(ascii_form)
    while index >= 0:
        hits.append(("ascii", index))
        index = blob.find(ascii_form, index + 1)
    return hits


def tech_runs(blob, width=20, limit=31):
    hits = []
    for offset in range(0, len(blob) - width):
        chunk = blob[offset:offset + width]
        if all(v <= limit for v in chunk) and sum(1 for v in chunk if v == 0) >= width - 4:
            hits.append((offset, chunk.hex(" ")))
    return hits


def scan_block(address, label, depth=0):
    blob = read(address, 0x400)
    if len(blob) < 0x40:
        return
    names = find_name(blob)
    techs = tech_runs(blob)
    interesting = bool(names) or len(techs) >= 8
    if interesting:
        print(f"\n{label} {address:#x} ({len(blob)} bytes): names={names} tech-like runs={len(techs)}")
        for row in range(0, 64, 16):
            chunk = blob[row:row + 16]
            print(f"  +{row:#04x}  {chunk.hex(' ')}  {''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)}")
        for offset, text in techs[:6]:
            print(f"  tech-run +{offset:#05x}: {text}")
    if depth < 1:
        for offset, value in pointers(blob)[:8]:
            scan_block(value, f"{label}[+{offset:#x}]", depth + 1)


def main():
    actor = int.from_bytes(read(0x8050EA10, 4), "big")
    print(f"actor {actor:#x}")
    scan_block(actor, "actor", depth=0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
