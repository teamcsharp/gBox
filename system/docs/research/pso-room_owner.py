"""Which cave layouts contain room 50? The record's third lane is the room id.

The player is in room 50, and the placement records carry a small value whose distinct set is [1, 10, 11, 20, 31, 32, 33, 34, 50, 51, 52, 53] - which includes 50.
`pso_setdata` names that lane `amount`, but a set file for one room of an area would not need 199 placements with 23 distinct "amounts"; it needs one room id per
record.

So: read every cave layout's set file, group its placements by that lane, and see which layout owns room 50. That decides the layout exactly - no offset voting,
no guessing.
"""
import collections
import json
import sys

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import gcdisc, pso_setdata                             # noqa: E402

DISC = r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz"
LAYOUTS = [f"map_cave01_0{i}" for i in range(6)]
ROOM = 50


if __name__ == "__main__":
    disc = gcdisc.GCDisc(DISC)
    names = set(disc.files)

    owners = collections.defaultdict(list)
    print(f"looking for room {ROOM} across the cave layouts\n")
    for layout in LAYOUTS:
        candidates = sorted(n for n in names if n.endswith(f"{layout}ad.dat") or n.endswith(f"{layout}d.dat"))
        if not candidates:
            print(f"  {layout}: no set file")
            continue
        for name in candidates:
            recs = pso_setdata.records(disc.read(name))
            rooms = collections.Counter(r.get("amount") for r in recs)
            rooms = {int(k): v for k, v in rooms.items() if isinstance(k, int)}
            has = ROOM in rooms
            print(f"  {name:24s} {len(recs):4d} placements, rooms {sorted(rooms)}"
                  + (f"   <-- contains {ROOM} ({rooms[ROOM]} placements)" if has else ""))
            if has:
                owners[name].append((layout, rooms[ROOM], len(recs)))

    print(f"\n=== files containing room {ROOM} ===")
    if not owners:
        print("  none - the third lane is not a room id, or room numbering differs for this area")
    for name, rows in owners.items():
        for layout, count, total in rows:
            print(f"  {name}  layout={layout}  {count} of {total} placements are room {ROOM}")

    if len(owners) == 1:
        name = next(iter(owners))
        layout = owners[name][0][0]
        print(f"\nVERDICT: room {ROOM} belongs to {layout} alone - that is the loaded layout")
        recs = pso_setdata.records(disc.read(name))
        mine = [r for r in recs if r.get("amount") == ROOM]
        xs = [r["x"] for r in mine]
        zs = [r["z"] for r in mine]
        print(f"  its {len(mine)} placements span x {min(xs):.0f}..{max(xs):.0f}, z {min(zs):.0f}..{max(zs):.0f}")
        print("  matching those against the live entities gives the room offset directly")
