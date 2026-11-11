"""Target the emulator's DOCKED child window, not the gBox app shell that hosts it.

Measured: with the game docked, `app_window()` returned the gBox window (owner pid 60304) while the emulator is pid 45920, and a held "up" moved the
character 0.0 units - the keys were being delivered to the shell, not to the game's child window. `EnumWindows` only walks top-level windows, so
a docked emulator is invisible to it.

This adds a child-window search by pid (EnumChildWindows over every top-level window) and prefers that when it exists, which is the window that
actually owns the render surface and the input.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\game_input.py")
text = path.read_text(encoding="utf-8")

anchor = "    user32.EnumWindows(cb, 0)\n    return found[0] if found else None"
replacement = '''    user32.EnumWindows(cb, 0)
    if found:
        return found[0]

    # docked emulator: it has no top-level window, but its render window is a child somewhere inside the app
    if target_pid:
        children = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def child_cb(hwnd, _l):
            if not user32.IsWindowVisible(hwnd):
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == target_pid:
                children.append(hwnd)
            return True

        tops = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def top_cb(hwnd, _l):
            if user32.IsWindowVisible(hwnd):
                tops.append(hwnd)
            return True

        user32.EnumWindows(top_cb, 0)
        for top in tops:
            user32.EnumChildWindows(top, child_cb, 0)
            if children:
                return children[0]
    return None'''

if anchor not in text:
    raise SystemExit("anchor not found")
text = text.replace(anchor, replacement)
path.write_text(text, encoding="utf-8")
print("game_input now finds the docked emulator's child window")
