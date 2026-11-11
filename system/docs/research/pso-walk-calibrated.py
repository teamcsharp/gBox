"""Calibrate the stick->world mapping by probing, then walk a collision path with closed-loop feedback.

The naive assumption (right = +x) was wrong on the live camera: pressing "left" moved the character +x. So measure instead: hold each
direction briefly from a standstill, record the world displacement it produces, and pick the key whose measured vector best matches the
direction to the next waypoint. Feedback comes from the actor's position in RAM after every hold.
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
from gbox import pso_walk                                          # noqa: E402
from gbox.adapters import win_send_keys                            # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "75cf966f35164149-4ec5d512e3484b02"
PID = 36964
REL = Path(r"D:\gBox\pso-ds\rel\map_forest01c.rel")
ROUTE = Path(r"D:\gBox\pso-ds\routes\route-20261110-235419.json")
KEYS = ("up", "down", "left", "right")


def read(address, length):
    body = json.dumps({"op": "read_memory", "args": {"address": address, "length": length}}).encode()
    req = urllib.request.Request(f"{API}/api/sessions/{SID}/rpc", data=body, method="POST",
                                 headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                          "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=15).read() or b'""')


def position():
    actor = int(read(0x8050EA10, 4), 16)
    if not actor:
        return None
    return struct.unpack(">fff", bytes.fromhex(read(actor + 0x38, 12)))


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
    press([{"key": k, "down": True} for k in keys])
    time.sleep(seconds)
    press([{"key": k, "down": False} for k in keys])


def calibrate():
    """World displacement produced by each stick direction."""
    vectors = {}
    for key in KEYS:
        before = position()
        hold([key], 0.45)
        time.sleep(0.25)
        after = position()
        vectors[key] = (after[0] - before[0], after[2] - before[2])
    return vectors


def key_for(direction, vectors):
    """The key whose measured world vector points most nearly along `direction`."""
    best, best_dot = None, -1e9
    norm = math.hypot(*direction) or 1.0
    for key, (vx, vz) in vectors.items():
        length = math.hypot(vx, vz)
        if length < 1e-6:
            continue
        dot = (vx / length) * (direction[0] / norm) + (vz / length) * (direction[1] / norm)
        if dot > best_dot:
            best, best_dot = key, dot
    return best, best_dot


def main():
    start = position()
    print("start:", tuple(round(v, 1) for v in start))
    vectors = calibrate()
    print("stick->world:", {k: (round(v[0], 1), round(v[1], 1)) for k, v in vectors.items()})
    collision = REL.read_bytes()
    rows = json.loads(ROUTE.read_text(encoding="utf-8"))
    rows = rows.get("rows") if isinstance(rows, dict) else rows
    points = [(r["x"], r["z"]) for r in rows if r.get("floor") == 1]
    route = target = None
    for candidate in sorted(points, key=lambda p: math.dist(p, (start[0], start[2]))):
        if not (80 <= math.dist(candidate, (start[0], start[2])) <= 260):
            continue
        route = pso_walk.path(collision, (start[0], start[2]), candidate)
        if route:
            target = candidate
            break
    if not route:
        print("no reachable target")
        return 2
    print(f"target {tuple(round(v,1) for v in target)}; {len(route)} waypoints")
    for step in range(14):
        now = position()
        remaining = math.dist((now[0], now[2]), target)
        if remaining < 25:
            print(f"arrived within {remaining:.0f} units")
            break
        # steer at the next waypoint not yet reached
        waypoint = route[0]
        for candidate in route:
            if math.dist((now[0], now[2]), candidate) > 12:
                waypoint = candidate
                break
        direction = (waypoint[0] - now[0], waypoint[1] - now[2])
        key, dot = key_for(direction, vectors)
        print(f"step {step}: pos={tuple(round(v,1) for v in now)} next={tuple(round(v,1) for v in waypoint)} "
              f"key={key} align={dot:.2f} remaining={remaining:.0f}")
        if key:
            hold([key], 0.5)
        time.sleep(0.15)
    cap.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
