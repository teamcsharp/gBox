"""Check that minimap marker bearings really correspond to world bearings of the doors.

The exit navigation assumes the minimap is north-up and player-centred, so a marker's crop bearing equals the world bearing of the doorway.
This compares the live marker bearings with the world bearings of every TObjDoor/TObjDoorKey in the entity table from the same position.
Pure reads - no input.
"""
import math
import struct
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import map_exit as ME                                              # noqa: E402
import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, POS = 0x8050D460, 256, 0x38


def player():
    pointer = int.from_bytes(S.read_memory(0x8050EA10, 4), "big")
    blob = S.read_memory(pointer + POS, 12)
    return struct.unpack(">fff", blob) if len(blob) == 12 else None


def doors():
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    out = []
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        name_pointer = int.from_bytes(S.read_memory(pointer, 4), "big")
        if not (0x80000000 <= name_pointer < 0x81800000):
            continue
        name = S.read_memory(name_pointer, 32).split(b"\x00")[0].decode("ascii", "replace")
        if not name.startswith("TObjDoor"):
            continue
        blob = S.read_memory(pointer + POS, 12)
        if len(blob) != 12:
            continue
        x, y, z = struct.unpack(">fff", blob)
        out.append({"index": index, "class": name, "x": x, "z": z})
    return out


def bearing(point, target):
    return math.degrees(math.atan2(target[1] - point[1], target[0] - point[0]))


def main():
    me = player()
    if me is None:
        print("no player")
        return 2
    point = (me[0], me[2])
    markers = ME.exits_from_map()
    doors_found = doors()
    print(f"player ({point[0]:.0f},{point[1]:.0f})")
    print(f"minimap markers ({len(markers)}):")
    for marker in markers:
        print(f"  bearing {marker['bearing']:+7.1f}  {marker['distance_px']:5.1f}px  colour-pixels {marker['px']}")
    print(f"world doors ({len(doors_found)}):")
    for door in doors_found:
        d = math.dist(point, (door["x"], door["z"]))
        print(f"  {door['class']:<14} ({door['x']:8.1f},{door['z']:8.1f}) bearing {bearing(point, (door['x'], door['z'])):+7.1f}  dist {d:6.1f}")
    matches = 0
    for marker in markers:
        best = min(doors_found, key=lambda door: abs(((bearing(point, (door["x"], door["z"])) - marker["bearing"]) + 180) % 360 - 180))
        error = abs(((bearing(point, (best["x"], best["z"])) - marker["bearing"]) + 180) % 360 - 180)
        if error < 12:
            matches += 1
        print(f"  marker {marker['bearing']:+7.1f} -> {best['class']} bearing "
              f"{bearing(point, (best['x'], best['z'])):+7.1f} (error {error:4.1f} deg)")
    print(f"\nmarkers matching a door within 12 degrees: {matches}/{len(markers)}")
    return 0 if matches >= max(1, len(markers) // 2) else 3


if __name__ == "__main__":
    raise SystemExit(main())
