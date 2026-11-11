"""Find the player's facing angle: a gun fires forward, so the bot must be able to aim.

The rifle is equipped and verified, the wolf is 16.9 units away, and four bursts left its HP at 42 - because a gun fires in the direction the
character faces and nothing makes the character face the target. This scans the player struct for a float that behaves like a yaw (a small angular
value that changes when the character turns) and prints candidates, so aim can be controlled instead of hoped for.
"""
import math
import struct
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import pso_input                                                   # noqa: E402
import session as S                                                # noqa: E402

PLAYER = 0x8050EA10


def blob():
    pointer = int.from_bytes(S.read_memory(PLAYER, 4), "big")
    return S.read_memory(pointer, 0x340)


first = blob()
print("sampling the actor, turning with left, to find a float that moves like an angle")
pso_input.hold("left", 0.6)
time.sleep(0.3)
second = blob()
pso_input.hold("right", 0.6)
time.sleep(0.3)
third = blob()

candidates = []
for offset in range(0x30, 0x340 - 3, 4):
    values = []
    for sample in (first, second, third):
        (value,) = struct.unpack(">f", sample[offset:offset + 4])
        values.append(value)
    if not all(math.isfinite(v) and -10.0 <= v <= 10.0 for v in values):
        continue
    changed = abs(values[1] - values[0]) > 0.01
    restored = abs(values[2] - values[0]) < abs(values[1] - values[0])
    if changed and restored:
        candidates.append((offset, [round(v, 3) for v in values]))
print(f"angle candidates (changed on left, returned on right): {len(candidates)}")
for offset, values in candidates[:14]:
    print(f"  +0x{offset:03X}: {values}")

# cross-check: the yaw should match the bearing to a known point when facing it
pointer = int.from_bytes(S.read_memory(PLAYER, 4), "big")
pos = struct.unpack(">fff", S.read_memory(pointer + 0x38, 12))
print(f"\nplayer position: {tuple(round(v, 1) for v in pos)}")
