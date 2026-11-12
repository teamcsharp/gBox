"""Prove room-level routing works on the disc-derived graph, including the negative cases."""
import sys

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import pso_roomgraph as G                              # noqa: E402


if __name__ == "__main__":
    graph = G.load()
    print(f"areas in the graph: {len(graph)}")
    for area, row in sorted(G.summary(graph).items()):
        print(f"  {area:10s} layouts {row['layouts']:2d}  rooms {row['rooms']:3d}  edges {row['edges']:3d}")

    print("\n=== from room 50 (cave01) ===")
    answer = G.neighbours(graph, "cave01", 50)
    print("  connected rooms:", answer["rooms"])
    print("  seen in layouts:", answer["layouts"])

    print("\n=== shortest room sequences ===")
    for goal in (1, 2, 5, 60, 50):
        found = G.path(graph, "cave01", 50, goal)
        doors = len(found) - 1 if found else None
        print(f"  room 50 -> {goal:4d}: {found}  ({doors} doors)" if found else f"  room 50 -> {goal:4d}: no route")

    print("\n=== negative cases ===")
    isolated = 9999
    print(f"  to an unused room ({isolated}): {G.path(graph, 'cave01', 50, isolated)}  (correct: [])")
    try:
        G.neighbours(graph, "no_such_area", 50)
        print("  unknown area did not raise - wrong")
    except G.RoomGraphError as exc:
        print(f"  unknown area raises RoomGraphError: {str(exc)[:60]}")

    print("\n=== nearest of several goals ===")
    best = G.route_to_any(graph, "cave01", 50, [1, 20, 120])
    print(f"  from 50 to any of [1, 20, 120]: {best}")

    reachable = sum(1 for room in (1, 2, 5, 20, 60, 120)
                    if G.path(graph, "cave01", 50, room))
    print(f"\nVERDICT: {reachable} of 6 probed rooms are reachable from room 50 by doors, "
          "computed from the disc's own link data")
