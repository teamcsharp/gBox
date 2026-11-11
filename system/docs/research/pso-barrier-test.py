"""Gate test: walk at the energy barrier (221, 493) from the Forest 1 spawn and try to open/pass it.

If Forest 1's start zone is gated, the barrier is the wall the oscillating walkers kept turning away from. Reaching it and interacting
(or attacking) should open the west passage; the walker measures its own displacement each stride so terrain cannot fool it.
"""
import json
import math
import struct
import sys
import time
import urllib.request
import uuid

sys.path.insert(0, r"C:\_tools\gBox\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import capture_gbox_app as cap                                     # noqa: E402
from gbox.adapters import win_send_keys                            # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "e731ee594dde4a89-cae9dad929a34d17"
PID = 37032
TABLE, MAX_ENTRIES = 0x8050D460, 256
FLOOR = 0x805D5FC0
GOAL = (221.0, 493.0)                                              # TOBarrierEnergy01
LOG = r"D:\gBox\pso-ds\barrier.log"


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


def pos():
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
    send([{"key": k, "down": True} for k in keys])
    time.sleep(seconds)
    send([{"key": k, "down": False} for k in keys])
    time.sleep(0.05)


def tap(key, times=1, gap=0.45):
    for _ in range(times):
        send([{"key": key, "down": True}, {"key": key, "down": False}])
        time.sleep(gap)


def unit(dx, dz):
    length = math.hypot(dx, dz)
    return (dx / length, dz / length) if length > 1e-6 else (0.0, 0.0)


def main(budget=420.0):
    log("=== barrier gate test")
    if floor() != 1:
        controls("floor_warp", {"target": "1"})
        time.sleep(10)
    tap("b", 2, 0.5)
    log(f"start {tuple(round(v,1) for v in pos())} goal barrier {GOAL} dist={math.dist(pos(), GOAL):.0f}")
    started = time.time()
    while time.time() - started < budget:
        me = pos()
        distance = math.dist(me, GOAL)
        if distance <= 12:
            log(f"at the barrier ({distance:.0f}); interacting and pushing")
            tap("a", 1, 0.6)
            tap("a", 3, 0.3)
            for step in range(6):
                hold("up", 0.9)
                now = pos()
                log(f"  push {step}: {tuple(round(v,1) for v in now)} dist={math.dist(now, GOAL):.0f} floor={floor()}")
                if floor() != 1:
                    log(f"FLOOR CHANGED: {floor()}")
                    cap.main()
                    return 0
            cap.main()
            return 0
        bearing = unit(GOAL[0] - me[0], GOAL[1] - me[1])
        best = None
        for key in ("up", "down", "left", "right"):
            before = pos()
            hold(key, 0.45)
            after = pos()
            vector = (after[0] - before[0], after[1] - before[1])
            length = math.hypot(*vector)
            if length < 1.5:
                continue
            align = (vector[0] / length) * bearing[0] + (vector[1] / length) * bearing[1]
            if best is None or align > best[1]:
                best = (key, align, length)
        if best is None:
            log("  no direction moves; pressing B")
            tap("b", 1, 0.4)
            continue
        hold(best[0], 0.9)
        if int(time.time() - started) % 30 < 2:
            log(f"  {math.dist(pos(), GOAL):.0f} units to barrier, key={best[0]} align={best[1]:.2f}, "
                f"pos={tuple(round(v,1) for v in pos())}")
            cap.main()
    log("budget spent")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
