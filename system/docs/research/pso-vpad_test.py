"""Drive the game through a virtual XInput pad - the path that needs no keyboard and no focus.

Measured over three rounds: no keyboard delivery reaches this session, in either encoding, while the operator's controller works. The app's pad module says
what it forwards - "the view forwards the operator's controller to the session it shows" - and the plane's own helper describes a "focus-independent
XInput virtual pad" (`pso_coop_setup.xinput_pad`, `gbox/vpad_win.py`). This machine has `vgamepad` installed and ViGEmBus running, so a virtual pad can
be created and pressed.

If the app polls XInput for the pad it forwards, pressing the virtual pad should move the character - which would give the bot a working input path that
survives focus changes entirely.

The test holds the left stick up for 0.8 s, then left for 0.8 s, measuring the character's movement after each, and also sends a plain A button press.
"""
import math
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import map_exit as ME                                              # noqa: E402

try:
    import vgamepad as vg
except Exception as exc:                                          # noqa: BLE001
    raise SystemExit(f"vgamepad unavailable: {exc}")


def measure(label, action, seconds=0.8):
    before = ME.read_pos()
    action(seconds)
    time.sleep(0.3)
    after = ME.read_pos()
    moved = math.dist(before, after)
    print(f"{label}: {moved:.2f} units  ({tuple(round(v, 1) for v in before)} -> {tuple(round(v, 1) for v in after)})")
    return moved


def stick(gamepad, x=0.0, y=0.0, seconds=0.8):
    gamepad.left_joystick_float(x_value_float=x, y_value_float=y)
    gamepad.update()
    time.sleep(seconds)
    gamepad.left_joystick_float(x_value_float=0.0, y_value_float=0.0)
    gamepad.update()


if __name__ == "__main__":
    pad = vg.VX360Gamepad()
    print("virtual pad created:", type(pad).__name__)
    time.sleep(1.0)
    measure("stick up", lambda s: stick(pad, 0.0, 1.0, s))
    measure("stick down", lambda s: stick(pad, 0.0, -1.0, s))
    measure("stick left", lambda s: stick(pad, -1.0, 0.0, s))
    measure("stick right", lambda s: stick(pad, 1.0, 0.0, s))

    def press_a(seconds):
        pad.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_A)
        pad.update()
        time.sleep(0.2)
        pad.release_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_A)
        pad.update()
        time.sleep(seconds)

    measure("A press", press_a, 0.4)
    pad.reset()
    pad.update()
    print("done")
