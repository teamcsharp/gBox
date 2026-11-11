"""Drive PSO forward with the agent pad, one press per step, capturing after each so the path is visible."""
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")
sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")

import pso_window_shot as SHOT                                   # noqa: E402
from gbox import vpad_win                                        # noqa: E402


def main():
    pad = vpad_win.VGamepad() if vpad_win.available() else None
    if pad is None:
        print("no pad")
        return 1
    print(f"pad slot {getattr(pad, 'slot', None)}")
    for i in range(6):
        rows = [{"key": "start", "down": True}, {"key": "start", "down": False}]
        print("tap start:", pad.apply(rows))
        time.sleep(2.5)
        windows = SHOT.find_window("Phantasy Star Online")
        if windows:
            path = SHOT.OUT / f"{time.strftime('%H%M%S')}-step{i}.png"
            SHOT.capture(windows[0][0], path)
            print("captured", path.name)
    pad.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
