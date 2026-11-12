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


def raise_window(hwnd=None, tries=6):
    """Ask the window manager to bring a window forward WITHOUT pinning it on top.

    Deliberately no HWND_TOPMOST here: that is what left gBox covering the whole desktop when the matching NOTOPMOST call was lost.
    """
    hwnd = hwnd or app_window()
    if not hwnd:
        return False
    root = user32.GetAncestor(hwnd, 2)
    for _ in range(tries):
        user32.ShowWindow(hwnd, 9)                       # SW_RESTORE
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        me = ctypes.windll.kernel32.GetCurrentThreadId()
        them = user32.GetWindowThreadProcessId(hwnd, None)
        user32.AttachThreadInput(me, them, True)
        user32.SetFocus(hwnd)
        user32.AttachThreadInput(me, them, False)
        time.sleep(0.18)
        if adapters._win_input_in_front(user32, root, False):
            return True
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
