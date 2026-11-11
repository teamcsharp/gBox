"""Unlimited TP for any loaded character.

Offsets (documented in pso_re_seeds.py and measured live this round):
    TObjPlayer.hp    +0x32C (u16)   max +0x2B8
    TObjPlayer.tp    +0x32E (u16)   max +0x2BA
Measured: tp 35, tp max 35 while the HUD read TP 35/35.

`apply()` writes a large max and a full current value; `keep_full()` runs a loop that re-fills the bar, so the character never runs out.
"""
import json
import struct
import sys
import time
import urllib.request

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "e731ee594dde4a89-cae9dad929a34d17"
TP, TP_MAX = 0x32E, 0x2BA
BIG = 999


def _rpc(op, args):
    body = json.dumps({"op": op, "args": args}).encode()
    for _ in range(3):
        try:
            req = urllib.request.Request(f"{API}/api/sessions/{SID}/rpc", data=body, method="POST",
                                         headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                                  "content-type": "application/json"})
            return json.loads(urllib.request.urlopen(req, timeout=10).read() or b"null")
        except Exception:                                        # noqa: BLE001
            time.sleep(0.15)
    return None


def read(address, length):
    result = _rpc("read_memory", {"address": address, "length": length})
    try:
        return bytes.fromhex(result or "")
    except Exception:                                            # noqa: BLE001
        return b""


def write(address, data):
    return _rpc("write_memory", {"address": address, "data": data.hex()})


def actor():
    raw = read(0x8050EA10, 4)
    return int.from_bytes(raw, "big") if raw else 0


def tp_state():
    pointer = actor()
    if not pointer:
        return None
    blob = read(pointer, 0x340)
    if len(blob) < 0x330:
        return None
    current = struct.unpack(">H", blob[TP:TP + 2])[0]
    maximum = struct.unpack(">H", blob[TP_MAX:TP_MAX + 2])[0]
    return {"tp": current, "tp_max": maximum}


def apply(maximum=BIG):
    pointer = actor()
    if not pointer:
        raise RuntimeError("no player actor")
    before = tp_state()
    write(pointer + TP_MAX, struct.pack(">H", maximum))
    write(pointer + TP, struct.pack(">H", maximum))
    after = tp_state()
    return {"before": before, "after": after, "address": hex(pointer), "ok": bool(after and after["tp_max"] >= maximum)}


def keep_full(every=1.5, duration=3600.0):
    started = time.time()
    while time.time() - started < duration:
        state = tp_state()
        if state and state["tp"] < state["tp_max"]:
            pointer = actor()
            if pointer:
                write(pointer + TP, struct.pack(">H", state["tp_max"]))
        time.sleep(every)
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "loop":
        print(json.dumps(apply()), flush=True)
        print("keeping TP full", flush=True)
        raise SystemExit(keep_full())
    print(json.dumps(apply(), indent=1))
