"""Walk to a world (x, z) in Pioneer 2 with the probe controller, press A, walk through, and capture.

Used to reach the medical door (hospital) and later the warp door, from the city's entity positions.
"""
import json
import math
import struct
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import capture_gbox_app as cap                                     # noqa: E402
from gbox.adapters import win_send_keys                            # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "75cf966f35164149-4ec5d512e3484b02"
PID = 36964
LOG = r"D:\gBox\pso-ds\city-walk.log"


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


def player():
    actor = int.from_bytes(read(0x8050EA10, 4), "big")
    if not actor:
        return None
    return struct.unpack(">fff", read(actor + 0x38, 12))


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
        time.sleep(0.08)
    try:
        return win_send_keys(PID, events)
    except Exception as exc:                                     # noqa: BLE001
        return {"error": str(exc)[:60]}


def hold(key, seconds):
    send([{"key": key, "down": True}])
    time.sleep(seconds)
    send([{"key": key, "down": False}])
    time.sleep(0.06)


def tap(key, times=1, gap=0.5):
    for _ in range(times):
        send([{"key": key, "down": True}, {"key": key, "down": False}])
        time.sleep(gap)


def unit(dx, dz):
    length = math.hypot(dx, dz)
    return (dx / length, dz / length) if length > 1e-6 else (0.0, 0.0)


def signed_angle(a, b):
    return math.degrees(math.atan2(a[0] * b[1] - a[1] * b[0], a[0] * b[0] + a[1] * b[1]))


def walk_to(goal, budget=300.0, tolerance=8.0):
    started = time.time()
    forward, cycle = None, 0
    while time.time() - started < budget:
        me = player()
        distance = math.dist((me[0], me[2]), goal)
        if distance <= tolerance:
            return True
        bearing = unit(goal[0] - me[0], goal[1] - me[2])
        if forward is None or cycle % 3 == 0:
            before = (me[0], me[2])
            hold("up", 0.5)
            after = player()
            forward = unit(after[0] - before[0], after[2] - before[1])
            if forward == (0.0, 0.0):
                tap("b", 1, 0.4)
                forward = None
                cycle += 1
                continue
        angle = signed_angle(forward, bearing)
        if abs(angle) <= 30:
            hold("up", 1.0)
        else:
            hold("left" if angle > 0 else "right", min(0.5, 0.1 + abs(angle) / 240.0))
            forward = None
        cycle += 1
        if cycle % 20 == 0:
            log(f"  {distance:.0f} units to go, pos={tuple(round(v,1) for v in me)}")
    return math.dist((player()[0], player()[2]), goal) <= tolerance


def main():
    goal = (193.5, -93.5)                                        # TObjCityDoor_Med (hospital)
    log(f"city walk: start {tuple(round(v,1) for v in player())} -> {goal}")
    reached = walk_to(goal)
    log(f"reached={reached} pos={tuple(round(v,1) for v in player())}")
    if reached:
        tap("a", 1, 0.9)
        tap("b", 1, 0.5)
        hold("up", 1.0)
        log(f"after door: pos={tuple(round(v,1) for v in player())}")
    cap.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
