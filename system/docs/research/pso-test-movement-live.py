"""Is the bot actually moving the character? Sample position and HP over ten seconds.

`play_rooms` is alive, the session has a character at (0, 0, -2015) with 40 HP, and the log goes quiet after `floor 0` - which means either it is playing without
logging, or every action is being swallowed. Position decides it: a bot that is playing changes `pos`; one that is not leaves it identical.
"""
import struct
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

PLAYER = 0x8050EA10
POS = 0x38
HP = 0x32C


def read():
    pointer = int.from_bytes(S.read_memory(PLAYER, 4), "big")
    if not (0x80000000 <= pointer < 0x81800000):
        return None
    blob = S.read_memory(pointer, 0x340)
    return struct.unpack(">fff", blob[POS:POS + 12]), struct.unpack(">H", blob[HP:HP + 2])[0]


if __name__ == "__main__":
    samples = []
    for index in range(10):
        state = read()
        if state is None:
            print(f"{index}: no player")
        else:
            (x, y, z), hp = state
            samples.append((x, z))
            print(f"{index}: pos=({x:.1f}, {z:.1f}) hp={hp}")
        time.sleep(1.0)

    if len(samples) >= 2:
        xs = [s[0] for s in samples]
        zs = [s[1] for s in samples]
        spread = max(max(xs) - min(xs), max(zs) - min(zs))
        print()
        print(f"movement spread: {spread:.2f} units")
        print("VERDICT:", "the bot is moving the character" if spread > 0.5
              else "the character is NOT moving - input is not reaching the game")
