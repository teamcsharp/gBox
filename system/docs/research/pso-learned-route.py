"""Serve the routes learned from the operator's demonstrations to the bot.

`learned/routes.json` holds every room-to-room transition the operator performed, with the path they actually walked. Given a target
point, this chains the learned transitions from the current room to the room containing the target and returns the waypoint list - so the
bot walks a proven route instead of inventing one.

Key finding from the data: the operator walked through TObjDoor 67 and 52 while their state was 0, so the +0x18C state is not a
passability gate. Demonstrated paths are the ground truth.
"""
import json
import math
from pathlib import Path

ROUTES = Path(r"D:\gBox\pso-ds\learned\routes.json")
ROOMS_FILE = Path(r"D:\gBox\pso-ds\routes\forest1-rooms.json")


def _rooms():
    data = json.loads(ROOMS_FILE.read_text(encoding="utf-8"))
    return [{"room": r["room"], "centre": tuple(r["centre"]), "cell_set": {tuple(c) for c in r["cell_list"]},
             "cells": [tuple(c) for c in r["cell_list"]]} for r in data["rooms"]]


def room_of(point, rooms=None):
    rooms = rooms or _rooms()
    x, z = point
    cell = (int(round(x / 10.0 - 0.5) * 10 + 5), int(round(z / 10.0 - 0.5) * 10 + 5))
    for room in rooms:
        if cell in room["cell_set"]:
            return room["room"]
    best = min(rooms, key=lambda r: math.dist((x, z), r["centre"]))
    return best["room"]


def transitions():
    try:
        data = json.loads(ROUTES.read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return []
    return data.get("transitions", [])


def learned_route(start, target, max_legs=6):
    """Chain learned transitions from the room holding `start` to the room holding `target`."""
    rooms = _rooms()
    from_room = room_of(start, rooms)
    to_room = room_of(target, rooms)
    if from_room == to_room:
        return []
    edges = transitions()
    by_pair = {}
    for edge in edges:
        key = (edge["from_room"], edge["to_room"])
        # keep the shortest demonstrated path for each pair
        if key not in by_pair or len(edge["path"]) < len(by_pair[key]["path"]):
            by_pair[key] = edge
    # breadth-first search over the room graph, then concatenate the shortest paths
    queue = [(from_room, [])]
    seen = {from_room}
    best_chain = None
    while queue:
        room, chain = queue.pop(0)
        if room == to_room:
            best_chain = chain
            break
        if len(chain) >= max_legs:
            continue
        for (a, b), edge in by_pair.items():
            if a == room and b not in seen:
                seen.add(b)
                queue.append((b, chain + [edge]))
    if not best_chain:
        return []
    waypoints = []
    for edge in best_chain:
        for point in edge["path"]:
            waypoints.append(tuple(point))
    return waypoints


def describe():
    """Human-readable summary of what has been learned."""
    edges = transitions()
    lines = [f"{len(edges)} learned transitions"]
    counts = {}
    for edge in edges:
        counts.setdefault((edge["from_room"], edge["to_room"]), 0)
        counts[(edge["from_room"], edge["to_room"])] += 1
    for (a, b), number in sorted(counts.items()):
        sample = next(e for e in edges if e["from_room"] == a and e["to_room"] == b)
        lines.append(f"  room {a} -> room {b}: {number} demonstrations, "
                     f"via {sample.get('door_class')} {sample.get('door')} "
                     f"(state {sample.get('door_state_before')}->{sample.get('door_state_after')}), "
                     f"{len(sample['path'])} waypoints, killed {sample.get('enemies_killed')}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(describe())
