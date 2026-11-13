"""Find the field that says "input refused", by diffing the player struct in both states.

The freeze has been inferred from position alone for too long: the pad reads `(0,0)`, the game runs at 30 fps, HP is 68/68, `b` is pressed first, and yet all four directions give 0.0 units.
That rules out the pad, the menu and death - it does not name the cause.

So this presses deliberately and dumps the **player struct** on each outcome. The struct starts at the pointer the profile reports (`TObjPlayer`, e.g. `80DA62A0`); `+0x38` is the
position as three big-endian floats, which is how `go_to_field` teleports, so a 256-byte window covers position, HP/TP, angle and whatever state word gates movement.

Each iteration: read position, hold `up` for 0.8 s, release all four, read position again, and dump the struct.

* moved > 2 units  -> a MOVING sample
* moved < 0.05     -> a FROZEN sample

When both exist, every differing 4-byte word is printed with both values. One of those offsets is the state the controller needs to gate on.
"""
import time

from pso_pad import Pad, call

DIRECTIONS = ("up", "down", "left", "right")


def state(pad):
    return call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}


def dump(pad, pointer, length=256):
    raw = call("/api/sessions/%s/rpc" % pad.sid,
               {"op": "read_memory", "args": {"address": int(pointer, 16), "length": length}}, "POST")
    try:
        return bytes.fromhex(raw) if isinstance(raw, str) else None
    except ValueError:
        return None


def words(blob):
    return [int.from_bytes(blob[i:i + 4], "big") for i in range(0, len(blob) - 3, 4)]


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)
    player = (state(pad).get("player") or {})
    pointer = player.get("ptr")
    print("player ptr:", pointer, "| hp", player.get("hp"))
    if not pointer:
        raise SystemExit("no player pointer")

    moving_dump = frozen_dump = None
    for step in range(70):
        if moving_dump is not None and frozen_dump is not None:
            break
        before = state(pad).get("player") or {}
        start = (float(before.get("x") or 0), float(before.get("z") or 0))

        pad.send([{"key": "up", "down": True}])
        time.sleep(0.8)
        pad.send([{"key": k, "down": False} for k in DIRECTIONS])
        time.sleep(0.35)

        after = state(pad).get("player") or {}
        end = (float(after.get("x") or 0), float(after.get("z") or 0))
        moved = abs(end[0] - start[0]) + abs(end[1] - start[1])

        blob = dump(pad, pointer)
        if not blob:
            continue
        if moved > 2.0 and moving_dump is None:
            moving_dump = blob
            print(f"  step {step}: MOVING {moved:6.1f} units - struct captured (hp {after.get('hp')})")
        elif moved < 0.05 and frozen_dump is None:
            frozen_dump = blob
            print(f"  step {step}: FROZEN {moved:6.2f} units - struct captured (hp {after.get('hp')})")

    if not moving_dump or not frozen_dump:
        print("\ncould not capture both (moving:", bool(moving_dump), "frozen:", bool(frozen_dump), ")")
        print("if it never froze, that is good news - rerun when it does")
        raise SystemExit(0)

    print("\ndiffering 4-byte words (FROZEN vs MOVING):")
    differs = []
    for index, (frozen, moving) in enumerate(zip(words(frozen_dump), words(moving_dump))):
        if frozen != moving:
            offset = index * 4
            differs.append(offset)
            print(f"  +0x{offset:02X}: frozen 0x{frozen:08X} ({frozen:>11})   moving 0x{moving:08X} ({moving:>11})")
    print(f"\n{len(differs)} differing words out of {len(words(frozen_dump))}")
