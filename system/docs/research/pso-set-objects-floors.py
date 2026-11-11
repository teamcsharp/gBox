"""Decode the set objects for both forest floors into one file keyed by floor.

`set_warp.py` decoded the set files but keyed them by file name and only covered Forest 1's pair. The viewer needs
"which objects are on floor N", so this decodes `map_forest01d/02d` (the placement sets) with the verified format - class id as a big-endian
u16, class name = registry index (id >> 8), position as little-endian floats at 0x10/0x14/0x18 - and writes
`routes/set-objects-floors.json`.

Objects are what a room contains: containers, capsules, enemies' spawn markers, doors, warps.
"""
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import pso_class_registry as REG                          # noqa: E402

REL = Path(r"D:\gBox\pso-ds\rel")
OUT = Path(r"D:\gBox\pso-ds\routes\set-objects-floors.json")
SETS = {1: "map_forest01d.dat", 2: "map_forest02d.dat"}
RECORD = 68
POS = (0x10, 0x14, 0x18)


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
        try:
            x, y, z = (struct.unpack("<f", record[offset:offset + 4])[0] for offset in POS)
        except Exception:                                        # noqa: BLE001
            continue
        if not all(-100000 < value < 100000 for value in (x, y, z)):
            continue
        rows.append({"record": index, "class_id": class_id,
                     "class": table.get(class_id >> 8) or f"class {class_id}",
                     "x": round(x, 1), "y": round(y, 1), "z": round(z, 1)})
    return rows


def main():
    table = names()
    out = {}
    for floor, name in SETS.items():
        path = REL / name
        if not path.exists():
            print(f"floor {floor}: missing {name}")
            continue
        rows = decode(path, table)
        out[str(floor)] = {"set": name, "objects": rows}
        print(f"floor {floor} ({name}): {len(rows)} objects")
        from collections import Counter
        for class_name, count in Counter(row["class"] for row in rows).most_common(6):
            sample = next(row for row in rows if row["class"] == class_name)
            print(f"   {class_name:<26} x{count:<3} first at ({sample['x']:.0f},{sample['z']:.0f})")
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
