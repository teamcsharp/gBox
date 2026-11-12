"""Does the padstate mirror carry the bot's presses? Read XInput slot 0 around a bot press.

The log says the worker is `padstate: mirroring the operator's pad on XInput slot 0`, and the emulator's config reads `XInput/0/Gamepad`. XInput devices do not
need focus - Dolphin polls them every frame - so if the bot's `send_input` events reach that mirror, a headless session would receive them after all.

The test reads the mirror's state directly (XInputGetState) before and during a bot press, and reports whether the buttons change. That distinguishes two
worlds:

  * buttons change -> the mirror carries the bot's input, and the problem is elsewhere (the emulator binding, or the pad not being polled);
  * buttons do not change -> the mirror only reflects the operator's physical pad, and the bot's events never reach the device the game reads.
"""
import ctypes
import sys
import time
from ctypes import wintypes

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import game_input as G                                             # noqa: E402


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", wintypes.DWORD), ("wButtons", wintypes.WORD),
                ("bLeftTrigger", ctypes.c_ubyte), ("bRightTrigger", ctypes.c_ubyte),
                ("sThumbLX", ctypes.c_short), ("sThumbLY", ctypes.c_short),
                ("sThumbRX", ctypes.c_short), ("sThumbRY", ctypes.c_short)]


def load_xinput():
    for name in ("XInput1_4.dll", "XInput1_3.dll", "XInput9_1_0.dll"):
        try:
            return ctypes.windll.LoadLibrary(name)
        except Exception:                                         # noqa: BLE001
            continue
    return None


def snapshot(fn):
    rows = []
    for slot in range(4):
        state = XINPUT_STATE()
        code = fn.XInputGetState(slot, ctypes.byref(state))
        rows.append((slot, code, state.wButtons, state.sThumbLX, state.sThumbLY))
    return rows


if __name__ == "__main__":
    fn = load_xinput()
    if fn is None:
        raise SystemExit("no XInput library")

    print("before any bot press:")
    for slot, code, buttons, lx, ly in snapshot(fn):
        print(f"  slot {slot}: {'connected' if code == 0 else 'absent'} buttons=0x{buttons:04X} lx={lx} ly={ly}")

    # hold START down through the bot path and sample while it is held
    G.send([{"key": "start", "down": True}])
    saw_press = False
    for _ in range(10):
        time.sleep(0.15)
        for slot, code, buttons, lx, ly in snapshot(fn):
            if code == 0 and buttons:
                print(f"  DURING press slot {slot}: buttons=0x{buttons:04X} lx={lx} ly={ly}")
                saw_press = True   # a BUTTON appeared; stick noise alone is the operator's pad
    G.send([{"key": "start", "down": False}])
    time.sleep(0.5)

    print("after release:")
    for slot, code, buttons, lx, ly in snapshot(fn):
        print(f"  slot {slot}: {'connected' if code == 0 else 'absent'} buttons=0x{buttons:04X} lx={lx} ly={ly}")

    print()
    print("VERDICT:", "the mirror carries the bot's press" if saw_press
          else "the mirror does NOT carry the bot's press - it only reflects the operator's pad")
