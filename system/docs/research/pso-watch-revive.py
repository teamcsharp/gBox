"""Watch the Lv 1 character die and revive: does survival's native revival restore HP? This is the cheapest heal path and the
character is at 2 HP anyway."""
import json
import struct
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\system")

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "e731ee594dde4a89-cae9dad929a34d17"


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


def main():
    for sample in range(40):
        actor = int.from_bytes(read(0x8050EA10, 4), "big")
        if not actor:
            print(f"{time.strftime('%H:%M:%S')} no actor")
            time.sleep(3)
            continue
        hp = int.from_bytes(read(actor + 0x32C, 2), "big")
        hp_max = int.from_bytes(read(actor + 0x2B8, 2), "big")
        x, _y, z = struct.unpack(">fff", read(actor + 0x38, 12))
        print(f"{time.strftime('%H:%M:%S')} hp={hp}/{hp_max} pos=({x:.0f},{z:.0f}) floor={read(0x805D5FC0,4).hex()}", flush=True)
        if hp >= hp_max * 0.9:
            print("REVIVED AT (NEAR) FULL HP -> revival is a heal")
            return 0
        time.sleep(4)
    print("no revival seen in the window")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
