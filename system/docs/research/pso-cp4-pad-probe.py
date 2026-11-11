"""CP4 round 103: can this process provide the missing pad? Create a ViGEm pad, keep it alive, and see what probe_pads reports.

If probe_pads sees it (an XInput slot that reports), then a launch's keyboard-fallback path binds THAT slot - and the agent can
drive the game by feeding the pad, with no focus games at all (vpad.apply is focus-independent by design).
"""
import json
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")

from gbox import pad_bind, vpad_win  # noqa: E402


def main():
    print("available:", vpad_win.available())
    before = pad_bind.probe_pads()
    print("probe before:", json.dumps(before, default=str)[:400])
    try:
        vp = vpad_win.VGamepad()
    except Exception as exc:                          # noqa: BLE001
        print(f"VGamepad() failed: {type(exc).__name__}: {exc}")
        return 1
    print(f"created pad on XInput slot {vp.slot}")
    time.sleep(1.0)
    during = pad_bind.probe_pads()
    print("probe during:", json.dumps(during, default=str)[:400])
    print("live_slots:", pad_bind.live_slots(during))
    print("choose_slot:", pad_bind.choose_slot(during))
    # feed it a press and read the slot state back, so we know the pad is not a phantom
    result = vp.apply([{"key": "a", "frames": 2}])
    print("apply:", result)
    time.sleep(0.5)
    after_press = pad_bind.probe_pads()
    print("probe after press:", json.dumps(after_press, default=str)[:400])
    vp.close()
    time.sleep(0.5)
    print("probe after close:", json.dumps(pad_bind.probe_pads(), default=str)[:400])
    return 0


if __name__ == "__main__":
    sys.exit(main())
