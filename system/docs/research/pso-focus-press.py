"""Focus the gBox window, then post PSO presses to the docked game (the adapter's no-vpad keyboard path)."""
import ctypes
import json
import sys
import time
import urllib.request
from ctypes import wintypes

sys.path.insert(0, r"C:\_tools\gBox\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import capture_gbox_app as cap                                     # noqa: E402
from gbox.adapters import win_send_keys                            # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
user32 = ctypes.windll.user32


def call(path, timeout=60):
    req = urllib.request.Request(API + path, headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read() or b"null")


def focus_app() -> int | None:
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
    if not found:
        return None
    hwnd = found[0]
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.6)
    print("gBox hwnd:", hex(hwnd), "foreground:", user32.GetForegroundWindow() == hwnd)
    return hwnd


def main():
    sessions = call("/api/sessions?include_ended=false")
    if not sessions:
        print("no session")
        return 1
    pid = (sessions[0].get("detail") or {}).get("pid")
    print("session:", sessions[0]["session_id"], "dolphin pid:", pid)
    for i in range(3):
        focus_app()
        try:
            sent = win_send_keys(pid, [{"key": "start", "down": True}, {"key": "start", "down": False}])
            print("press", i, "sent:", sent)
        except Exception as exc:                                 # noqa: BLE001
            print("press", i, "failed:", type(exc).__name__, exc)
        time.sleep(2.0)
        cap.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
