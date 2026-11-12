"""Will the next launch actually get a working virtual pad? Run the adapter's own setup path.

Every session so far predates the `pad_route.py` deployment, so the fix has never been exercised where it matters: `DolphinWinAdapter._setup_vpad` builds the
`GCPadNew.ini` that Dolphin reads, and `_vpad_works()` decides whether `send_input` uses the pad or falls back to the keyboard.

This instantiates the adapter without launching anything and calls those methods exactly as a launch would:

* `_setup_vpad(base)` must return an INI whose `Device` is the **virtual pad's slot**, not `XInput/0`, with `Always Connected` so a resting pad keeps the port up;
* `_vpad_works()` must return **True** - that is what makes `send_input` choose `vpad.apply` instead of `win_send_keys`.

If both hold, the next launch uses focus-free input; if either fails, the relaunch would not have helped and it is better to know now.
"""
import os
import sys

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox.adapters import DolphinWinAdapter                     # noqa: E402


def make_adapter():
    """An adapter with only what setup needs - no process, no launch."""
    adapter = object.__new__(DolphinWinAdapter)
    adapter.gecko_id = "GPOE8P"                 # the owned disc: PSO Episode I & II Plus
    adapter.capture_backend = None
    adapter.coop_players = 1
    adapter.vpad = adapter.vpad2 = adapter.vpad3 = None
    adapter._p = lambda level, message: print(f"  progress[{level}]: {message}")
    return adapter


if __name__ == "__main__":
    print("=== the gates ===")
    adapter = make_adapter()
    print("  os.name:", os.name)
    print("  GBOX_DOLPHIN_VPAD:", os.environ.get("GBOX_DOLPHIN_VPAD", "<unset>"))
    print("  _want_vpad():", adapter._want_vpad())
    if not adapter._want_vpad():
        raise SystemExit("the vpad gate is closed - a relaunch would not help")

    print("\n=== _setup_vpad ===")
    base = getattr(DolphinWinAdapter, "PAD_INI_WIN", "")
    print(f"  base INI: {len(base)} chars, contains 'Device = XInput/0/Gamepad': "
          f"{'Device = XInput/0/Gamepad' in base}")
    result = adapter._setup_vpad(base)
    if result is None:
        raise SystemExit("_setup_vpad returned None - the launch would fall back to the keyboard")

    print(f"  returned INI: {len(result)} chars")
    lines = [line for line in result.splitlines() if line.startswith(("Device =", "Options/"))]
    for line in lines[:4]:
        print("   ", line)

    device = next((line.split("=", 1)[1].strip() for line in result.splitlines()
                   if line.startswith("Device =")), "")
    print(f"\n  GCPad1 device: {device}")
    print(f"  is the virtual pad's slot ({adapter.vpad.slot}): "
          f"{device == f'XInput/{adapter.vpad.slot}/Gamepad'}")
    print(f"  Always Connected present: {'Options/Always Connected = True' in result}")

    print("\n=== _vpad_works (the decision send_input makes) ===")
    works = adapter._vpad_works()
    print("  _vpad_works():", works)
    print("  report:", getattr(adapter, "vpad_report", None))

    close = getattr(adapter.vpad, "close", None)
    if callable(close):
        close()
    print("\nVERDICT:", "the next launch will use focus-free pad input"
          if works and device == f"XInput/{adapter.vpad.slot}/Gamepad"
          else "the setup does NOT produce a working pad - the relaunch would not fix input")
