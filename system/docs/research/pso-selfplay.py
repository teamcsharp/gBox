"""Self-play: fight what is near, loot what is near, then walk to the next unexplored room.

This is the bot actually playing the game, built on the analysis done earlier:

  * enemies within ENGAGE units are approached and attacked until the entity disappears (a kill also clears rooms, which is what unlocks doors);
  * containers and capsules are approached and opened with A;
  * when nothing is near, the nearest room from the mesh room graph that has not been visited yet becomes the target, and `run2` walks there
    (27 units/s measured), marking it visited on arrival;
  * every action goes through `pso_input`, which yields whenever the operator has been on the pad within three seconds.

Progress is written to `selfplay.jsonl` so a run can be reviewed afterwards: each room entered, each target fought, each item opened.
"""
import json
import math
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import learn_live as L                                             # noqa: E402
import map_exit as ME                                              # noqa: E402
import pso_input                                                   # noqa: E402
import run2 as RUN                                                 # noqa: E402
import session as S                                                # noqa: E402

ROOMS = Path(r"D:\gBox\pso-ds\routes\forest1-rooms-mesh.json")
STATE = Path(r"D:\gBox\pso-ds\selfplay-state.json")
RECORD = Path(r"D:\gBox\pso-ds\selfplay.jsonl")
LOG = r"D:\gBox\pso-ds\selfplay.log"
ENGAGE = 42.0
LOOT = 26.0


def log(line, event=None):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")
    if event:
        with RECORD.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"t": round(time.time(), 2), **event}) + "\n")


def floor_now():
    return int.from_bytes(S.read_memory(0x805D5FC0, 4), "big")


def player():
    return ME.read_pos()


def room_graph():
    try:
        return json.loads(ROOMS.read_text(encoding="utf-8")).get("rooms") or []
    except Exception:                                            # noqa: BLE001
        return []


def room_of(point, rooms):
    best = None
    for room in rooms:
        distance = math.dist(point, (room["centre"][0], room["centre"][1]))
        if best is None or distance < best[0]:
            best = (distance, room["room"])
    return best[1] if best else None


def nearest_enemy(point, limit=ENGAGE):
    best = None
    for entity in L.entities():
        if not entity["c"].startswith(("TObjEne", "TEne", "TBoss", "TObjBoss")):
            continue
        distance = math.dist(point, (entity["x"], entity["z"]))
        if distance <= limit and (best is None or distance < best[0]):
            best = (distance, entity)
    return best


def nearest_loot(point, limit=LOOT):
    best = None
    for entity in L.entities():
        if not entity["c"].startswith(("TObjContainer", "TOCapsule", "TItem")):
            continue
        distance = math.dist(point, (entity["x"], entity["z"]))
        if distance <= limit and (best is None or distance < best[0]):
            best = (distance, entity)
    return best


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return {"visited": []}


def save_state(state):
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")


def main():
    rooms = room_graph()
    state = load_state()
    visited = set(state.get("visited", []))
    skip = {}
    log(f"=== self-play on floor {floor_now()}, {len(rooms)} rooms in the graph, visited {sorted(visited)}")
    while True:
        if not pso_input.allowed():
            time.sleep(0.4)
            continue
        point = player()
        if point is None:
            time.sleep(0.4)
            continue
        room = room_of(point, rooms)
        if room is not None and room not in visited:
            visited.add(room)
            state["visited"] = sorted(visited)
            save_state(state)
            log(f"entered room {room} at ({point[0]:.0f},{point[1]:.0f})", {"event": "room", "room": room,
                                                                             "x": round(point[0]), "z": round(point[1]),
                                                                             "floor": floor_now()})
        enemy = nearest_enemy(point)
        if enemy and skip.get((enemy[1]["c"], round(enemy[1]["x"]), round(enemy[1]["z"])), 0) > time.time():
            enemy = None
        if enemy:
            gap, entity = enemy
            log(f"enemy {entity['c']} at {gap:.0f} units - engaging")
            for _ in range(10):
                if not pso_input.allowed():
                    break
                here = player()
                if here is None:
                    break
                still = nearest_enemy(here, limit=ENGAGE)
                if still is None:
                    break
                gap, target = still
                if gap > 5:
                    RUN.run_to(player, (target["x"], target["z"]), tolerance=4.0, budget=5.0)
                pso_input.hold("a", 0.3)
            if nearest_enemy(player(), limit=ENGAGE):
                skip[(entity["c"], round(entity["x"]), round(entity["z"]))] = time.time() + 45
                log("  target survived - skipping it for 45 s")
            log("  target cleared or skipped", {"event": "fight", "class": entity["c"],
                                                "at": [round(entity["x"]), round(entity["z"])]})
            continue
        loot = nearest_loot(point)
        if loot:
            gap, entity = loot
            log(f"{entity['c']} at {gap:.0f} units - opening", {"event": "loot", "class": entity["c"],
                                                                "at": [round(entity["x"]), round(entity["z"])]})
            RUN.run_to(player, (entity["x"], entity["z"]), tolerance=4.0, budget=5.0)
            pso_input.tap("a", gap=0.35)
            time.sleep(0.4)
            continue
        candidates = [r for r in rooms if r["room"] not in visited] or rooms
        if not candidates:
            time.sleep(0.5)
            continue
        target = min(candidates, key=lambda r: math.dist(point, (r["centre"][0], r["centre"][1])))
        log(f"nothing near - walking to room {target['room']} centre "
            f"({target['centre'][0]:.0f},{target['centre'][1]:.0f})", {"event": "travel", "room": target["room"]})
        arrived, elapsed, final, travelled, cycles = RUN.run_to(
            player, (target["centre"][0], target["centre"][1]), tolerance=22.0, budget=40.0)
        log(f"  travel done arrived={arrived} {elapsed:.0f}s {travelled:.0f} units")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        log("stopped by operator")
