"""Fight for real: step off the pad, lock on with L, close with the stick, attack, and repeat. Then open the menu to read EXP.

Zero EXP was the finding of round 178 - the bot walked but never landed a kill. PSO's lock-on (L) turns the camera to the nearest
enemy, so this loop needs no enemy coordinates: lock, advance, swing, repeat, then check the character panel for Total EXP.
"""
import json
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
LOG = r"D:\gBox\pso-ds\combat.log"


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
    time.sleep(0.06)


def tap(key, times=1, gap=0.35):
    for _ in range(times):
        press([{"key": key, "down": True}, {"key": key, "down": False}])
        time.sleep(gap)


def main():
    log(f"start pos={tuple(round(v,1) for v in pos())}")
    hold("down", 1.0)                                          # step off the pad
    log(f"off pad: {tuple(round(v,1) for v in pos())}")
    for round_index in range(24):
        tap("l", 1, 0.5)                                       # lock on / re-centre the camera
        hold("up", 0.9)                                        # close the distance
        tap("a", 4, 0.4)                                       # swing
        if round_index % 4 == 3:
            log(f"round {round_index}: pos={tuple(round(v,1) for v in pos())}")
            cap.main()
    log("combat loop done")
    # read the character panel
    tap("start", 1, 1.5)
    cap.main()
    log("menu captured - read Total EXP from the screenshot")
    tap("b", 2, 0.6)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
