"""Try scancode input: Dolphin's DirectInput keyboard reads scan codes, not virtual-key codes.

The launch line proves the emulator is configured for background input with the keyboard on port 1:

    -C Dolphin.Input.BackgroundInput=True
    -C Dolphin.Core.SIDevice0=6
    -C Dolphin.General.HotkeysRequireFocus=False

so configuration is not the problem. What is left is *how* the key events are synthesised. DirectInput devices read **scan codes** from the hardware
stream; a `SendInput` that carries only a virtual-key code (no `KEYEVENTF_SCANCODE`, scan 0) can be invisible to them even though the window receives it.

This sends the same press both ways and measures the character's movement for each:

  1. virtual-key only (what the adapter does now);
  2. scancode (`KEYEVENTF_SCANCODE` with the hardware scan code).

If the second moves the character and the first does not, that is the whole bug.
"""
import ctypes
import math
import time
from ctypes import wintypes

import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import game_input as G                                             # noqa: E402
import map_exit as ME                                              # noqa: E402

user32 = ctypes.windll.user32
KEYEVENTF_SCANCODE, KEYEVENTF_KEYUP = 0x0008, 0x0002

SCAN = {"up": 0x48, "down": 0x50, "left": 0x4B, "right": 0x4D, "a": 0x1E, "b": 0x30}


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _U(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _U)]


def scancode_press(key, seconds=0.6):
    scan = SCAN[key]
    down = INPUT(type=1, union=_U(ki=KEYBDINPUT(wVk=0, wScan=scan, dwFlags=KEYEVENTF_SCANCODE, time=0, dwExtraInfo=None)))
    up = INPUT(type=1, union=_U(ki=KEYBDINPUT(wVk=0, wScan=scan, dwFlags=KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP,
                                              time=0, dwExtraInfo=None)))
    user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))
    time.sleep(seconds)
    user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))


def measure(label, action):
    before = ME.read_pos()
    action()
    time.sleep(0.3)
    after = ME.read_pos()
    moved = math.dist(before, after)
    print(f"{label}: {moved:.2f} units  ({tuple(round(v, 1) for v in before)} -> {tuple(round(v, 1) for v in after)})")
    return moved


if __name__ == "__main__":
    print("focused:", G.game_has_focus())
    measure("virtual-key via adapter (G.send)", lambda: (
        G.send([{"key": "up", "down": True}]), time.sleep(0.6), G.send([{"key": "up", "down": False}])))
    measure("scancode SendInput", lambda: scancode_press("up", 0.6))
    measure("scancode again", lambda: scancode_press("up", 0.6))
