"""List the top-level windows so the gBox app window can be identified reliably."""
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32


@ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
def each(hwnd, _l):
    if not user32.IsWindowVisible(hwnd):
        return True
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    title = buf.value.strip()
    if not title:
        return True
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls, 256)
    print(f"hwnd {hwnd:#010x} pid {pid.value:6d} class {cls.value[:28]:<28} title {title[:70]}")
    return True


print("visible top-level windows:")
user32.EnumWindows(each, 0)

import sys                                                              # noqa: E402
sys.path.insert(0, r"C:\_tools\gBox\.tmp")
import game_input as G                                                  # noqa: E402

print("game_input.app_window():", G.app_window())
