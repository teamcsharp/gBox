"""Do placement records carry a room id? If so, matching is exact instead of a degenerate vote.

The offset vote was degenerate: all six cave layouts produced the same offset (792, -1296) and the player then landed at (-980, 567), outside every cave room's
bounds. A common answer for every candidate is the signature of a biased fit, not a match.

The player's `room` is 50, and `pso_floor_map`'s notes record a Forest 1 session in "rooms 11-16" - so room ids are meaningful. If a set record names its room,
the placements for room 50 can be isolated and the match becomes exact.
"""
import json
import struct
import sys

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import gcdisc, pso_setdata                             # noqa: E402

DISC = r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz"
NAME = "map_cave01_00ad.dat"

if __name__ == "__main__":
    disc = gcdisc.GCDisc(DISC)
    data = disc.read(NAME)
    recs = pso_setdata.records(data)
    print(f"{NAME}: {len(data)} bytes, {len(recs)} placements\n")

    print("every field in a record:")
    print(json.dumps(recs[0], indent=2, default=str)[:1200])

    print("\n=== candidate room-like fields across records ===")
    for field in ("room", "set_id", "group_id", "amount", "kind", "index"):
        values = [r.get(field) for r in recs if field in r]
        if not values:
            continue
        distinct = sorted(set(values), key=lambda v: (str(type(v)), str(v)))
        print(f"  {field:10s} {len(distinct):4d} distinct  sample {distinct[:8]}")

    print("\n=== raw words per record (first 20 bytes) ===")
    for record in recs[:3]:
        raw = record.get("raw") or []
        print("  ", list(raw)[:6])

    # the payload is 68 bytes; the decoded 'raw' array shows the u32 lanes
    print("\n=== which lane looks like a small room id? ===")
    width = len(recs[0].get("raw") or [])
    print("raw lanes:", width)
    for lane in range(width):
        values = [r["raw"][lane] for r in recs if len(r.get("raw") or []) > lane]
        small = [v for v in values if isinstance(v, int) and 0 < v < 200]
        if len(small) >= len(values) * 0.5:
            distinct = sorted(set(small))
            print(f"  lane {lane}: {len(small)}/{len(values)} small values, distinct {distinct[:12]}")
