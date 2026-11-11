"""Capture the live game window wherever it is: the docked gBox app window or the emulator's own window.

After a relaunch the game can come up as its own Dolphin window instead of being docked inside the gBox app, so capturing the gBox window
returns a black frame. This finds the largest visible window owned by the running emulator pid (or falls back to the gBox app window)
and saves it through the same screenshot helper.
"""
import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import pso_window_shot as SHOT                                     # noqa: E402
import session as S                                                # noqa: E402

user32 = ctypes.windll.user32
OUT = Path(r"D:\gBox\pso-ds\demo")


def windows_for(pid):
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _l):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid or not user32.IsWindowVisible(hwnd):
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width, height = rect.right - rect.left, rect.bottom - rect.top
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        found.append((width * height, hwnd, buf.value.strip(), width, height))
        return True

    user32.EnumWindows(cb, 0)
    found.sort(reverse=True)
    return found


def gbox_app_window():
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


def best_window():
    """(hwnd, label): the emulator's own largest window, else the gBox app window."""
    try:
        pid = S.pid()
    except Exception:                                            # noqa: BLE001
        pid = None
    if pid:
        candidates = windows_for(pid)
        for area, hwnd, title, width, height in candidates:
            if width > 320 and height > 240:
                return hwnd, f"emulator pid {pid} '{title}' {width}x{height}"
    app = gbox_app_window()
    return (app, "gBox app") if app else (None, "none")


def main():
    hwnd, label = best_window()
    if not hwnd:
        print("no window")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{__import__('time').strftime('%H%M%S')}-game.png"
    SHOT.capture(hwnd, path)
    print(f"captured {label} -> {path.name} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
