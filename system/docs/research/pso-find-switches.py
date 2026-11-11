"""Find the interactable switches in the current room.

Switches are entities whose class name says so (PSO: TOSwitchAttackSub and friends). For each one this reports the position, distance to
the player, and the small integer fields in its struct - the state field that changes when it is flipped is one of them, and the door it
opens is usually the nearest door.
"""
import struct
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S

TABLE, MAX_ENTRIES = 0x8050D460, 256
POS = 0x38
NAME_PATTERNS = ("Switch", "switch", "Button", "Pad")


def class_name(pointer):
    name_pointer = int.from_bytes(S.read_memory(pointer, 4), "big")
    if not (0x80000000 <= name_pointer < 0x81800000):
        return ""
    return S.read_memory(name_pointer, 32).split(b"\x00")[0].decode("ascii", "replace")


def player():
    pointer = int.from_bytes(S.read_memory(0x8050EA10, 4), "big")
    blob = S.read_memory(pointer + POS, 12)
    return struct.unpack(">fff", blob) if len(blob) == 12 else None


def main():
    me = player()
    print("player:", tuple(round(v, 1) for v in me) if me else None)
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    found = []
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        name = class_name(pointer)
        if not name or not any(pattern in name for pattern in NAME_PATTERNS):
            continue
        blob = S.read_memory(pointer, 0x340)
        if len(blob) < 0x340:
            continue
        x, y, z = struct.unpack(">fff", blob[POS:POS + 12])
        distance = ((x - me[0]) ** 2 + (z - me[2]) ** 2) ** 0.5 if me else 0.0
        small = {}
        for offset in range(0, 0x340 - 3, 4):
            (word,) = struct.unpack(">i", blob[offset:offset + 4])
            if -1 <= word <= 16:
                small[hex(offset)] = word
        found.append({"index": index, "class": name, "x": x, "y": y, "z": z, "distance": distance,
                      "small_fields": small})
    print(f"switch-like entities: {len(found)}")
    for item in sorted(found, key=lambda e: e["distance"]):
        print(f"  [{item['index']:3d}] {item['class']:<24} at ({item['x']:7.1f},{item['y']:6.1f},{item['z']:7.1f}) "
              f"dist={item['distance']:6.1f}")
        print(f"        small fields: {json_small(item['small_fields'])}")
    return 0


def json_small(fields):
    return " ".join(f"{k}={v}" for k, v in list(fields.items())[:24])


if __name__ == "__main__":
    raise SystemExit(main())
