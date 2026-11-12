"""Prove the vpad probe now passes: create a pad, press, read back, ask pad_route.

Before this, `_vpad_works()` died on `from . import pad_route` with ModuleNotFoundError, so every press fell back to `win_send_keys` - which takes the window
focus, waits up to ten seconds for it, and blinds the RPC for about twenty-five. This runs the exact probe the adapter runs, against a real virtual pad, so
"the next launch will use the focus-free path" is a measurement rather than a hope.
"""
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import pad_route, vpad_win, xinput                   # noqa: E402

if __name__ == "__main__":
    handle = xinput.load()
    print("xinput handle:", handle)
    pad = vpad_win.VGamepad()
    print("vpad created, slot:", getattr(pad, "slot", None))
    time.sleep(0.5)

    slot = getattr(pad, "slot", None)
    before = pad_route.slot_reading(xinput.read(handle, slot))
    print("before:", before)

    print("press:", pad.apply([{"key": "a", "down": True}]))
    time.sleep(0.3)
    after = pad_route.slot_reading(xinput.read(handle, slot))
    print("after: ", after)

    pad.apply([{"key": "a", "down": False}])
    registered = pad_route.press_registered(before, after)
    print("\npress_registered:", registered)
    print("report:", pad_route.report("vpad" if registered else "keyboard", slot, registered))
    print("VERDICT:", "THE PROBE PASSES - next launch uses the focus-free pad"
          if registered else "probe still fails")

    close = getattr(pad, "close", None) or getattr(pad, "stop", None)
    if callable(close):
        close()
    print("pad closed")
