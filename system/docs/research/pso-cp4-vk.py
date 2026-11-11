"""CP4: try virtual-key injection (Dolphin's Qt window may translate VK, while DInput reads scancodes)."""
import ctypes
import sys
import time
from ctypes import wintypes

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp\tools")

from pso_boot import Plane, Reader                      # noqa: E402
from gbox import pso_boot_walk as W                     # noqa: E402

GAME_HWND = 660428
VK_RETURN = 0x0D


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_ulonglong)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 8)]


def vk_press(vk: int) -> None:
    user32 = ctypes.windll.user32
    down = _INPUT(type=1, ki=KEYBDINPUT(vk, 0, 0, 0, 0))
    up = _INPUT(type=1, ki=KEYBDINPUT(vk, 0, 0x0002, 0, 0))
    user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(down))
    time.sleep(0.08)
    user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(up))


def main():
    user32 = ctypes.windll.user32
    user32.ShowWindow(GAME_HWND, 9)
    user32.SetForegroundWindow(GAME_HWND)
    time.sleep(0.4)
    print("foreground:", user32.GetForegroundWindow() == GAME_HWND)
    plane = Plane()
    session = plane.running()
    if not session:
        print("no session")
        return 1
    reader = Reader(plane, session["session_id"])
    for attempt in range(3):
        vk_press(VK_RETURN)
        time.sleep(2.0)
        state = W.state(reader)
        print(f"attempt {attempt + 1}: mode={state.get('mode')} floor={state.get('floor')} "
              f"player={state.get('player')}")
        if state.get("mode") not in (None, 0):
            print("VK press landed")
            return 0
    print("VK presses also ignored")
    return 3


if __name__ == "__main__":
    sys.exit(main())
