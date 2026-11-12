"""Send game input reliably: raise the gBox window, verify it holds the keyboard, send immediately (never click afterwards).

The strict adapter path refuses when the game window is not in front, and a mouse click after raising hands focus back to whatever window
is on top. So the working sequence is: restore + topmost-toggle + foreground, confirm `_win_input_in_front`, then send keys at once while
re-checking before every batch.
"""
import ctypes
import sys
import time
from ctypes import wintypes

sys.path.insert(0, r"C:\_tools\gBox\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp")

from gbox import adapters                                          # noqa: E402

import session as _session                                          # noqa: E402

user32 = ctypes.windll.user32
PID = None                  # resolved at runtime through session.py


def app_window():
    """The window to raise for input.

    Order matters: when the emulator runs standalone it owns a visible top-level window, and keys must go there; when it is docked inside
    the app it has no top-level window of its own, so the app's window is the target.
    """
    try:
        target_pid = _pid()
    except Exception:                                            # noqa: BLE001
        target_pid = None

    standalone = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def by_pid(hwnd, _l):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == target_pid:
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            if buf.value.strip():
                standalone.append(hwnd)
        return True

    if target_pid:
        user32.EnumWindows(by_pid, 0)
        if standalone:
            return standalone[0]                                 # standalone emulator: send straight to it

    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _l):
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        if buf.value.strip() == "gBox":
            found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
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
    return None


def raise_window():
    """NEVER raises a window. The operator must be able to type without interruption.

    Kept as a function so existing callers do not break, but it deliberately does nothing and reports failure.
    """
    return False


def clear_topmost(hwnd=None):
    """Release an always-on-top window. Safe to call whether or not it is pinned."""
    hwnd = hwnd or app_window()
    if not hwnd:
        return False
    GWL_EXSTYLE, WS_EX_TOPMOST, HWND_NOTOPMOST = -20, 0x00000008, -2
    released = False
    for target in (hwnd, user32.GetAncestor(hwnd, 2)):
        if not target:
            continue
        style = user32.GetWindowLongW(target, GWL_EXSTYLE)
        if style & WS_EX_TOPMOST:
            user32.SetWindowLongW(target, GWL_EXSTYLE, style & ~WS_EX_TOPMOST)
        user32.SetWindowPos(target, HWND_NOTOPMOST, 0, 0, 0, 0,
                            0x0001 | 0x0002 | 0x0010 | 0x0020)   # NOSIZE|NOMOVE|NOACTIVATE|FRAMECHANGED
        if not (user32.GetWindowLongW(target, GWL_EXSTYLE) & WS_EX_TOPMOST):
            released = True
    return released


def _pid():
    global PID
    if PID is None:
        PID = _session.pid()
    return PID


def game_has_focus():
    """True when the game's window is already the foreground window."""
    hwnd = app_window()
    if not hwnd:
        return False
    try:
        root = user32.GetAncestor(hwnd, 2)
        return bool(adapters._win_input_in_front(user32, root, False))
    except Exception:
        return False


def _owner_pid(hwnd):
    """The process id that owns a window."""
    pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def send(events, attempts=2):
    """Deliver input as real key events to the window that relays them into the emulator.

    This is the path that works: `win_send_keys` sends key events, and the app forwards them into the game. The `session_op`/padstate route does not carry bot
    input at all - the mirror only reflects the operator's physical pad, proven by reading XInput around a press and seeing no button change.

    It requires the game (or gBox) to be the active window, which is inherent to this path and is why the game must be in front.
    """
    hwnd = app_window()
    if not hwnd:
        return False
    target = _owner_pid(hwnd)
    for attempt in range(attempts):
        try:
            win_send_keys(target, events, polite=False)
            return True
        except RuntimeError as exc:
            message = str(exc)
            if "must be active" not in message and "isn't open" not in message:
                raise
            if attempt == attempts - 1:
                return False
            time.sleep(0.15)
    return False


def tap(key):
    """One press and release in a single call."""
    return send([{"key": key, "down": True}, {"key": key, "down": False}])


def move(*keys):
    """Several taps in one call: down, up, down, up ... for each key in order."""
    events = []
    for key in keys:
        events.append({"key": key, "down": True})
        events.append({"key": key, "down": False})
    return send(events)


def win_send_keys(pid, events, polite=False):
    return adapters.win_send_keys(pid, events, polite=polite)


if __name__ == "__main__":
    import struct

    import mem_write

    hwnd = app_window()
    print("raised:", raise_window(hwnd), "front:",
          adapters._win_input_in_front(user32, user32.GetAncestor(hwnd, 2), False) if hwnd else None)

    def pos():
        actor = int.from_bytes(mem_write.read_bytes(0x8050EA10, 4), "big")
        x, y, z = struct.unpack(">fff", mem_write.read_bytes(actor + 0x38, 12))
        return (round(x, 1), round(y, 1), round(z, 1))

    print("start:", pos())
    for key in ("up", "down", "left", "right"):
        ok = send([{"key": key, "down": True}])
        time.sleep(1.1)
        send([{"key": key, "down": False}])
        time.sleep(0.2)
        print(f"  {key} sent={ok} -> {pos()}")
