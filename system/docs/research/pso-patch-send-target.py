"""Send keys to the gBox window, not to the emulator's window - the app is what forwards them into the game.

Measured: with the game live (floor 1, 91 entities, PiP active, gBox foreground, focus and permission both true), a held direction moved the character
**0.0 units**. `win_send_keys(emulator_pid, ...)` picks a window with `_pid_window`, which requires `IsWindowVisible` and not iconic - and gBox runs
Dolphin headless (`-b`), so the emulator's own windows are hidden and the one it may still find is not the render surface. Keys sent there go nowhere.

The app is the thing that receives the keyboard and forwards it into the docked game: `app_window()` returns the **gBox** window for exactly this
setup. So `send` now resolves the pid of the window it is actually going to send to - the gBox window's owner - instead of the emulator's pid.

That is the difference between typing into a window nobody reads and typing into the app that relays.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\game_input.py")
text = path.read_text(encoding="utf-8")

start = text.find("def send(")
end = text.find("def win_send_keys(")
if start < 0 or end < 0:
    raise SystemExit("send() or win_send_keys() not found")

body = '''def _owner_pid(hwnd):
    """The process id that owns a window."""
    pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def send(events, attempts=2):
    """Deliver keys to the window that actually carries them into the game.

    gBox runs the emulator headless and forwards the keyboard itself, so the target is the gBox window's process, found through `app_window()` - not
    the emulator pid, whose visible window (if any) is not the render surface.
    """
    hwnd = app_window()
    if not hwnd:
        return False
    target = _owner_pid(hwnd)
    for _ in range(attempts):
        try:
            win_send_keys(target, events, polite=False)
            return True
        except RuntimeError as exc:
            if "must be active" not in str(exc) and "isn't open" not in str(exc):
                raise
            time.sleep(0.15)
    return False


'''
text = text[:start] + body + text[end:]
if "import ctypes.wintypes" not in text and "ctypes" in text:
    pass
path.write_text(text, encoding="utf-8")
print("send now targets the window that forwards into the game")
