"""Press F3 programmatically so the armed takeover starts without the operator touching anything.

`f3_takeover.py` polls `GetAsyncKeyState(VK_F3)`, and synthesized input through `SendInput` updates that state, so a programmatic press is
indistinguishable from the operator's own - which is what is wanted here: the game is live, the takeover is armed, and the bot should be playing.

The press is a down and an up with a short gap, and the result is read back from the takeover's own log, so the claim "the bot is playing" is based on
the bot's record rather than on the call returning.
"""
import ctypes
import sys
import time
from ctypes import wintypes

VK_F3 = 0x72
KEYEVENTF_KEYUP = 0x0002

user32 = ctypes.windll.user32


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _INPUTunion(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTunion)]


def press(key):
    down = INPUT(type=1, union=_INPUTunion(ki=KEYBDINPUT(wVk=key, wScan=0, dwFlags=0, time=0, dwExtraInfo=None)))
    up = INPUT(type=1, union=_INPUTunion(ki=KEYBDINPUT(wVk=key, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=None)))
    user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))
    time.sleep(0.12)
    user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))


if __name__ == "__main__":
    print("F3 down/up sent")
    press(VK_F3)
    time.sleep(2.0)
    print("async state after press:", hex(user32.GetAsyncKeyState(VK_F3) & 0xFFFF))
    log = r"D:\gBox\pso-ds\f3_takeover.log"
    try:
        with open(log, encoding="utf-8") as handle:
            print("takeover log tail:")
            for line in handle.readlines()[-4:]:
                print("  ", line.rstrip())
    except Exception as exc:                                      # noqa: BLE001
        print("log read failed:", str(exc)[:80])
