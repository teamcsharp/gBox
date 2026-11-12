"""Is the `link` field the room connection? If so, the room graph comes from the disc.

`pso_setdata` decodes a `link` lane on every placement (the first Forest 1 record had `link: 53`). In a 68-byte object record, a small integer that is not geometry is
either a variant selector or a *connection* - and a connection between rooms is precisely what `pso_knowledge.record_edge` needs and what room-to-room path-guiding
runs on.

The test is whether `link` values coincide with room numbers (`amount`). If, for each room, its links name other rooms in the same layout, then the disc carries the
adjacency graph directly and no walking is required to build it.
"""
import collections
import json
import sys

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import gcdisc, pso_setdata                             # noqa: E402

DISC = r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz"
LAYOUT = "map_cave01_00"


if __name__ == "__main__":
    disc = gcdisc.GCDisc(DISC)
    recs = pso_setdata.records(disc.read(LAYOUT + "d.dat"))
    print(f"{LAYOUT}: {len(recs)} placements")

    rooms = sorted({r["amount"] for r in recs if isinstance(r.get("amount"), int)})
    print(f"rooms: {rooms}")

    links = collections.Counter(r.get("link") for r in recs if isinstance(r.get("link"), int))
    print(f"\nlink values ({len(links)} distinct): {sorted(links)[:24]}")

    # do link values look like room numbers?
    as_rooms = [v for v in links if v in rooms]
    print(f"link values that are also room numbers: {len(as_rooms)} of {len(links)} -> {as_rooms[:12]}")

    # per-room link sets
    print("\nper room, which links appear:")
    graph = collections.defaultdict(set)
    for room in rooms:
        group = [r for r in recs if r.get("amount") == room]
        room_links = sorted({r["link"] for r in group if isinstance(r.get("link"), int)})
        other_links = [v for v in room_links if v in rooms and v != room]
        print(f"  room {room:4d}  {len(group):3d} placements  links {room_links[:8]}"
              + (f"  -> other rooms {other_links}" if other_links else ""))
        for value in other_links:
            graph[room].add(value)

    if graph:
        print("\n=== implied adjacency ===")
        for room in sorted(graph):
            print(f"  {room} <-> {sorted(graph[room])}")
        edges = {(min(a, b), max(a, b)) for a, target in graph.items() for b in target}
        print(f"\n{len(edges)} undirected connections from {len(graph)} rooms")
        print(f"connectivity: {len(graph)} of {len(rooms)} rooms have at least one cross-room link")
    else:
        print("\nno link value names another room - `link` is not the room connection")

    # sanity: do the placements carrying a cross-room link sit near a room edge?
    print("\npositions of placements whose link names another room (first 8):")
    shown = 0
    for rec in recs:
        if not isinstance(rec.get("link"), int) or rec["link"] not in rooms or rec["link"] == rec.get("amount"):
            continue
        print(f"  room {rec['amount']:4d} kind {rec['kind']:3d} at ({rec['x']:8.1f}, {rec['z']:8.1f}) "
              f"-> link {rec['link']}")
        shown += 1
        if shown >= 8:
            break
