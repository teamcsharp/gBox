"""CP17 with the yaw-aware stepper: pso_walk.path for the route, then pso_kbwalk.steer_walk per waypoint (short legs, forward
re-probed each step), watching pso_ram.floor and trying the key door at the end.
"""
import json
import math
import struct
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import capture_gbox_app as cap                                     # noqa: E402
from gbox import pso_kbwalk, pso_walk                              # noqa: E402
from gbox.adapters import win_send_keys                            # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "e731ee594dde4a89-cae9dad929a34d17"
PID = 37032
TABLE, MAX_ENTRIES = 0x8050D460, 256
FLOOR = 0x805D5FC0
REL = Path(r"D:\gBox\pso-ds\rel\map_forest01c.rel")
LOG = r"D:\gBox\pso-ds\cp17-steer.log"


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


def floor():
    return int.from_bytes(read(FLOOR, 4), "big")


def cstring(address, limit=40):
    raw = read(address, limit)
    return raw.split(b"\x00")[0].decode("ascii", "replace") if raw else ""


def doors():
    raw = read(TABLE, MAX_ENTRIES * 4)
    out = []
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        name_pointer = int.from_bytes(read(pointer, 4), "big")
        if not (0x80000000 <= name_pointer < 0x81800000):
            continue
        name = cstring(name_pointer)
        if not name.startswith("TObjDoor"):
            continue
        x, y, z = struct.unpack(">fff", read(pointer + 0x38, 12))
        out.append({"index": index, "class": name, "x": x, "y": y, "z": z})
    return out


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
        time.sleep(0.06)
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


def tap(key, times=1, gap=0.4):
    for _ in range(times):
        send([{"key": key, "down": True}, {"key": key, "down": False}])
        time.sleep(gap)


def main():
    log("=== CP17 steer_walk attempt")
    me = read_pos()
    log(f"floor={floor()} pos={tuple(round(v,1) for v in me)}")
    collision = REL.read_bytes()
    targets = sorted([d for d in doors() if d["class"].startswith("TObjDoorKey")],
                     key=lambda d: math.dist(me, (d["x"], d["z"])))
    if not targets:
        log("no key doors")
        return 2
    door = targets[0]
    goal = (door["x"], door["z"])
    log(f"target {door['class']} at ({goal[0]:.0f},{goal[1]:.0f}) dist={math.dist(me, goal):.0f}")
    route = pso_walk.path(collision, me, goal)
    if not route:
        log("no route")
        return 2
    log(f"route: {len(route)} waypoints")
    for index, waypoint in enumerate(route):
        if floor() != 1:
            log(f"FLOOR CHANGED BY WALKING: {floor()}")
            cap.main()
            return 0
        result = pso_kbwalk.steer_walk(read_pos, hold, waypoint, tolerance=6.0, max_steps=8)
        if index % 4 == 0:
            log(f"  wp {index}/{len(route)} ok={result.get('ok')} why={result.get('why')} "
                f"pos={tuple(round(v,1) for v in read_pos())} remaining={math.dist(read_pos(), goal):.0f}")
        if index % 8 == 7:
            cap.main()
    log(f"route done; floor={floor()} pos={tuple(round(v,1) for v in read_pos())}")
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
