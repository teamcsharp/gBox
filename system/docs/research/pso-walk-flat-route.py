"""Walk the flat-only route to Forest 1's key door. Where it stops is the gate.

The route comes from flat_route.py (106 waypoints over level cells). The walker is the calibrated one that converged 708->163 in round
190, chunked so progress is visible and a stall is reported with the exact coordinates where it happened - which is the gate's
location if the zone really is gated.
"""
import json
import math
import struct
import sys
import time
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import capture_gbox_app as cap                                     # noqa: E402
from gbox import pso_kbwalk                                        # noqa: E402
from gbox.adapters import win_send_keys                            # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "e731ee594dde4a89-cae9dad929a34d17"
PID = 37032
FLOOR = 0x805D5FC0
ROUTE = Path(r"D:\gBox\pso-ds\routes\forest1-flat-route.json")
LOG = r"D:\gBox\pso-ds\flat-walk.log"


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(text + "\n")


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


def controls(op, fields, timeout=90):
    body = {"op": "pso_controls", "args": {"command_id": str(uuid.uuid4()), "expires": time.time() + 5,
                                          "input": {"session_id": SID, "op": op, **fields}}}
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{API}/api/sessions/{SID}/rpc", data=data, method="POST",
                                 headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                          "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read() or b"null")
    except Exception as exc:                                     # noqa: BLE001
        return {"error": str(exc)[:120]}


def floor():
    return int.from_bytes(read(FLOOR, 4), "big")


def read_pos():
    actor = int.from_bytes(read(0x8050EA10, 4), "big")
    if not actor:
        return None
    x, _y, z = struct.unpack(">fff", read(actor + 0x38, 12))
    return x, z


def gbox_hwnd():
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _l):
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        if buf.value.strip() == "gBox":
            found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def send(events):
    import ctypes
    user32 = ctypes.windll.user32
    hwnd = gbox_hwnd()
    if hwnd:
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.05)
    try:
        return win_send_keys(PID, events)
    except Exception:                                            # noqa: BLE001
        return {}


def hold(keys, seconds):
    if isinstance(keys, str):
        keys = [keys]
    keys = list(keys)
    if not keys:
        return
    send([{"key": k, "down": True} for k in keys])
    time.sleep(seconds)
    send([{"key": k, "down": False} for k in keys])
    time.sleep(0.04)


def tap(key, times=1, gap=0.45):
    for _ in range(times):
        send([{"key": key, "down": True}, {"key": key, "down": False}])
        time.sleep(gap)


def main(budget=600.0):
    log("=== flat-route walk")
    if floor() != 1:
        controls("floor_warp", {"target": "1"})
        time.sleep(10)
    tap("b", 2, 0.5)
    route = json.loads(ROUTE.read_text(encoding="utf-8"))["waypoints"]
    me = read_pos()
    log(f"start {tuple(round(v,1) for v in me)} route waypoints {len(route)} floor={floor()}")
    started = time.time()
    index = 0
    still = 0
    last = me
    while index < len(route) and time.time() - started < budget:
        if floor() != 1:
            log(f"FLOOR CHANGED BY WALKING: {floor()}")
            cap.main()
            return 0
        chunk = route[index:index + 4]
        try:
            pso_kbwalk.walk_path(read_pos, hold, [tuple(w) for w in chunk], tolerance=9.0)
        except RuntimeError as exc:
            log(f"  walk_path: {exc}")
            tap("b", 1, 0.35)
        now = read_pos()
        moved = math.dist(now, last)
        last = now
        index += len(chunk)
        if moved < 3:
            still += 1
        else:
            still = 0
        if index % 8 == 0:
            log(f"  waypoint {index}/{len(route)}, pos={tuple(round(v,1) for v in now)}, moved={moved:.0f}")
            cap.main()
        if still >= 3:
            log(f"  STALLED at {tuple(round(v,1) for v in now)} (waypoint {index}) - this is the gate if the zone is gated")
            cap.main()
            return 3
    log(f"route finished at {tuple(round(v,1) for v in read_pos())} floor={floor()}")
    tap("a", 1, 0.8)
    for step in range(4):
        hold("up", 0.9)
        now = floor()
        log(f"  push {step}: floor={now}")
        if now != 1:
            log(f"FLOOR CHANGED BY WALKING: {now}")
            cap.main()
            return 0
    cap.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
