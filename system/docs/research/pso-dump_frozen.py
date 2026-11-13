"""Dump the frozen player struct and interpret it: what is the game's own state when input is refused?

The character has been frozen for seventy consecutive `up` presses - 0.00 units each, HP 68/68, pad clean. That is a stable, reproducible state rather than a transient, so the struct can be
read once and examined instead of diffed.

What is known about the layout, from how the rest of the system uses it:

* `+0x38` is the position: three big-endian floats, which is exactly what `go_to_field` writes to teleport;
* the profile reads HP, TP, `angle` and `heading_deg` from this same struct.

So the dump prints every 4-byte word three ways - as a signed integer, as an unsigned hex, and as a float - and calls out any float that is a plausible coordinate or angle. A frozen state
should show itself as a flag, a counter stuck at a value, or an animation/timer field that never advances.
"""
import struct
import time

from pso_pad import Pad, call

POINTER_OFFSET = 0x38


def state(pad):
    return call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}


def dump(pad, pointer, length=256):
    raw = call("/api/sessions/%s/rpc" % pad.sid,
               {"op": "read_memory", "args": {"address": int(pointer, 16), "length": length}}, "POST")
    return bytes.fromhex(raw) if isinstance(raw, str) else None


if __name__ == "__main__":
    pad = Pad()
    now = state(pad)
    player = now.get("player") or {}
    pointer = player.get("ptr")
    print("session:", pad.sid, "| ptr:", pointer)
    print("profile says: x", player.get("x"), "y", player.get("y"), "z", player.get("z"),
          "| angle", player.get("angle"), "| heading", player.get("heading_deg"), "| hp", player.get("hp"))
    if not pointer:
        raise SystemExit("no pointer")

    first = dump(pad, pointer)
    time.sleep(2.0)
    second = dump(pad, pointer)
    if not first or not second:
        raise SystemExit("could not read the struct")

    print("\nwords that CHANGED over 2 s while frozen (an animation would keep ticking):")
    changed = 0
    for offset in range(0, len(first) - 3, 4):
        a = first[offset:offset + 4]
        b = second[offset:offset + 4]
        if a != b:
            changed += 1
            print(f"  +0x{offset:02X}: {a.hex()} -> {b.hex()}")
    print(f"  ({changed} of {len(first)//4} words changed)")

    print("\nfull struct, 4-byte words (offset, int, hex, float):")
    for offset in range(0, len(first) - 3, 4):
        chunk = first[offset:offset + 4]
        as_int = int.from_bytes(chunk, "big", signed=True)
        as_uint = int.from_bytes(chunk, "big")
        as_float = struct.unpack(">f", chunk)[0]
        marker = ""
        if offset == POINTER_OFFSET:
            marker = "   <- position x"
        elif offset == POINTER_OFFSET + 4:
            marker = "   <- position y"
        elif offset == POINTER_OFFSET + 8:
            marker = "   <- position z"
        if -100000.0 < as_float < 100000.0 and abs(as_float) > 0.0001 and marker == "":
            if 0.0 < abs(as_float) < 1000.0:
                marker = "   <- plausible coord/angle"
        print(f"  +0x{offset:02X}  {as_int:>12}  0x{as_uint:08X}  {as_float:>14.4f}{marker}")
