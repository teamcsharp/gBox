"""What is placed in Cave 1, by class? The room graph is sparse there and this says why.

`cave01` has 39 rooms but only **8** connections, while `ancient02` has 127 over 111 rooms. The hypothesis is that caves place their doors as entities whose records do
not carry a `link`, rather than as link-carrying markers.

This lists every placement class in `map_cave01_00` with its count, then isolates the door/warp-like classes and prints their records - position, link, and any other
field that could name the room on the other side.
"""
import collections
import sys

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import gcdisc, pso_class_registry, pso_setdata         # noqa: E402

DISC = r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz"
LAYOUT = "map_cave01_00"
DOORISH = ("door", "warp", "gate", "teleport", "area")


def class_name(rec):
    kind = rec.get("kind")
    if not isinstance(kind, int):
        return None, None
    index = pso_setdata.kind_class(kind)
    if isinstance(index, int) and 0 <= index < len(pso_class_registry.CLASS_NAMES):
        return index, pso_class_registry.CLASS_NAMES[index]
    return index, None


if __name__ == "__main__":
    disc = gcdisc.GCDisc(DISC)
    recs = pso_setdata.records(disc.read(LAYOUT + "d.dat"))
    print(f"{LAYOUT}: {len(recs)} placements\n")

    histogram = collections.Counter()
    names = {}
    for rec in recs:
        index, name = class_name(rec)
        histogram[index] += 1
        if index not in names:
            names[index] = name

    print("class index -> name, count:")
    for index, count in histogram.most_common():
        label = names.get(index) or "(unresolved in this build)"
        print(f"  index {str(index):>4}  {count:4d}  {label}")

    print("\n=== door-like classes present in this layout ===")
    hits = []
    for rec in recs:
        index, name = class_name(rec)
        if name and any(word in name.lower() for word in DOORISH):
            hits.append((name, rec))
    if not hits:
        print("  none - no door, warp, gate, teleport or area class is placed in the caves")
    for name, rec in hits[:12]:
        print(f"  {name:26s} room {rec.get('amount')} at ({rec['x']:8.1f}, {rec['z']:8.1f}) "
              f"link {rec.get('link')}")

    print("\n=== every class name in the registry containing a door-like word ===")
    available = [name for name in pso_class_registry.CLASS_NAMES
                 if name and any(word in name.lower() for word in DOORISH)]
    for name in available:
        print(f"  {name}")
    if not available:
        print("  none in the registry at all")

    print("\n=== which records carry a non-zero link, by room ===")
    linked = [r for r in recs if isinstance(r.get("link"), int) and r["link"]]
    print(f"  {len(linked)} of {len(recs)} records carry a non-zero link")
    per_room = collections.defaultdict(set)
    for rec in linked:
        per_room[rec["amount"]].add(rec["link"])
    for room in sorted(per_room):
        print(f"    room {room:4d} -> links {sorted(per_room[room])[:10]}")

    print("\n=== the kinds that DO carry cross-room links ===")
    kinds = collections.Counter()
    for rec in linked:
        index, name = class_name(rec)
        kinds[(index, name)] += 1
    for (index, name), count in kinds.most_common():
        print(f"  kind index {index:>4}  {count:3d} records  {name or '(unresolved)'}")
