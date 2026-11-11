"""Diagnose the external input path: find the Dolphin window for a pid, its top-level ancestor, and whether the gBox app is
the foreground owner. win_send_keys refuses or silently misses when the top-level window is not in front.
"""
import sys

sys.path.insert(0, r"C:\_tools\gBox\system")

import ctypes
from ctypes import wintypes

from gbox import adapters

PID = 37032
user32 = ctypes.windll.user32


def pid_windows(pid):
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _l):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            root = user32.GetAncestor(hwnd, 2)
            found.append({"hwnd": hwnd, "title": buf.value, "class": cls.value,
                          "visible": bool(user32.IsWindowVisible(hwnd)), "root": root})
        return True

    user32.EnumWindows(cb, 0)
    return found


def main():
    print("foreground:", hex(user32.GetForegroundWindow()))
    windows = pid_windows(PID)
    print(f"windows owned by pid {PID}: {len(windows)}")
    for row in windows:
        print(f"  hwnd={row['hwnd']:#x} title={row['title']!r} class={row['class']!r} "
              f"visible={row['visible']} root={row['root']:#x}")
    h = adapters._pid_window(PID)
    print("_pid_window:", hex(h) if h else None)
    if h:
        root = user32.GetAncestor(h, 2)
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(root, title, 256)
        print("root:", hex(root), "title:", title.value, "foreground==root:", user32.GetForegroundWindow() == root)
        print("_win_input_in_front:", adapters._win_input_in_front(user32, root, False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
