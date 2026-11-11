"""Receding-horizon navigation over the Forest 1 collision: re-plan from the current position, walk a short horizon, and sidestep
when stalled.

`pso_kbwalk.walk_path` walks the whole list it is given and holds the last leg for tens of steps when a segment is unreachable in
practice (trees and rocks are not in the collision data). This wrapper instead asks for a fresh `pso_walk.path` every few steps,
walks only the near part of it, and when the position stops improving it steps sideways before trying again.
"""
import json
import math
import struct
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\system")

import capture_gbox_app as cap                                     # noqa: E402
from gbox import pso_kbwalk                                        # noqa: E402
from gbox import pso_walk                                          # noqa: E402
from gbox.adapters import win_send_keys                            # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "75cf966f35164149-4ec5d512e3484b02"
PID = 36964
REL = Path(r"D:\gBox\pso-ds\rel\map_forest01c.rel")
HISTORY = Path(r"D:\gBox\pso-ds\routes\forest1-navigation.json")


def read(address, length):
    body = json.dumps({"op": "read_memory", "args": {"address": address, "length": length}}).encode()
    req = urllib.request.Request(f"{API}/api/sessions/{SID}/rpc", data=body, method="POST",
                                 headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                          "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=15).read() or b'""')


def read_pos():
    actor = int(read(0x8050EA10, 4), 16)
    if not actor:
        return None
    x, _y, z = struct.unpack(">fff", bytes.fromhex(read(actor + 0x38, 12)))
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


def press(events):
    import ctypes
    user32 = ctypes.windll.user32
    for _ in range(3):
        hwnd = gbox_hwnd()
        if hwnd:
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.12)
        try:
            answer = win_send_keys(PID, events)
            if answer.get("sent"):
                return answer
        except Exception:                                        # noqa: BLE001
            time.sleep(0.12)
    return {"sent": 0}


def hold(keys, seconds):
    if isinstance(keys, str):
        keys = [keys]
    keys = list(keys)
    if not keys:
        return
    press([{"key": k, "down": True} for k in keys])
    time.sleep(seconds)
    press([{"key": k, "down": False} for k in keys])


def main(goal=None, max_rounds=40, horizon=5):
    start = read_pos()
    if not start:
        print("no actor")
        return 1
    print("start:", tuple(round(v, 1) for v in start))
    cal = pso_kbwalk.calibrate(read_pos, hold)
    print("calibration:", {k: (round(v[0], 2), round(v[1], 2)) for k, v in cal.items() if k in pso_kbwalk.KEYS})
    collision = REL.read_bytes()
    if goal is None:
        rows = json.loads(Path(r"D:\gBox\pso-ds\routes\route-20261110-235419.json").read_text(encoding="utf-8"))
        rows = rows.get("rows") if isinstance(rows, dict) else rows
        points = [(r["x"], r["z"]) for r in rows if r.get("floor") == 1]
        goal = max(points, key=lambda p: math.dist(p, start))
    print("goal:", tuple(round(v, 1) for v in goal))
    history, stall, last_distance = [], 0, None
    for round_index in range(max_rounds):
        current = read_pos()
        distance = math.dist(current, goal)
        history.append([round(current[0], 1), round(current[1], 1), round(distance, 1)])
        print(f"round {round_index}: pos={tuple(round(v,1) for v in current)} remaining={distance:.0f}")
        if distance <= 10:
            print("arrived")
            break
        if last_distance is not None and last_distance - distance < 3:
            stall += 1
        else:
            stall = 0
        last_distance = distance
        if stall >= 2:                                          # sidestep: push along the route's normal for a moment
            print("  stalled - sidestep")
            hold("left" if round_index % 2 == 0 else "right", 0.45)
            hold("up", 0.45)
            stall = 0
            continue
        route = pso_walk.path(collision, current, goal)
        if not route:
            print("  no route from here")
            break
        segment = route[:horizon]
        result = pso_kbwalk.walk_path(read_pos, hold, segment, tolerance=9.0)
        if not result.get("ok"):
            print("  segment:", result.get("why"))
    HISTORY.write_text(json.dumps({"goal": goal, "history": history}, indent=1), encoding="utf-8")
    print("end:", tuple(round(v, 1) for v in read_pos()), "remaining:", round(math.dist(read_pos(), goal), 1))
    cap.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
