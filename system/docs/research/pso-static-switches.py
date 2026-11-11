"""List the switches the LEVEL DATA places in a forest area, with their positions.

The live entity table only holds what is streamed in; the set file (map_forest01d.dat) lists every placed object, including
TOSwitchAttackSub and the laser-fence switches, at all positions in the area. That is the authoritative "which switches exist in this
room" source, so it complements the entity-table scan.
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import pso_class_registry                                # noqa: E402

REL = Path(r"D:\gBox\pso-ds\rel\map_forest01d.dat")
RECORD = 68
SWITCH_HINTS = ("Switch", "switch", "LazerFenceSw", "Button")


def main():
    data = REL.read_bytes()
    count = len(data) // RECORD
    print(f"{REL.name}: {len(data)} bytes, {count} records of {RECORD}")
    rows = []
    for index in range(count):
        record = data[index * RECORD:(index + 1) * RECORD]
        class_id = int.from_bytes(record[0:2], "big")
        name = pso_class_registry.name(class_id) if hasattr(pso_class_registry, "name") else str(class_id)
        if not name:
            name = f"class {class_id}"
        if not any(hint.lower() in str(name).lower() for hint in SWITCH_HINTS):
            continue
        # positions live at the end of the record as three big-endian floats in this format
        floats = [struct.unpack(">f", record[offset:offset + 4])[0] for offset in range(RECORD - 12, RECORD, 4)]
        rows.append({"index": index, "class": name, "x": floats[0], "y": floats[1], "z": floats[2]})
    print(f"switch-like records: {len(rows)}")
    for row in rows:
        print(f"  record {row['index']:3d} {row['class']:<24} at ({row['x']:8.1f},{row['y']:7.1f},{row['z']:8.1f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
