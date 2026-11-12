"""Build the room adjacency graph from the disc's `link` lane, across every cave layout.

`link` on a placement names another room: room 1's records point at 20, 50, 51, 52, 53, 60 and 120, and their positions are spread across the layout - so they are
connections, not decoration. One layout only exposed two rooms with cross-room links, so the graph has to be built across all 17 and unioned.

That is the room-to-room structure `pso_knowledge.record_edge` stores and room path-guiding needs, and it comes from the disc with no session and no walking. The
output goes next to the other route artefacts so it can seed the knowledge store.
"""
import collections
import json
import sys

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import gcdisc, pso_setdata                             # noqa: E402

DISC = r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz"
OUT = r"D:\gBox\pso-ds\routes\room-graph.json"
AREAS = {
    "cave01": 6, "cave02": 5, "cave03": 6,
    "machine01": 6, "machine02": 6,
    "ruins01": 3, "ruins02": 3,
    "ancient01": 5, "ancient02": 5, "ancient03": 5,
}


if __name__ == "__main__":
    disc = gcdisc.GCDisc(DISC)
    names = set(disc.files)

    result = {}
    total_edges = 0
    for area, count in AREAS.items():
        layouts = {}
        for index in range(count):
            layout = f"map_{area}_0{index}"
            candidates = sorted(n for n in names if n.endswith(f"{layout}d.dat"))
            if not candidates:
                continue
            recs = pso_setdata.records(disc.read(candidates[0]))
            rooms = {r["amount"] for r in recs if isinstance(r.get("amount"), int)}

            edges = set()
            for rec in recs:
                room = rec.get("amount")
                link = rec.get("link")
                if isinstance(room, int) and isinstance(link, int) and link in rooms and link != room:
                    edges.add((min(room, link), max(room, link)))

            layouts[layout] = {
                "rooms": len(rooms),
                "room_numbers": sorted(rooms),
                "edges": sorted([a, b] for a, b in edges),
            }
            total_edges += len(edges)
            print(f"  {layout:16s} {len(rooms):3d} rooms  {len(edges):3d} connections")

        if layouts:
            result[area] = layouts

    open(OUT, "w", encoding="utf-8").write(json.dumps(result, indent=1))
    print(f"\nsaved {OUT}")

    # coverage across all layouts
    rooms_total = sum(layout["rooms"] for area in result.values() for layout in area.values())
    connected = sum(len({v for edge in layout["edges"] for v in edge})
                    for area in result.values() for layout in area.values())
    print(f"layouts: {sum(len(area) for area in result.values())}")
    print(f"room slots: {rooms_total}  |  rooms with at least one connection: {connected}  "
          f"({100 * connected / rooms_total:.0f}%)")
    print(f"connections: {total_edges}")

    # which rooms are hubs?
    hub = collections.Counter()
    for area in result.values():
        for layout in area.values():
            for a, b in layout["edges"]:
                hub[a] += 1
                hub[b] += 1
    print("\nmost connected room numbers across the caves:")
    for room, count in hub.most_common(10):
        print(f"  room {room:4d}  {count} connections")
