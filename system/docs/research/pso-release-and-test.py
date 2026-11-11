"""Release every bound key (a killed driver can leave one held), dismiss any prompt, then verify the character can move again."""
import json
import struct
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp")

from gbox.adapters import win_send_keys                            # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "75cf966f35164149-4ec5d512e3484b02"
PID = 36964
KEYS = ("up", "down", "left", "right", "a", "b", "x", "y", "start", "l", "r", "z")


def read(address, length):
    body = json.dumps({"op": "read_memory", "args": {"address": address, "length": length}}).encode()
    req = urllib.request.Request(f"{API}/api/sessions/{SID}/rpc", data=body, method="POST",
                                 headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                          "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=15).read() or b'""')


def pos():
    actor = int(read(0x8050EA10, 4), 16)
    return struct.unpack(">fff", bytes.fromhex(read(actor + 0x38, 12))) if actor else None


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


def main():
    print("release all:", press([{"key": k, "down": False} for k in KEYS]))
    time.sleep(0.5)
    before = pos()
    print("before:", tuple(round(v, 1) for v in before))
    for key in ("up", "down", "left", "right"):
        press([{"key": key, "down": True}])
        time.sleep(0.6)
        press([{"key": key, "down": False}])
        time.sleep(0.3)
        now = pos()
        print(f"  {key}: {tuple(round(v,1) for v in now)} d=({now[0]-before[0]:.1f},{now[2]-before[2]:.1f})")
        before = now
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
