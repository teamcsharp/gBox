"""Free one inventory slot with the game's own item menu: START -> Item Pack -> cursor to Item List -> select -> show the
submenu (Equip / Drop / Toss / See), capturing every step so the right key is visible rather than guessed."""
import json
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import capture_gbox_app as cap                                     # noqa: E402
from gbox.adapters import win_send_keys                            # noqa: E402

PID = 36964


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


def tap(key, times=1, gap=0.7):
    import ctypes
    user32 = ctypes.windll.user32
    for _ in range(times):
        hwnd = gbox_hwnd()
        if hwnd:
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.12)
        try:
            win_send_keys(PID, [{"key": key, "down": True}, {"key": key, "down": False}])
        except Exception as exc:                                 # noqa: BLE001
            print("tap failed:", exc)
        time.sleep(gap)


def capture(label):
    cap.main()
    print(label, flush=True)


def main():
    tap("start", 1, 1.0)
    capture("menu")
    tap("a", 1, 1.2)                                           # Item Pack
    capture("item pack")
    tap("ddown", 1, 0.5)                                       # cursor to the Item List below
    capture("cursor down")
    tap("a", 1, 1.0)                                           # select an item
    capture("item selected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
