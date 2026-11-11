"""Navigate Forest 1 with gBox's calibrated keyboard walker (pso_kbwalk) over the extracted collision route.

Wires the module's two callbacks to the proven input path and to the actor's RAM position, then walks a collision route and reports
the distance history so convergence (or not) is visible rather than assumed.
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
from gbox import pso_kbwalk, pso_walk                              # noqa: E402
from gbox.adapters import win_send_keys                            # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "75cf966f35164149-4ec5d512e3484b02"
PID = 36964
REL = Path(r"D:\gBox\pso-ds\rel\map_forest01c.rel")
ROUTE = Path(r"D:\gBox\pso-ds\routes\route-20261110-235419.json")


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
    if isinstance(keys, str):                                    # pso_kbwalk passes one key name
        keys = [keys]
    keys = list(keys)
    if not keys:
        return {"sent": 0}
    press([{"key": k, "down": True} for k in keys])
    time.sleep(seconds)
    press([{"key": k, "down": False} for k in keys])
    return {"sent": 2 * len(keys)}


def main():
    start = read_pos()
    print("start:", tuple(round(v, 1) for v in start))
    calibration = pso_kbwalk.calibrate(read_pos, hold)
    print("calibration:", calibration)
    collision = REL.read_bytes()
    rows = json.loads(ROUTE.read_text(encoding="utf-8"))
    rows = rows.get("rows") if isinstance(rows, dict) else rows
    points = [(r["x"], r["z"]) for r in rows if r.get("floor") == 1]
    route = target = None
    for candidate in sorted(points, key=lambda p: -math.dist(p, start)):
        if math.dist(candidate, start) < 60:
            continue
        route = pso_walk.path(collision, start, candidate)
        if route:
            target = candidate
            break
    if not route:
        print("no route")
        return 2
    print(f"target {tuple(round(v,1) for v in target)}; route {len(route)} waypoints")
    result = pso_kbwalk.walk_path(read_pos, hold, route, tolerance=8.0, log=lambda line: print("  ", line, flush=True))
    print("walk result:", json.dumps(result, default=str)[:400])
    print("end:", tuple(round(v, 1) for v in (read_pos() or (0, 0))), "remaining:",
          round(math.dist(read_pos(), target), 1))
    cap.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
