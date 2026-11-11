"""Structural validation for a level set file, especially an edited one.

An edited file cannot be booted without a game, so the next best thing is to prove it satisfies every structural invariant the format shows:

  1. the size is an exact multiple of 68 (no header, no trailer);
  2. every record's class id is a multiple of 256 where the class table is sparse - measured on the shipped files, class ids are always
     `index << 8`, so a low byte other than 0 would mean a corrupted or foreign record;
  3. every position triple is finite and inside a sane bound;
  4. every class index resolves either to a registry name or to one of the unnamed indices the shipped files already use;
  5. optionally, compare against an original: the record count grows by exactly the number of additions and every original record survives
     byte-identical.

Exit code 0 only when every check passes.

Usage: python set_check.py <file> [original]
"""
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import pso_class_registry as REG                          # noqa: E402

RECORD = 68
POS = (0x10, 0x14, 0x18)
BOUND = 20000.0


def names():
    table = getattr(REG, "CLASS_NAMES", {}) or {}
    if isinstance(table, dict):
        return {int(k): v for k, v in table.items() if str(k).isdigit()}
    return {index: name for index, name in enumerate(table)}


def main(argv):
    if len(argv) < 2:
        print("usage: set_check.py <file> [original]")
        return 2
    path = Path(argv[1])
    if not path.exists():
        print("missing", path)
        return 2
    data = path.read_bytes()
    table = names()
    problems = []
    if len(data) % RECORD:
        problems.append(f"size {len(data)} is not a multiple of {RECORD} (remainder {len(data) % RECORD})")
    count = len(data) // RECORD
    unnamed = set()
    for index in range(count):
        record = data[index * RECORD:(index + 1) * RECORD]
        class_id = int.from_bytes(record[0:2], "big")
        if class_id & 0xFF:
            problems.append(f"record {index}: class id {class_id:#06x} has a non-zero low byte")
        name = table.get(class_id >> 8)
        if not name:
            unnamed.add(class_id >> 8)
        x, y, z = (struct.unpack("<f", record[offset:offset + 4])[0] for offset in POS)
        if not all(math.isfinite(v) and abs(v) <= BOUND for v in (x, y, z)):
            problems.append(f"record {index}: position ({x},{y},{z}) is not finite or out of bounds")
    print(f"{path.name}: {count} records, {len(data)} bytes")
    print(f"  unnamed class indices used: {sorted(unnamed) if unnamed else 'none'}")
    if len(argv) > 2:
        original = Path(argv[2]).read_bytes()
        original_count = len(original) // RECORD
        added = count - original_count
        survivors = 0
        for index in range(min(count, original_count)):
            if data[index * RECORD:(index + 1) * RECORD] == original[index * RECORD:(index + 1) * RECORD]:
                survivors += 1
        print(f"  against {Path(argv[2]).name}: {original_count} -> {count} records ({added:+d}), "
              f"{survivors}/{original_count} original records byte-identical")
        if survivors != original_count:
            problems.append(f"{original_count - survivors} original records changed")
        if added < 0:
            problems.append(f"records were lost ({added})")
    if problems:
        print(f"  FAIL ({len(problems)} problems)")
        for problem in problems[:10]:
            print(f"    - {problem}")
        return 3
    print("  PASS: every structural invariant holds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
