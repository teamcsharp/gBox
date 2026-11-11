"""Test whether survival's native revival restores HP: warp to Forest 1 at low HP, wait for the Boomas, then read HP.

If revival brings the character back at full HP this is the cheapest heal available (no inventory slot, no hospital walk), which
matters because the inventory is full from the equip cycler.
"""
import json
import struct
import sys
import time
import urllib.request
import uuid

sys.path.insert(0, r"C:\_tools\gBox\system")

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "75cf966f35164149-4ec5d512e3484b02"


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


def controls(op, fields):
    body = {"op": "pso_controls", "args": {"command_id": str(uuid.uuid4()), "expires": time.time() + 5,
                                          "input": {"session_id": SID, "op": op, **fields}}}
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{API}/api/sessions/{SID}/rpc", data=data, method="POST",
                                 headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                          "content-type": "application/json"})
    try:
        return 200, json.loads(urllib.request.urlopen(req, timeout=60).read() or b"null")
    except Exception as exc:                                     # noqa: BLE001
        return getattr(exc, "code", 0), getattr(exc, "read", lambda: b"")().decode()[:200]


def hp():
    actor = int.from_bytes(read(0x8050EA10, 4), "big")
    if not actor:
        return None
    return int.from_bytes(read(actor + 0x32C, 2), "big"), int.from_bytes(read(actor + 0x2B8, 2), "big")


def main():
    print("before:", hp(), "floor:", read(0x805D5FC0, 4).hex())
    print("warp:", str(controls("floor_warp", {"target": "1"}))[:200])
    for _ in range(30):
        time.sleep(5)
        current = hp()
        print(f"  hp={current} floor={read(0x805D5FC0, 4).hex()}", flush=True)
        if current and current[0] >= current[1] * 0.9:
            print("healed to near full")
            break
    print("after:", hp())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
