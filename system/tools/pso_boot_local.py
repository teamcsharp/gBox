"""CP4 path 1: drive the boot walk from ONE long-lived process with direct SendInput.

`pso_boot.py` presses through the plane's HTTP relay, which is asynchronous: the worker's input thread sends the keys
later, and `adapters._win_input_in_front` only accepts pad input while the game's root window is the foreground window *at
that moment*. A round-trip through the API therefore loses the focus it just raised.

This driver removes the hop: it raises the window itself, asserts it is foreground, and injects the scan codes with the
same `SendInput` the worker uses (`gbox.adapters._SCAN` / `PAD_KEYS`), all in one process, polling RAM through the plane's
`read_memory` (which is proven to work on the i9 session).

    python system/tools/pso_boot_local.py --start-at press_start
"""
from __future__ import annotations

import argparse
import ctypes
import sys
import time
from ctypes import wintypes

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system\tools")

from gbox import pso_boot_walk as W                     # noqa: E402
from gbox.adapters import _SCAN, PAD_KEYS, _pid_window, win_bring_to_front  # noqa: E402
from pso_boot import Plane, Reader                      # noqa: E402

_ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", _ULONG_PTR)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 8)]


KEYEVENTF_KEYUP = 0x0002


def emulator_pid() -> int | None:
    """The pid whose top-level window is the worker's Dolphin (title contains 'Dolphin')."""
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if "Dolphin" in buf.value:
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                found.append(pid.value)
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def scancode(name: str, player: int = 1) -> tuple[int, int]:
    keys = PAD_KEYS.get(player, PAD_KEYS[1])
    mapped = keys.get(name, name)
    return _SCAN.get(mapped, _SCAN.get(str(mapped).lower(), (0, 0)))


def send(scan: int, extended: int) -> None:
    inp = _INPUT()
    inp.type = 1
    inp.ki = KEYBDINPUT(0, scan, 0x0001 | (0x0002 if extended else 0), 0, 0)      # KEYEVENTF_SCANCODE
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def release(scan: int, extended: int) -> None:
    inp = _INPUT()
    inp.type = 1
    inp.ki = KEYBDINPUT(0, scan, 0x0001 | KEYEVENTF_KEYUP | (0x0002 if extended else 0), 0, 0)
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def foreground_is(pid: int) -> bool:
    """`adapters._win_input_in_front`'s rule: the game root window must be the foreground window."""
    user32 = ctypes.windll.user32
    h = _pid_window(pid)
    if not h:
        return False
    root = user32.GetAncestor(h, 2) or h
    return user32.GetForegroundWindow() == root


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-at", default="press_start")
    ap.add_argument("--settle", type=float, default=1.8)
    args = ap.parse_args()

    pid = emulator_pid()
    if not pid:
        print("no Dolphin window found; launch a session first")
        return 1
    plane = Plane()
    session = plane.running()
    if not session:
        print("no running session")
        return 1
    sid = session["session_id"]
    reader = Reader(plane, sid)
    print(f"emulator pid {pid}, session {sid}")

    def press(keys) -> None:
        if not foreground_is(pid):
            win_bring_to_front(pid)
            time.sleep(0.4)
        assert foreground_is(pid), "game window is not foreground; keys would be dropped"
        for name in keys:
            scan, ext = scancode(name)
            if not scan:
                print(f"  no scan code for {name!r}")
                continue
            send(scan, ext)
        time.sleep(0.12)
        for name in keys:
            scan, ext = scancode(name)
            if scan:
                release(scan, ext)
        print(f"  pressed {keys}")

    result = W.walk(lambda: W.state(reader), press, settle=args.settle, log=print, start_at=args.start_at)
    print(f"result: {dict(ok=result['ok'], arrived=result['arrived'], why=result['why'])}")
    return 0 if result["arrived"] else 1


if __name__ == "__main__":
    sys.exit(main())
