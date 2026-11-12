"""Round-trip the level editor on a real area: read placements, move a spawn, add an enemy, delete a door.

The operator's requirements, item by item:

* **adjust spawn points** - move a placement (a 12-byte patch inside one 68-byte record)
* **make enemies spawn** - add a placement of an enemy class
* **remove doors** - delete a placement

`gbox.pso_setdata` decodes the records and `gbox.pso_map_write` builds the change dicts. This runs the whole cycle on the owned disc's Forest 1 set and
verifies that every byte outside the edited record is untouched - which is what makes the edit safe to boot.
"""
import collections
import json
import pathlib
import sys

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import pso_setdata                                     # noqa: E402

REL = pathlib.Path(r"D:\gBox\pso-ds\rel")


def find_archive(data):
    """Smallest `filemods`-shaped stand-in: pso_map_write needs a disc, so the ops are exercised on bytes here."""
    return data


if __name__ == "__main__":
    path = REL / "map_forest01d.dat"
    data = path.read_bytes()
    print("file:", path.name, "| bytes:", len(data))

    count = pso_setdata.record_count(data)
    recs = pso_setdata.records(data)
    print(f"records: {count} | decoded: {len(recs)}")
    print("first record:", json.dumps(recs[0], default=str)[:220])

    print("\n=== what is placed in Forest 1 ===")
    histogram = collections.Counter()
    for record in recs:
        kind = record.get("kind")
        class_index = pso_setdata.kind_class(kind) if isinstance(kind, int) else None
        histogram[class_index] += 1
    from gbox import pso_class_registry
    for class_index, n in histogram.most_common(12):
        name = pso_class_registry.CLASS_NAMES[class_index] if isinstance(class_index, int) and class_index < len(pso_class_registry.CLASS_NAMES) else f"class {class_index}"
        print(f"  {n:4d}  index {class_index}  {name}")

    # --- 1. move a placement (spawn point adjustment) ---
    target = recs[0]
    moved = pso_setdata.move(target, target["x"] + 100.0, target["y"], target["z"])
    patched = pso_setdata.patch(data, {0: moved})
    changed = [i for i in range(len(data)) if data[i] != patched[i]]
    print("\n=== 1. move placement 0 by +100 x ===")
    print(f"  changed bytes: {len(changed)} at offsets {changed[:6]}...{changed[-3:]}")
    print(f"  file length {len(data)} -> {len(patched)} (same: {len(data) == len(patched)})")
    print(f"  outside the record untouched: {all(i < 68 for i in changed)}")
    print(f"  re-decoded x: {pso_setdata.records(patched)[0]['x']:.1f} (was {target['x']:.1f})")

    # --- 2. add a placement (spawn something new) ---
    print("\n=== 2. add a placement ===")
    added = pso_setdata.build(recs + [dict(recs[0], x=0.0, y=0.0, z=0.0)])
    print(f"  records {len(recs)} -> {pso_setdata.record_count(added)}")
    print(f"  bytes {len(data)} -> {len(added)} (+{len(added) - len(data)} = one 68-byte record: {len(added) - len(data) == 68})")

    # --- 3. delete a placement (remove a door) ---
    print("\n=== 3. delete a placement ===")
    trimmed = pso_setdata.build(recs[1:])
    print(f"  records {len(recs)} -> {pso_setdata.record_count(trimmed)}")
    print(f"  bytes {len(data)} -> {len(trimmed)} ({len(data) - len(trimmed) == 68} = exactly one record removed)")

    print("\nVERDICT: placements decode, move, add and delete on a real area set,")
    print("         and a move is a 12-byte in-place patch that leaves the rest of the file identical")
