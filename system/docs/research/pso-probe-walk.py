"""Probe-and-turn walker: every cycle it measures where "up" actually sends the character, turns until the target is ahead, strides.

The camera turns with the character, so a fixed calibration goes stale after every turn. This controller re-measures the forward
vector each cycle (a short up-hold), compares it with the bearing to the target, turns with left/right when the bearing is off, and
strides when it is aligned. A progress watchdog changes the stride length when the distance stops falling.
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
from gbox.adapters import win_send_keys                            # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "75cf966f35164149-4ec5d512e3484b02"
PID = 36964
FLOOR = 0x805D5FC0
LOG = Path(r"D:\gBox\pso-ds\probe-walk.log")


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(text + "\n")


def read(address, length):
    body = json.dumps({"op": "read_memory", "args": {"address": address, "length": length}}).encode()
    req = urllib.request.Request(f"{API}/api/sessions/{SID}/rpc", data=body, method="POST",
                                 headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                          "content-type": "application/json"})
    return bytes.fromhex(json.loads(urllib.request.urlopen(req, timeout=15).read() or b'""'))


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


def press(events):
    import ctypes
    user32 = ctypes.windll.user32
    for _ in range(3):
        hwnd = gbox_hwnd()
        if hwnd:
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.08)
        try:
            answer = win_send_keys(PID, events)
            if answer.get("sent"):
                return answer
        except Exception:                                        # noqa: BLE001
            time.sleep(0.08)
    return {"sent": 0}


def hold(key, seconds):
    press([{"key": key, "down": True}])
    time.sleep(seconds)
    press([{"key": key, "down": False}])
    time.sleep(0.05)


def unit(dx, dz):
    length = math.hypot(dx, dz)
    return (dx / length, dz / length) if length > 1e-6 else (0.0, 0.0)


def signed_angle(a, b):
    """Degrees from vector a to vector b, positive is counter-clockwise in (x, z)."""
    dot = a[0] * b[0] + a[1] * b[1]
    cross = a[0] * b[1] - a[1] * b[0]
    return math.degrees(math.atan2(cross, dot))


def probe_forward(seconds=0.45):
    before = pos()
    hold("up", seconds)
    after = pos()
    return unit(after[0] - before[0], after[1] - before[1]), before, after


def walk_to(target, budget=300.0, tolerance=12.0):
    started = time.time()
    last_distance, stall = None, 0
    stride = 0.8
    while time.time() - started < budget:
        current = pos()
        distance = math.dist(current, target)
        if distance <= tolerance:
            log(f"arrived within {distance:.0f} at {tuple(round(v,1) for v in current)}")
            return True
        forward, before, after = probe_forward()
        moved = math.dist(after, before)
        bearing = unit(target[0] - after[0], target[1] - after[1])
        if moved < 1.0:
            log(f"  probe moved {moved:.1f} at {tuple(round(v,1) for v in after)} - pushing/blind, sidestep")
            hold("left", 0.35)
            hold("up", 0.5)
            continue
        angle = signed_angle(forward, bearing)
        if last_distance is not None and last_distance - distance < 2:
            stall += 1
        else:
            stall = 0
        last_distance = distance
        if stall >= 2:
            log("  stalled - turning hard to re-orient")
            hold("left" if stall % 2 else "right", 0.5)
            stride = 0.5 if stride > 0.6 else 1.1
            stall = 0
            continue
        if abs(angle) <= 30:
            hold("up", stride)
        else:
            turn = "left" if angle > 0 else "right"
            hold(turn, min(0.55, 0.12 + abs(angle) / 200.0))
        log(f"  pos={tuple(round(v,1) for v in pos())} remaining={math.dist(pos(), target):.0f} "
            f"angle={angle:.0f} moved={moved:.0f} stride={stride:.1f}")
    log(f"budget spent; remaining {math.dist(pos(), target):.0f}")
    return False


def main():
    target = (49.0, -54.4)                                          # Forest 1 door 4 from the set data
    log(f"start pos={tuple(round(v,1) for v in pos())} floor={floor()} target={target}")
    walk_to(target)
    log(f"end pos={tuple(round(v,1) for v in pos())} floor={floor()}")
    cap.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
