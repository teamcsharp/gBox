"""CP4: restore the game window, verify it, and press in one tight sequence."""
import ctypes
import sys
import time
from ctypes import wintypes

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp\tools")

from pso_boot import Plane, Reader                      # noqa: E402
from gbox import pso_boot_walk as W                     # noqa: E402
import pso_boot_local as L                              # noqa: E402

GAME_HWND = 660428


def main():
    user32 = ctypes.windll.user32
    fg_before = user32.GetForegroundWindow()
    user32.ShowWindow(GAME_HWND, 9)          # SW_RESTORE
    user32.ShowWindow(GAME_HWND, 5)          # SW_SHOW
    user32.SetForegroundWindow(GAME_HWND)
    time.sleep(0.4)
    focused = user32.GetForegroundWindow() == GAME_HWND
    print(f"hwnd {GAME_HWND}: iconic={bool(user32.IsIconic(GAME_HWND))} foreground={focused} (was {fg_before})")

    plane = Plane()
    session = plane.running()
    if not session:
        print("no session")
        return 1
    reader = Reader(plane, session["session_id"])
    for attempt in range(4):
        for name in ("start",):
            scan, ext = L.scancode(name)
            L.send(scan, ext)
        time.sleep(0.15)
        for name in ("start",):
            scan, ext = L.scancode(name)
            L.release(scan, ext)
        time.sleep(2.0)
        state = W.state(reader)
        print(f"attempt {attempt + 1}: foreground={user32.GetForegroundWindow() == GAME_HWND} "
              f"mode={state.get('mode')} floor={state.get('floor')} player={state.get('player')}")
        if state.get("mode") not in (None, 0):
            print("PRESS LANDED")
            return 0
    return 3


if __name__ == "__main__":
    sys.exit(main())
