"""A virtual Xbox pad the bot can drive: no keyboard, no window focus, no window at all.

Verified this round: `vgamepad` creates a ViGEmBus pad and accepts button and stick input. The plane itself describes this technique -
`pso_coop_setup.xinput_pad` builds "a focus-independent XInput virtual pad" - and the app forwards the operator's controller into the game, so a virtual
pad occupies exactly the channel that is known to work.

Every keyboard route failed on rounds 1-3 (virtual keys and scancodes, focused and unfocused, every target window), while the controller never did. This
module is that controller:

    pad = Pad()
    pad.calibrate(read_position)      # four stick directions, measured against the character
    pad.move(dx, dz, seconds)         # hold the stick in the world direction that moves toward (dx, dz)
    pad.press("a", 0.25)              # the interact / attack button

The calibration is unavoidable because PSO moves the character relative to the camera: the same stick direction means a different world direction after a
turn, so it is measured rather than assumed, exactly as the keyboard path did.
"""
import math
import time

try:
    import vgamepad as vg
except Exception as exc:                                          # noqa: BLE001
    raise SystemExit(f"vgamepad is unavailable: {exc}")

BUTTONS = {
    "a": vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
    "b": vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
    "x": vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
    "y": vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
    "start": vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
    "back": vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
    "lb": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
    "rb": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
}

# the four stick directions as (x, y) in XInput's convention, y up
DIRECTIONS = {"up": (0.0, 1.0), "down": (0.0, -1.0), "left": (-1.0, 0.0), "right": (1.0, 0.0)}


class Pad:
    def __init__(self):
        self.pad = vg.VX360Gamepad()
        time.sleep(0.4)
        self.table = {}

    def stick(self, x, y, seconds=0.35):
        self.pad.left_joystick_float(x_value_float=x, y_value_float=y)
        self.pad.update()
        time.sleep(seconds)
        self.pad.left_joystick_float(x_value_float=0.0, y_value_float=0.0)
        self.pad.update()

    def press(self, key, seconds=0.25):
        button = BUTTONS.get(key)
        if button is None:
            return False
        self.pad.press_button(button=button)
        self.pad.update()
        time.sleep(seconds)
        self.pad.release_button(button=button)
        self.pad.update()
        return True

    def calibrate(self, read_position, seconds=0.35):
        """Measure which stick direction moves the character which way."""
        table = {}
        for name, (x, y) in DIRECTIONS.items():
            before = read_position()
            if before is None:
                continue
            self.stick(x, y, seconds)
            time.sleep(0.15)
            after = read_position()
            if after is None:
                continue
            table[name] = (after[0] - before[0], after[2] - before[2])
        self.table = table
        return table

    def best(self, dx, dz):
        """The stick direction whose measured movement best matches (dx, dz)."""
        if not self.table:
            return None
        length = math.hypot(dx, dz)
        if length < 1e-6:
            return None
        want = (dx / length, dz / length)
        best_name, best_score = None, -2.0
        for name, (mx, mz) in self.table.items():
            size = math.hypot(mx, mz)
            if size < 1e-6:
                continue
            score = (mx / size) * want[0] + (mz / size) * want[1]
            if score > best_score:
                best_name, best_score = name, score
        return best_name if best_score > 0.3 else None

    def move(self, dx, dz, seconds=0.3):
        """Hold the stick in the direction that moves toward (dx, dz). Returns the direction used."""
        name = self.best(dx, dz)
        if name is None:
            return None
        self.stick(*DIRECTIONS[name], seconds=seconds)
        return name

    def reset(self):
        self.pad.reset()
        self.pad.update()


if __name__ == "__main__":
    pad = Pad()
    print("virtual pad ready; testing XInput state reads")
    for name in ("a", "b"):
        print(f"  press {name}:", pad.press(name, 0.2))
    for name, (x, y) in DIRECTIONS.items():
        pad.stick(x, y, 0.2)
        print(f"  stick {name}: sent")
    pad.reset()
    print("done")
