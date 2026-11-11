"""Census of every entity class currently loaded, with counts and nearest positions.

Switch detection needs the real class names this build uses, so this lists them all rather than guessing patterns.
"""
import struct
import sys
from collections import Counter

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S

TABLE, MAX_ENTRIES, POS = 0x8050D460, 256, 0x38


def main():
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    player = int.from_bytes(S.read_memory(0x8050EA10, 4), "big")
    me = struct.unpack(">fff", S.read_memory(player + POS, 12)) if player else (0, 0, 0)
    counts = Counter()
    nearest = {}
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        name_pointer = int.from_bytes(S.read_memory(pointer, 4), "big")
        if not (0x80000000 <= name_pointer < 0x81800000):
            continue
        name = S.read_memory(name_pointer, 32).split(b"\x00")[0].decode("ascii", "replace")
        if not name:
            continue
        blob = S.read_memory(pointer + POS, 12)
        if len(blob) != 12:
            continue
        x, y, z = struct.unpack(">fff", blob)
        distance = ((x - me[0]) ** 2 + (z - me[2]) ** 2) ** 0.5
        counts[name] += 1
        if name not in nearest or distance < nearest[name][0]:
            nearest[name] = (distance, x, y, z)
    print(f"player at ({me[0]:.0f},{me[1]:.0f},{me[2]:.0f}); distinct classes: {len(counts)}")
    for name, count in counts.most_common():
        distance, x, y, z = nearest[name]
        print(f"  {name:<28} x{count:<3} nearest {distance:7.1f} at ({x:7.1f},{y:6.1f},{z:7.1f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
