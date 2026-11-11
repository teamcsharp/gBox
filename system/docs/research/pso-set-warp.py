"""Decode the level set file with the class mapping and find the area warp (the teleporter to the next area).

Measured mapping: set class id = registry index * 256. Verified: id 4352 = index 17 = TOSwitchAttackSub (the two switches in this room).
The forest teleporter is TObjAreaWarpForest = index 205 = set id 52480.

Position fields: three LITTLE-endian floats at 0x11 / 0x15 / 0x19 (a one-byte tag precedes each float). Verified against the two
independently known switch positions (-520, 700, -500) and (-400, 250, -100).
"""
import json
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import pso_class_registry as REG                          # noqa: E402

SETS = {
    "map_forest01d.dat": Path(r"D:\gBox\pso-ds\rel\map_forest01d.dat"),
    "map_forest01ad.dat": Path(r"D:\gBox\pso-ds\rel\map_forest01ad.dat"),
}
RECORD = 68
POS = (0x10, 0x14, 0x18)
INTERESTING = ("warp", "switch", "telep", "portal", "boss")
OUT = Path(r"D:\gBox\pso-ds\routes\set-objects.json")


def names():
    table = getattr(REG, "CLASS_NAMES", {}) or {}
    if isinstance(table, dict):
        return {int(k): v for k, v in table.items() if str(k).isdigit() and v}
    return {index: name for index, name in enumerate(table) if name}


def decode(path, table):
    data = path.read_bytes()
    rows = []
    for index in range(len(data) // RECORD):
        record = data[index * RECORD:(index + 1) * RECORD]
        class_id = int.from_bytes(record[0:2], "big")
        registry_index = class_id >> 8
        class_name = table.get(registry_index) or f"class {class_id}"
        try:
            x, y, z = (struct.unpack("<f", record[offset:offset + 4])[0] for offset in POS)
        except Exception:                                        # noqa: BLE001
            continue
        if not all(-100000 < value < 100000 for value in (x, y, z)):
            continue
        rows.append({"record": index, "class_id": class_id, "index": registry_index, "class": class_name,
                     "x": round(x, 1), "y": round(y, 1), "z": round(z, 1)})
    return rows


def main():
    table = names()
    print(f"registry names: {len(table)}")
    everything = {}
    for label, path in SETS.items():
        if not path.exists():
            print(f"{label}: missing")
            continue
        rows = decode(path, table)
        everything[label] = rows
        print(f"\n{label}: {len(rows)} decoded objects of {path.stat().st_size // RECORD} records")
        for class_name, count in Counter(row["class"] for row in rows).most_common(10):
            print(f"  {class_name:<26} x{count}")
        for row in rows:
            if any(hint in row["class"].lower() for hint in INTERESTING):
                print(f"    {row['class']:<26} ({row['x']:9.1f},{row['y']:7.1f},{row['z']:9.1f})  record {row['record']}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(everything, indent=1), encoding="utf-8")
    print("\nwrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
