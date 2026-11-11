"""Find the exit from the slope pocket: hold each of the eight stick directions for 1.5 s and measure the displacement.

On a slope the short probes only shuffled the character inside a 30-unit pocket. Longer holds with both single keys and diagonals show
which direction actually covers ground, including downhill (the only way off a slope in PSO).
"""
import json
import math
import struct
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp")

from gbox.adapters import win_send_keys                            # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "e731ee594dde4a89-cae9dad929a34d17"
PID = 37032


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


def pos():
    actor = int.from_bytes(read(0x8050EA10, 4), "big")
    if not actor:
        return None
    x, y, z = struct.unpack(">fff", read(actor + 0x38, 12))
    return x, y, z


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
    send([{"key": k, "down": True} for k in keys])
    time.sleep(seconds)
    send([{"key": k, "down": False} for k in keys])
    time.sleep(0.15)


def main():
    combos = [("up",), ("down",), ("left",), ("right",),
              ("up", "left"), ("up", "right"), ("down", "left"), ("down", "right")]
    print("start:", tuple(round(v, 1) for v in pos()))
    best = None
    for combo in combos:
        before = pos()
        hold(list(combo), 1.5)
        after = pos()
        moved = math.dist((before[0], before[2]), (after[0], after[2]))
        drop = before[1] - after[1]
        print(f"  {'+'.join(combo):<12} moved={moved:5.1f}  dy={drop:+5.1f}  -> {tuple(round(v,1) for v in after)}",
              flush=True)
        if best is None or moved > best[1]:
            best = (combo, moved, drop)
        if moved > 40:
            print("exit direction found:", combo, "moved", round(moved))
            break
    print("best:", best)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
