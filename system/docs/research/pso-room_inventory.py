"""Build a room-level inventory: each room's id, its placements and its bounds, per layout.

The `set_id` lane turns out to be the **room instance id** - all 21 of room 50's placements share `198293` - while `amount` is the room number (50). Two ids per room,
which is why grouping by either gives a coherent count.

That is the structure room-to-room pathing needs: which rooms exist in a layout, how big each is, and what is placed in it. It comes straight from the disc with no
live session, no transform and no guessing, and it complements the collision grids already internalised.

`pso_setdata` names these fields nothing like "room", so this records the finding alongside the inventory.
"""
import collections
import json
import sys
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import gcdisc, pso_setdata                             # noqa: E402

DISC = r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz"
OUT = r"D:\gBox\pso-ds\routes\room-inventory.json"
LAYOUTS = [f"map_cave01_0{i}" for i in range(6)] + [f"map_cave02_0{i}" for i in range(5)] \
          + [f"map_cave03_0{i}" for i in range(6)]


if __name__ == "__main__":
    disc = gcdisc.GCDisc(DISC)
    names = set(disc.files)
    inventory = {}

    for layout in LAYOUTS:
        candidates = sorted(n for n in names if n.endswith(f"{layout}d.dat"))
        if not candidates:
            continue
        recs = pso_setdata.records(disc.read(candidates[0]))
        by_amount = collections.defaultdict(list)
        by_set = collections.defaultdict(list)
        for rec in recs:
            if isinstance(rec.get("amount"), int):
                by_amount[rec["amount"]].append(rec)
            if isinstance(rec.get("set_id"), int) and rec["set_id"] >= 0x1000:
                by_set[rec["set_id"]].append(rec)

        rooms = []
        for room_number, group in sorted(by_amount.items()):
            xs = [r["x"] for r in group if isinstance(r.get("x"), (int, float))]
            zs = [r["z"] for r in group if isinstance(r.get("z"), (int, float))]
            kinds = collections.Counter(r.get("kind") for r in group)
            rooms.append({
                "room": room_number,
                "set_ids": sorted({r.get("set_id") for r in group if isinstance(r.get("set_id"), int) and r["set_id"] >= 0x1000}),
                "placements": len(group),
                "bounds": [round(min(xs), 1), round(min(zs), 1), round(max(xs), 1), round(max(zs), 1)] if xs and zs else None,
                "kinds": {str(k): v for k, v in kinds.items()},
            })
        inventory[layout] = {"placements": len(recs), "rooms": len(rooms),
                             "distinct_set_ids": len(by_set), "room_list": rooms}
        print(f"{layout:16s} {len(recs):4d} placements  {len(rooms):3d} rooms  {len(by_set):3d} set ids")

    open(OUT, "w", encoding="utf-8").write(json.dumps(inventory, indent=1))
    print("\nsaved", OUT)

    # show one layout in detail, and check the set-id-to-room claim
    sample = inventory.get("map_cave01_00")
    if sample:
        print(f"\n=== map_cave01_00: {sample['rooms']} rooms ===")
        for room in sample["room_list"][:12]:
            bounds = room["bounds"]
            span = f"({bounds[0]:.0f},{bounds[1]:.0f})..({bounds[2]:.0f},{bounds[3]:.0f})" if bounds else "?"
            print(f"  room {room['room']:4d}  set_ids {room['set_ids'][:2]}  {room['placements']:3d} placements  {span}")

        print("\nis each set_id one room?")
        shared = [room for room in sample["room_list"] if len(room["set_ids"]) > 1]
        print(f"  rooms in cave01_00 whose placements span more than one set_id: {len(shared)}")
        dupes = collections.Counter(sid for room in sample["room_list"] for sid in room["set_ids"])
        repeated = {sid: n for sid, n in dupes.items() if n > 1}
        print(f"  set_ids shared by more than one room: {len(repeated)}")
        print("  -> a set_id identifies a room instance" if not repeated and not shared
              else "  -> set_id and room number are not one-to-one")
