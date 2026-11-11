"""Train from the operator's demonstrations: turn recorded play into routes and door decisions the bot can execute.

Input: every D:\\gBox\\pso-ds\\demos\\demo-<stamp>\\state.jsonl (2 Hz samples of position, floor, HP, all door states, all enemies) and the
room graph in forest1-rooms.json.

What it learns:
  * which room the operator was in over time (from the room cell lists),
  * every room-to-room transition: which door was used, the path taken (simplified), HP before/after, whether enemies died on the way,
  * per-door decisions: was the door already unlocked, did the operator have to clear the room first, how long it took.

Output: D:\\gBox\\pso-ds\\learned\\routes.json, consumable by learned_route.py / map_bot.py.
"""
import json
import math
import sys
from collections import Counter
from pathlib import Path

DEMOS = Path(r"D:\gBox\pso-ds\demos")
ROOMS_FILE = Path(r"D:\gBox\pso-ds\routes\forest1-rooms.json")
OUT_DIR = Path(r"D:\gBox\pso-ds\learned")
OUT = OUT_DIR / "routes.json"
SIMPLIFY_STEP = 15.0


def load_rooms():
    data = json.loads(ROOMS_FILE.read_text(encoding="utf-8"))
    rooms = []
    for room in data["rooms"]:
        cells = [tuple(c) for c in room["cell_list"]]
        rooms.append({"room": room["room"], "cells": cells, "centre": tuple(room["centre"]),
                      "cell_set": set(cells)})
    doors = data["doors"]
    return rooms, doors


def room_of(point, rooms):
    """The room whose cell cloud contains (or is nearest to) the point."""
    x, z = point
    best = None
    for room in rooms:
        distance = math.dist((x, z), room["centre"])
        if best is None or distance < best[0]:
            best = (distance, room["room"])
        # exact cell hit
        cx, cz = int(round(x / 10.0 - 0.5) * 10 + 5), int(round(z / 10.0 - 0.5) * 10 + 5)
        if (cx, cz) in room["cell_set"]:
            return room["room"]
    return best[1] if best else None


def door_state_near(sample, x, z, limit=14.0):
    """A door's state from a live sample, matched by POSITION because entity indices shift between area loads."""
    best = None
    for door in sample.get("doors", []):
        distance = math.dist((x, z), (door["x"], door["z"]))
        if best is None or distance < best[0]:
            best = (distance, door["state"])
    return best[1] if best and best[0] <= limit else None


def nearest_door(point, doors):
    best = None
    for door in doors:
        distance = math.dist(point, (door["x"], door["z"]))
        if best is None or distance < best[0]:
            best = (distance, door)
    return best[1] if best and best[0] <= 40 else None


def simplify(points, step=SIMPLIFY_STEP):
    if not points:
        return []
    out = [points[0]]
    for point in points[1:]:
        if math.dist(point, out[-1]) >= step:
            out.append(point)
    if out[-1] != points[-1]:
        out.append(points[-1])
    return [[round(p[0], 1), round(p[1], 1)] for p in out]


def read_session(state_path):
    samples = []
    for line in state_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:                                        # noqa: BLE001
            continue
        if row.get("x") is None:
            continue
        samples.append(row)
    samples.sort(key=lambda r: r.get("t", 0))
    return samples


def main():
    rooms, doors = load_rooms()
    print(f"rooms {len(rooms)}, doors {len(doors)}")
    transitions = []
    door_actions = {}
    sessions = sorted(DEMOS.glob("demo-*/state.jsonl"))
    total_samples = 0
    for state_path in sessions:
        samples = read_session(state_path)
        if len(samples) < 2:
            continue
        total_samples += len(samples)
        print(f"\n{state_path.parent.name}: {len(samples)} samples")
        current_room = room_of((samples[0]["x"], samples[0]["z"]), rooms)
        segment = [(samples[0]["x"], samples[0]["z"])]
        segment_start = 0
        for index in range(1, len(samples)):
            row = samples[index]
            room = room_of((row["x"], row["z"]), rooms)
            if room != current_room:
                crossing = nearest_door((row["x"], row["z"]), doors)
                hp_before = samples[segment_start].get("hp")
                hp_after = row.get("hp")
                enemies_before = {e["c"]: e["hp"] for e in samples[segment_start].get("enemies", [])}
                enemies_after = {e["c"]: e["hp"] for e in row.get("enemies", [])}
                killed = sum(1 for name, hp in enemies_before.items() if enemies_after.get(name, 0) <= 0 < hp)
                record = {"session": state_path.parent.name,
                          "from_room": current_room, "to_room": room,
                          "door": crossing["door"] if crossing else None,
                          "door_class": crossing["class"] if crossing else None,
                          "door_x": crossing["x"] if crossing else None,
                          "door_z": crossing["z"] if crossing else None,
                          "door_state_before": None, "door_state_after": None,
                          "hp_before": hp_before, "hp_after": hp_after, "enemies_killed": killed,
                          "duration_s": round(row.get("t", 0) - samples[segment_start].get("t", 0), 1),
                          "path": simplify(segment)}
                # the crossing door's state at the moment of crossing, matched by POSITION because entity indices shift
                if crossing:
                    record["door_state_after"] = door_state_near(row, crossing["x"], crossing["z"])
                    record["door_state_before"] = door_state_near(samples[segment_start], crossing["x"], crossing["z"])
                    entry = door_actions.setdefault(crossing["door"], {
                        "door": crossing["door"], "class": crossing["class"],
                        "x": crossing["x"], "z": crossing["z"], "crossings": 0, "states_seen": [],
                        "enemies_killed_on_approach": 0, "seconds": []})
                    entry["crossings"] += 1
                    entry["states_seen"].append(record["door_state_after"])
                    entry["enemies_killed_on_approach"] += killed
                    entry["seconds"].append(record["duration_s"])
                transitions.append(record)
                print(f"  room {current_room} -> {room} via "
                      f"{record['door_class']} {record['door']} state "
                      f"{record['door_state_before']}->{record['door_state_after']} "
                      f"({len(record['path'])} waypoints, {record['duration_s']}s, killed {killed})")
                current_room = room
                segment = [(row["x"], row["z"])]
                segment_start = index
            else:
                segment.append((row["x"], row["z"]))
    for entry in door_actions.values():
        states = [s for s in entry["states_seen"] if s is not None]
        entry["common_state"] = Counter(states).most_common(1)[0][0] if states else None
        entry["median_seconds"] = sorted(entry["seconds"])[len(entry["seconds"]) // 2] if entry["seconds"] else None
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"sessions": len(sessions), "samples": total_samples,
                               "transitions": transitions,
                               "door_actions": list(door_actions.values())}, indent=1), encoding="utf-8")
    print(f"\n{len(sessions)} sessions, {total_samples} samples, {len(transitions)} room transitions")
    print(f"learned door behaviour for {len(door_actions)} doors")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
