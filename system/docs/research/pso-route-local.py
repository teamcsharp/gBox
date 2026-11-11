"""Record the operator's own route: positions through the desktop-local RPC (the byte path that works), plus their pad.

The reader is the one proven live on 2026-11-10: `POST http://127.0.0.1:18765/api/sessions/<sid>/rpc` with
`{"op": "read_memory", "args": {"address": ..., "length": ...}}` answers hex in ~20 ms - fast enough for real route sampling, unlike
the job route (sha256 only) and the main API's /rpc (504).
"""
import argparse
import json
import struct
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp\imitate-wt\system")

from gbox import pso_ram, xinput                                  # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
LOCAL = "http://127.0.0.1:18765"
OUT = Path(r"D:\gBox\pso-ds\routes")
BUTTONS = {0x1000: "a", 0x2000: "b", 0x4000: "x", 0x8000: "y", 0x0010: "start", 0x0020: "back",
           0x0001: "dup", 0x0002: "ddown", 0x0004: "dleft", 0x0008: "dright"}


class LocalReader:
    def __init__(self, session: str):
        self.session = session

    def read(self, address: int, length: int) -> bytes:
        body = json.dumps({"op": "read_memory", "args": {"address": address, "length": length}}).encode()
        req = urllib.request.Request(f"{LOCAL}/api/sessions/{self.session}/rpc", data=body, method="POST",
                                     headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                              "content-type": "application/json"})
        reply = json.loads(urllib.request.urlopen(req, timeout=10).read() or b'""')
        return bytes.fromhex(reply) if isinstance(reply, str) else b""


def pad_keys() -> list[str]:
    fn = xinput.load()
    for slot in range(4):
        state = xinput.read(fn, slot)
        if state is None:
            continue
        g = state.gamepad
        if g.buttons or abs(g.lx) > 7849 or abs(g.ly) > 7849:
            keys = [name for bit, name in BUTTONS.items() if g.buttons & bit]
            if abs(g.lx) > 7849:
                keys.append("right" if g.lx > 0 else "left")
            if abs(g.ly) > 7849:
                keys.append("down" if g.ly > 0 else "up")
            return keys
    return []


def read_u32(reader, address: int) -> int:
    return struct.unpack(">I", reader.read(address, 4))[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--seconds", type=float, default=900)
    ap.add_argument("--hz", type=float, default=4.0)
    args = ap.parse_args()
    reader = LocalReader(args.session)
    rows, start, actor_ptr, misses = [], time.time(), 0, 0
    print(f"recording at {args.hz:.0f} Hz", flush=True)
    while time.time() - start < args.seconds:
        now = time.time() - start
        try:
            if not actor_ptr or misses > 10:
                slots = struct.unpack(">4I", reader.read(pso_ram.PLAYER_SLOTS, 16))
                actor_ptr = next((s for s in slots if s), 0)
                misses = 0
            if actor_ptr:
                x, y, z = struct.unpack(">3f", reader.read(actor_ptr + 0x38, 12))
                rows.append({"t": round(now, 2), "x": round(x, 1), "y": round(y, 1), "z": round(z, 1),
                             "floor": read_u32(reader, pso_ram.FLOOR), "keys": pad_keys()})
                misses = 0
            else:
                misses += 1
        except Exception as exc:                                  # noqa: BLE001
            misses += 1
            if misses == 1:
                print("read error:", type(exc).__name__, exc, flush=True)
        time.sleep(max(0.0, 1 / args.hz))
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"route-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({"session": args.session, "rows": rows}, indent=0), encoding="utf-8")
    print(f"{len(rows)} samples -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
