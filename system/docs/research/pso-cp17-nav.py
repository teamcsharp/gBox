"""CP17 with the proven navigator: collision route (pso_walk) + calibrated walker (pso_kbwalk), re-planned every few waypoints,
sidestep on a stall. Targets Forest 1's key doors and watches pso_ram.floor for a change by walking.
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
LOG = r"D:\gBox\pso-ds\cp17-nav.log"


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
        time.sleep(0.08)
    try:
        return win_send_keys(PID, events)
    except Exception as exc:                                     # noqa: BLE001
        return {"error": str(exc)[:50]}


def hold(keys, seconds):
    if isinstance(keys, str):
        keys = [keys]
    keys = list(keys)
    if not keys:
        return
    send([{"key": k, "down": True} for k in keys])
    time.sleep(seconds)
    send([{"key": k, "down": False} for k in keys])
    time.sleep(0.05)


def tap(key, times=1, gap=0.5):
    for _ in range(times):
        send([{"key": key, "down": True}, {"key": key, "down": False}])
        time.sleep(gap)


def navigate(collision, goal, max_rounds=45, horizon=6, tolerance=11.0):
    stall, last = 0, None
    for round_index in range(max_rounds):
        current = read_pos()
        distance = math.dist(current, goal)
        if distance <= tolerance:
            return True
        if last is not None and last - distance < 3:
            stall += 1
        else:
            stall = 0
        last = distance
        if stall >= 2:
            hold("left" if round_index % 2 == 0 else "right", 0.4)
            hold("up", 0.4)
            tap("b", 1, 0.3)
            stall = 0
            continue
        route = pso_walk.path(collision, current, goal)
        if not route:
            log(f"  no route from {tuple(round(v,1) for v in current)} to {goal}")
            return False
        pso_kbwalk.walk_path(read_pos, hold, route[:horizon], tolerance=9.0)
        if round_index % 4 == 3:
            log(f"  round {round_index}: {distance:.0f} units to door, floor={floor()}")
    return math.dist(read_pos(), goal) <= tolerance


def main():
    log("=== CP17 collision-nav attempt")
    log(f"floor={floor()} pos={tuple(round(v,1) for v in read_pos())}")
    collision = REL.read_bytes()
    me = read_pos()
    targets = sorted([d for d in doors() if d["class"].startswith("TObjDoorKey")],
                     key=lambda d: math.dist(me, (d["x"], d["z"])))
    if not targets:
        log("no key doors found")
        return 2
    for door in targets[:3]:
        goal = (door["x"], door["z"])
        log(f"target {door['class']} at ({goal[0]:.0f},{goal[1]:.0f}) dist={math.dist(read_pos(), goal):.0f}")
        reached = navigate(collision, goal)
        log(f"  reached={reached} floor={floor()} pos={tuple(round(v,1) for v in read_pos())}")
        if floor() != 1:
            log(f"FLOOR CHANGED BY WALKING: {floor()}")
            cap.main()
            return 0
        if reached:
            tap("a", 1, 0.8)
            for step in range(4):
                hold("up", 0.9)
                now = floor()
                log(f"   push {step}: floor={now}")
                if now != 1:
                    log(f"FLOOR CHANGED BY WALKING: {now}")
                    cap.main()
                    return 0
            cap.main()
    log("no floor change at the key doors tried")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
