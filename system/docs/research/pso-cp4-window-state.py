"""CP4: why the focus will not stick - inspect the game window's state, restore it, and try a press."""
import ctypes
import sys
import time
from ctypes import wintypes

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp\tools")

from pso_boot import Plane, Reader                      # noqa: E402
from gbox import pso_boot_walk as W                     # noqa: E402
import pso_boot_local as L                              # noqa: E402


def main():
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _l):
        n = user32.GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if "Dolphin" in buf.value:
                found.append((hwnd, buf.value))
        return True

    user32.EnumWindows(cb, 0)
    print("Dolphin windows:", [(hwnd, title[:60]) for hwnd, title in found])
    for hwnd, title in found:
        print(f"  hwnd {hwnd}: visible={bool(user32.IsWindowVisible(hwnd))} iconic={bool(user32.IsIconic(hwnd))} "
              f"root={user32.GetAncestor(hwnd, 2)}")
    fg = user32.GetForegroundWindow()
    n = user32.GetWindowTextLengthW(fg)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(fg, buf, n + 1)
    print(f"foreground now: {fg} {buf.value[:60]!r}")

    plane = Plane()
    session = plane.running()
    if not session:
        print("no session")
        return 1
    reader = Reader(plane, session["session_id"])
    pid = L.emulator_pid()

    for hwnd, title in found:
        root = user32.GetAncestor(hwnd, 2) or hwnd
        user32.ShowWindow(root, 9)                       # SW_RESTORE
        user32.ShowWindow(root, 5)                       # SW_SHOW
        user32.BringWindowToTop(root)
        user32.SetForegroundWindow(root)
        time.sleep(0.5)
        print(f"after restore of {root}: foreground={user32.GetForegroundWindow() == root} "
              f"iconic={bool(user32.IsIconic(root))}")

    # one press and one read
    if pid:
        L.win_bring_to_front(pid)
        time.sleep(0.2)
        for name in ("start",):
            scan, ext = L.scancode(name)
            L.send(scan, ext)
        time.sleep(0.15)
        for name in ("start",):
            scan, ext = L.scancode(name)
            L.release(scan, ext)
        time.sleep(2.5)
    print("state after press:", W.state(reader))
    return 0


if __name__ == "__main__":
    sys.exit(main())
