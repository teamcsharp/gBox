"""Room-level routing from the disc-derived graph (`routes/room-graph.json`).

`area_fingerprint` keys the live knowledge store on a hash of loaded collision memory, so a disc graph cannot be stored there - but the live state does give
something the graph can be keyed on directly: **the floor** (`0x805D5FC0`, resolved to an area by `pso_floor_map`) and **the player's room number**
(`player.room`).

So this module answers the question the bot actually has: *"I am in room 50 of the caves - which rooms can I reach from here?"* It unions the edges across every
layout of that area, because which layout is loaded is not known until its geometry is hashed; a union is a **superset**, so it never omits a real connection.

That distinction is stated in the API: `neighbours()` is a prior, not a promise. It narrows where to explore, and a live observation overrides it.
"""
from __future__ import annotations

import collections
import json
from pathlib import Path


class RoomGraphError(ValueError):
    pass


def load(path=None) -> dict:
    """Read the graph file: {area: {layout: {rooms, room_numbers, edges}}}."""
    source = Path(path) if path else Path(r"D:\gBox\pso-ds\routes\room-graph.json")
    if not source.is_file():
        raise RoomGraphError(f"no room graph at {source}")
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data:
        raise RoomGraphError("room graph is empty")
    return data


def _area(data: dict, area: str) -> dict:
    key = str(area or "").strip()
    if key not in data:
        raise RoomGraphError(f"area {area!r} is not in the graph (have {sorted(data)[:6]}...)")
    return data[key]


def neighbours(data: dict, area: str, room: int) -> dict:
    """Rooms connected to `room`, unioned across every layout of the area.

    Returns {"rooms": [...], "layouts": [...], "certain": bool} - `certain` is true when exactly one layout carries the edge, which is the case where the union
    adds nothing and the answer is exact.
    """
    edges = collections.defaultdict(set)
    layouts = set()
    for layout, info in _area(data, area).items():
        for a, b in info.get("edges") or []:
            if a == room:
                edges[b].add(layout)
            elif b == room:
                edges[a].add(layout)
    rooms = sorted(edges)
    certain = bool(rooms) and all(len(where) == 1 for where in edges.values()) and len(_area(data, area)) == 1
    return {"rooms": rooms, "layouts": sorted({name for where in edges.values() for name in where}), "certain": certain}


def path(data: dict, area: str, start: int, goal: int, limit: int = 64) -> list:
    """Shortest room sequence from `start` to `goal` over the unioned edges, or [] when unreachable.

    Breadth-first, because every edge is one door: the number of doors is what matters, not distance.
    """
    if start == goal:
        return [start]
    adjacency = collections.defaultdict(set)
    for layout, info in _area(data, area).items():
        for a, b in info.get("edges") or []:
            adjacency[a].add(b)
            adjacency[b].add(a)
    seen = {start: None}
    queue = collections.deque([start])
    while queue and len(seen) < limit:
        room = queue.popleft()
        for neighbour in sorted(adjacency.get(room, ())):
            if neighbour in seen:
                continue
            seen[neighbour] = room
            if neighbour == goal:
                out = [neighbour]
                while seen[out[-1]] is not None:
                    out.append(seen[out[-1]])
                return out[::-1]
            queue.append(neighbour)
    return []


def route_to_any(data: dict, area: str, start: int, goals) -> list:
    """The shortest path from `start` to whichever of `goals` is nearest by doors."""
    best = []
    for goal in sorted(set(int(g) for g in goals)):
        found = path(data, area, start, goal)
        if found and (not best or len(found) < len(best)):
            best = found
    return best


def summary(data: dict) -> dict:
    """Per-area counts, for a status line rather than a guess."""
    out = {}
    for area, layouts in data.items():
        rooms = set()
        edges = set()
        for info in layouts.values():
            rooms.update(info.get("room_numbers") or [])
            edges.update(tuple(edge) for edge in info.get("edges") or [])
        out[area] = {"layouts": len(layouts), "rooms": len(rooms), "edges": len(edges)}
    return out


if __name__ == "__main__":
    graph = load()
    print("areas:", len(graph))
    for area, row in sorted(summary(graph).items()):
        print(f"  {area:10s} layouts {row['layouts']:2d}  rooms {row['rooms']:3d}  edges {row['edges']:3d}")

    print("\nfrom room 50 in the caves:")
    answer = neighbours(graph, "cave01", 50)
    print("  connected rooms:", answer["rooms"])
    print("  seen in layouts:", answer["layouts"])

    target = 1
    found = path(graph, "cave01", 50, target)
    print(f"\nroom 50 -> room {target}: {found}  ({len(found) - 1 if found else 'no'} doors)")
