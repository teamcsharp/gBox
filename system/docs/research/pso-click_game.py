"""Click on the game view to give it DOM focus, so keys reach the game again.

The input path dead-ends on DOM focus: the app forwards keys to the emulator only while the game surface holds focus, and clicking a toolbar button moves
that focus onto the button. Until the page is reloaded with the refocus fix, the way to hand the keyboard back is to click the game itself.

This synthesises a real mouse click at the centre of the gBox window - the game view occupies most of the PiP - and then immediately tests whether a held
direction moves the character. The click cannot hurt: PSO is pad-driven, so a click on the picture does nothing in the game.
"""
import ctypes
import math
import struct
import sys
import time
from ctypes import wintypes

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import game_input as G                                             # noqa: E402
import map_exit as ME                                              # noqa: E402
import session as S                                                # noqa: E402

user32 = ctypes.windll.user32
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004


def click(x, y):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.1)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def window_rect(hwnd):
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


if __name__ == "__main__":
    hwnd = G.app_window()
    left, top, width, height = window_rect(hwnd)
    print(f"gBox window {left},{top} {width}x{height}")
    # the game occupies the PiP; a click a little below centre stays inside the picture and away from the top bar
    click(left + width // 2, top + int(height * 0.6))
    time.sleep(0.8)
    before = ME.read_pos()
    G.send([{"key": "up", "down": True}])
    time.sleep(0.6)
    G.send([{"key": "up", "down": False}])
    time.sleep(0.3)
    after = ME.read_pos()
    print("moved after the click:", round(math.dist(before, after), 2), "units")
    pointer = int.from_bytes(S.read_memory(0x8050EA10, 4), "big")
    blob = S.read_memory(pointer, 0x340)
    print("position:", tuple(round(v, 1) for v in struct.unpack(">fff", blob[0x38:0x44])),
          "| hp:", struct.unpack(">H", blob[0x32C:0x32E])[0])
