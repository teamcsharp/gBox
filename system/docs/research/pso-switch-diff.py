"""Diff the switch/fence entity snapshot taken before the operator flipped the switches against the current state.

That comparison is the direct evidence of what a switch flip does: which fields changed on the switch itself, on its laser fence, and on
the doors of that room.
"""
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S

SNAPSHOT = Path(r"D:\gBox\pso-ds\switch_snapshot.json")
TABLE, POS = 0x8050D460, 0x38


def current_fields(pointer):
    blob = S.read_memory(pointer, 0x340)
    if len(blob) < 0x340:
        return None, None
    x, y, z = struct.unpack(">fff", blob[POS:POS + 12])
    fields = {}
    for offset in range(0, 0x340 - 3, 4):
        (word,) = struct.unpack(">i", blob[offset:offset + 4])
        fields[hex(offset)] = word
    return (x, y, z), fields


def main():
    if not SNAPSHOT.exists():
        print("no snapshot")
        return 2
    before = {row["index"]: row for row in json.loads(SNAPSHOT.read_text(encoding="utf-8"))}
    raw = S.read_memory(TABLE, 256 * 4)
    print(f"snapshot entries: {len(before)}")
    for index, row in sorted(before.items()):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            print(f"  [{index}] {row['class']} at ({row['x']:.0f},{row['z']:.0f}): no longer in the table")
            continue
        position, fields = current_fields(pointer)
        if not fields:
            continue
        name_pointer = int.from_bytes(S.read_memory(pointer, 4), "big")
        name = S.read_memory(name_pointer, 32).split(b"\x00")[0].decode("ascii", "replace") if name_pointer else "?"
        old = row["fields"]
        changed = {key: (old.get(key), fields[key]) for key in fields if key in old and old[key] != fields[key]}
        if changed:
            print(f"  [{index}] {name} at ({row['x']:.0f},{row['z']:.0f}) CHANGED:")
            for key, (was, now) in list(changed.items())[:12]:
                print(f"      {key}: {was} -> {now}")
        else:
            print(f"  [{index}] {name} at ({row['x']:.0f},{row['z']:.0f}): unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
