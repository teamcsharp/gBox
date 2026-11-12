"""Prove the virtual pad appears as a real XInput device that another program can poll.

`vgamepad` accepted input, but that only proves the object works. What matters is whether the pad is visible on an XInput slot to *other* processes - the
app and the emulator poll there, so a pad that exists but is never enumerated is useless.

`XInputGetState(slot)` returns 0 when a controller is connected on that slot and 1167 when it is not, so reading the state before and after creating the
pad shows a slot becoming connected, and reading it while pressing a button proves the state carries through to a poller.
"""
import ctypes
import time
from ctypes import wintypes


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", wintypes.DWORD), ("wButtons", wintypes.WORD),
                ("bLeftTrigger", ctypes.c_ubyte), ("bRightTrigger", ctypes.c_ubyte),
                ("sThumbLX", ctypes.c_short), ("sThumbLY", ctypes.c_short),
                ("sThumbRX", ctypes.c_short), ("sThumbRY", ctypes.c_short)]


def slot_state(xinput, slot):
    state = XINPUT_STATE()
    code = xinput.XInputGetState(slot, ctypes.byref(state))
    return code, state


def describe(xinput):
    rows = []
    for slot in range(4):
        code, state = slot_state(xinput, slot)
        rows.append((slot, code, state.wButtons, state.sThumbLY))
    return rows


def load():
    for name in ("XInput1_4.dll", "XInput1_3.dll", "XInput9_1_0.dll"):
        try:
            return ctypes.windll.LoadLibrary(name)
        except Exception:                                        # noqa: BLE001
            continue
    raise SystemExit("no XInput library")


if __name__ == "__main__":
    xinput = load()
    print("before creating the pad:")
    for slot, code, buttons, ly in describe(xinput):
        print(f"  slot {slot}: code {code} {'connected' if code == 0 else 'not connected'}")
    import vgamepad as vg
    pad = vg.VX360Gamepad()
    time.sleep(0.8)
    print("after creating the pad:")
    for slot, code, buttons, ly in describe(xinput):
        print(f"  slot {slot}: code {code} {'CONNECTED' if code == 0 else 'not connected'}"
              f" buttons=0x{buttons:04X} LY={ly}")
    pad.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_A)
    pad.left_joystick_float(x_value_float=0.0, y_value_float=1.0)
    pad.update()
    time.sleep(0.4)
    print("while pressing A and holding the stick up:")
    for slot, code, buttons, ly in describe(xinput):
        print(f"  slot {slot}: code {code} buttons=0x{buttons:04X} LY={ly}"
              f"  {'A DOWN' if buttons & 0x1000 else ''} {'STICK UP' if ly > 10000 else ''}")
    pad.reset()
    pad.update()
    print("released")
