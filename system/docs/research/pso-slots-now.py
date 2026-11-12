"""Which XInput slots are actually live, and what is on them?

The config binds `XInput/0/Gamepad`, and the log says `padstate: mirroring the operator's pad on XInput slot 0`. If the virtual pad also took slot 0, the game is reading
either a mirror of an absent controller or a pad that fights with it - and that would explain why twelve presses moved nothing while `_vpad_works()` reports true in
isolation.

This reads all four slots and reports buttons and sticks, so the conflict is visible rather than inferred.
"""
import sys

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import pad_route, xinput                            # noqa: E402


if __name__ == "__main__":
    handle = xinput.load()
    print("XInputGetState available:", bool(handle))
    for slot in range(4):
        state = xinput.read(handle, slot)
        if state is None:
            print(f"  slot {slot}: absent")
            continue
        reading = pad_route.slot_reading(state)
        buttons = reading.get("buttons") or 0
        print(f"  slot {slot}: connected  buttons=0x{buttons:04X}  "
              f"lx={reading.get('lx')} ly={reading.get('ly')} "
              f"lt={reading.get('lt')} rt={reading.get('rt')}")
