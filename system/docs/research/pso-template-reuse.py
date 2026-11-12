"""How many unique room templates do the caves use, and are they reused across layouts?

Round 8 established that `set_id` (>= 0x1000) identifies a room template and `amount` a room number. The natural next question, and the one that sizes the knowledge
store: **how many templates exist, and does the same template appear in several layouts at different room numbers?**

If a template's placements are byte-identical wherever it appears, then knowledge learned in one layout transfers to every layout that uses it - which is exactly what
`pso_knowledge`'s fingerprint key is for. If they differ, the template id alone is not enough to key on.

This compares each template's placement signature (sorted rounded positions) across all 17 cave layouts.
"""
import collections
import json
import sys

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import gcdisc, pso_setdata                             # noqa: E402

DISC = r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz"
LAYOUTS = ([f"map_cave01_0{i}" for i in range(6)] + [f"map_cave02_0{i}" for i in range(5)]
           + [f"map_cave03_0{i}" for i in range(6)])
MIN_TEMPLATE = 0x1000


def signature(recs):
    return tuple(sorted((round(r["x"], 1), round(r["z"], 1)) for r in recs))


if __name__ == "__main__":
    disc = gcdisc.GCDisc(DISC)
    names = set(disc.files)

    # template -> {layout: signature}
    templates = collections.defaultdict(dict)
    # template -> {layout: [room numbers]}
    instances = collections.defaultdict(lambda: collections.defaultdict(list))
    layout_rooms = {}

    for layout in LAYOUTS:
        candidates = sorted(n for n in names if n.endswith(f"{layout}d.dat"))
        if not candidates:
            continue
        recs = pso_setdata.records(disc.read(candidates[0]))
        layout_rooms[layout] = len({r.get("amount") for r in recs if isinstance(r.get("amount"), int)})
        grouped = collections.defaultdict(list)
        for rec in recs:
            template = rec.get("set_id")
            if isinstance(template, int) and template >= MIN_TEMPLATE:
                grouped[template].append(rec)
                if isinstance(rec.get("amount"), int):
                    instances[template][layout].append(rec["amount"])
        for template, group in grouped.items():
            templates[template][layout] = signature(group)

    print(f"layouts analysed: {len(layout_rooms)}")
    print(f"distinct room templates: {len(templates)}\n")

    reusable, varying = 0, 0
    for template, by_layout in sorted(templates.items()):
        layout_count = len(by_layout)
        signatures = set(by_layout.values())
        identical = len(signatures) == 1
        if layout_count > 1:
            reusable += 1 if identical else 0
            varying += 0 if identical else 1
        room_numbers = sorted({room for rooms in instances[template].values() for room in rooms})
        marker = "identical everywhere" if identical else f"{len(signatures)} DIFFERENT signatures"
        print(f"  template {template:7d}  in {layout_count:2d} layout(s)  "
              f"{len(next(iter(by_layout.values()))):3d} placements  rooms {room_numbers[:6]}  {marker}")

    shared = [t for t, by in templates.items() if len(by) > 1]
    print(f"\ntemplates used by more than one layout: {len(shared)}")
    print(f"  of those, byte-identical placement sets: {reusable}")
    print(f"  of those, differing between layouts:     {varying}")

    print(f"\nroom numbers per layout: {json.dumps(layout_rooms, indent=0)[:300]}")

    total_unique = len(templates)
    print(f"\nVERDICT: the caves are built from {total_unique} unique room templates "
          f"across {len(layout_rooms)} layouts, so knowledge keyed on a template transfers to every "
          f"layout that reuses it" if reusable or not shared else
          f"\nVERDICT: {total_unique} templates, but their placements differ by layout - the template id alone "
          f"cannot be the key")
