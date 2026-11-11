"""Dump the switch/fence entities and their small state fields, so a flip can be detected.

Candidates on this build: TLazerFenceSw (the switch), TObjLazerFenceNorm (the fence it opens), TObjDoorKey (a key door) and TObject (a
generic interactable). For each, print the position and every small integer field in the struct - one of them is the flipped/pressed flag,
and a before/after comparison around an A press identifies which.
"""
import json
import struct
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S

TABLE, MAX_ENTRIES, POS = 0x8050D460, 256, 0x38
WANTED = ("TLazerFenceSw", "TObjLazerFenceNorm", "TObjDoorKey", "TObject", "TOSwitch")
SNAPSHOT = r"D:\gBox\pso-ds\switch_snapshot.json"


def entities(wanted=WANTED):
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    player = int.from_bytes(S.read_memory(0x8050EA10, 4), "big")
    me = struct.unpack(">fff", S.read_memory(player + POS, 12)) if player else (0, 0, 0)
    out = []
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        name_pointer = int.from_bytes(S.read_memory(pointer, 4), "big")
        if not (0x80000000 <= name_pointer < 0x81800000):
            continue
        name = S.read_memory(name_pointer, 32).split(b"\x00")[0].decode("ascii", "replace")
        if not any(name.startswith(prefix) for prefix in wanted):
            continue
        blob = S.read_memory(pointer, 0x340)
        if len(blob) < 0x340:
            continue
        x, y, z = struct.unpack(">fff", blob[POS:POS + 12])
        fields = {}
        for offset in range(0, 0x340 - 3, 4):
            (word,) = struct.unpack(">i", blob[offset:offset + 4])
            if -1 <= word <= 32:
                fields[hex(offset)] = word
        out.append({"index": index, "class": name, "x": round(x, 1), "y": round(y, 1), "z": round(z, 1),
                    "distance": round(((x - me[0]) ** 2 + (z - me[2]) ** 2) ** 0.5, 1), "fields": fields})
    return sorted(out, key=lambda e: e["distance"])


def main():
    rows = entities()
    print(f"switch/fence/interactable entities: {len(rows)}")
    for row in rows:
        keys = " ".join(f"{k}={v}" for k, v in list(row["fields"].items())[:18])
        print(f"  [{row['index']:3d}] {row['class']:<22} ({row['x']:7.1f},{row['y']:6.1f},{row['z']:7.1f}) "
              f"dist={row['distance']:6.1f}")
        print(f"        {keys}")
    with open(SNAPSHOT, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=1)
    print("snapshot ->", SNAPSHOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
