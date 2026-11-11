"""Prototype the editor's write side: move or place an object in a level set file, safely, and prove the result.

A set file is 68-byte records: a big-endian u16 class id at +0x00 (class name = id >> 8 through the registry), and the position as three
little-endian floats at +0x10 / +0x14 / +0x18. Everything else in the record is left untouched, so an edit changes 12 bytes and nothing else.

This works on a COPY. It prints the record it changed, writes the copy, re-decodes both files, and asserts that exactly one object differs and
that the records are otherwise byte-identical - the evidence that a position edit is clean before any of it is offered to the game.

Usage:
  python set_edit.py list   [set]                 show records
  python set_edit.py move   [set] [record] [x] [y] [z]   write a copy with that record moved
  python set_edit.py verify [original] [edited]   compare two files record by record
"""
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import pso_class_registry as REG                          # noqa: E402

REL = Path(r"D:\gBox\pso-ds\rel")
OUT = Path(r"D:\gBox\pso-ds\rel\edited")
RECORD = 68
POS = (0x10, 0x14, 0x18)


def names():
    table = getattr(REG, "CLASS_NAMES", {}) or {}
    if isinstance(table, dict):
        return {int(k): v for k, v in table.items() if str(k).isdigit() and v}
    return {index: name for index, name in enumerate(table) if name}


def decode(data, table):
    out = []
    for index in range(len(data) // RECORD):
        record = data[index * RECORD:(index + 1) * RECORD]
        class_id = int.from_bytes(record[0:2], "big")
        try:
            x, y, z = (struct.unpack("<f", record[offset:offset + 4])[0] for offset in POS)
        except Exception:                                        # noqa: BLE001
            continue
        out.append({"record": index, "class": table.get(class_id >> 8) or f"class {class_id}",
                    "class_id": class_id, "x": round(x, 2), "y": round(y, 2), "z": round(z, 2)})
    return out


def main(argv):
    table = names()
    command = argv[1] if len(argv) > 1 else "list"
    set_name = argv[2] if len(argv) > 2 else "map_forest01d.dat"
    source = REL / set_name
    if not source.exists():
        print("missing", source)
        return 2
    data = source.read_bytes()
    if command == "list":
        objects = decode(data, table)
        print(f"{set_name}: {len(objects)} records")
        for obj in objects[:20]:
            print(f"  {obj['record']:3d}  {obj['class']:<26} ({obj['x']:8.1f},{obj['y']:7.1f},{obj['z']:8.1f})")
        return 0
    if command == "move":
        record = int(argv[3])
        x, y, z = (float(argv[4]), float(argv[5]), float(argv[6]))
        before = decode(data, table)
        target = next((o for o in before if o["record"] == record), None)
        if target is None:
            print(f"no record {record}")
            return 2
        edited = bytearray(data)
        offset = record * RECORD
        edited[offset + POS[0]:offset + POS[0] + 4] = struct.pack("<f", x)
        edited[offset + POS[1]:offset + POS[1] + 4] = struct.pack("<f", y)
        edited[offset + POS[2]:offset + POS[2] + 4] = struct.pack("<f", z)
        changed = sum(1 for a, b in zip(data, edited) if a != b)
        OUT.mkdir(parents=True, exist_ok=True)
        destination = OUT / set_name
        destination.write_bytes(bytes(edited))
        after = decode(bytes(edited), table)
        moved = [(b["record"], a["class"], (a["x"], a["z"]), (b["x"], b["z"]))
                 for a, b in zip(before, after) if abs(a["x"] - b["x"]) > 0.01 or abs(a["z"] - b["z"]) > 0.01]
        print(f"moved record {record} ({target['class']}) from "
              f"({target['x']:.1f},{target['y']:.1f},{target['z']:.1f}) to ({x:.1f},{y:.1f},{z:.1f})")
        print(f"bytes changed: {changed} (expected 12) | objects changed: {len(moved)} (expected 1)")
        print(f"wrote {destination}")
        return 0 if changed == 12 and len(moved) == 1 else 3
    if command == "verify":
        original = (REL / argv[2]).read_bytes()
        other = (REL / argv[3]).read_bytes() if not Path(argv[3]).is_absolute() else Path(argv[3]).read_bytes()
        a, b = decode(original, table), decode(other, table)
        differing = [(x["record"], x["class"], (x["x"], x["z"]), (y["x"], y["z"]))
                     for x, y in zip(a, b) if abs(x["x"] - y["x"]) > 0.01 or abs(x["z"] - y["z"]) > 0.01]
        same_records = len(a) == len(b)
        print(f"records {len(a)} vs {len(b)} (same count: {same_records}) | differing objects: {len(differing)}")
        for row in differing[:6]:
            print(f"  record {row[0]} {row[1]}: {row[2]} -> {row[3]}")
        return 0
    print("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
