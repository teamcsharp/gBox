"""Self-play v2: one locked target at a time.

The measured failure of v1 was target switching: `nearest_enemy` re-picked every round, and with several moving Beasts in the area the bot chased
whichever was closest at that instant and never stayed inside melee range of one long enough to kill it.

This locks a target by **pointer** and keeps it until it dies (HP 0 or the entity disappears) or the pursuit times out. Only then does it pick the
next one. Everything else is the same loop that already works: fight, loot, then walk to the next unexplored room from the mesh room graph.
"""
import json
import math
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import map_bot as MB                                               # noqa: E402
import map_exit as ME                                              # noqa: E402
import nav_fast as NAV                                             # noqa: E402
import pso_input                                                   # noqa: E402
import run2 as RUN                                                 # noqa: E402
import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, POS, HP = 0x8050D460, 256, 0x38, 0x32C
ROOMS = Path(r"D:\gBox\pso-ds\routes\forest1-rooms-mesh.json")
STATE = Path(r"D:\gBox\pso-ds\selfplay2-state.json")
RECORD = Path(r"D:\gBox\pso-ds\selfplay2.jsonl")
LOG = r"D:\gBox\pso-ds\selfplay2.log"
ENGAGE = 60.0
MELEE = 5.0
GIVE_UP = 60.0


def log(line, event=None):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")
    if event:
        with RECORD.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"t": round(time.time(), 2), **event}) + "\n")


def floor():
    return int.from_bytes(S.read_memory(0x805D5FC0, 4), "big")


def enemies(point, limit=ENGAGE):
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    out = []
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        try:
            name_pointer = int.from_bytes(S.read_memory(pointer, 4), "big")
            if not (0x80000000 <= name_pointer < 0x81800000):
                continue
            name = S.read_memory(name_pointer, 32).split(b"\x00")[0].decode("ascii", "replace")
            if not name.startswith(("TObjEne", "TEne", "TBoss")):
                continue
            blob = S.read_memory(pointer, 0x340)
            if len(blob) < 0x340:
                continue
            x, y, z = struct.unpack(">fff", blob[POS:POS + 12])
            hp = struct.unpack(">H", blob[HP:HP + 2])[0]
        except Exception:                                        # noqa: BLE001
            continue
        distance = math.dist(point, (x, z))
        if distance <= limit:
            out.append({"pointer": pointer, "class": name, "x": x, "z": z, "hp": hp, "distance": distance})
    return out


def rooms():
    """The room graph for the floor the player is on - Forest 1 or Forest 2."""
    try:
        current = floor()
    except Exception:                                            # noqa: BLE001
        current = 1
    path = ROOMS.parent / f"forest{current}-rooms-mesh.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("rooms") or []
    except Exception:                                            # noqa: BLE001
        return []


def room_of(point, room_list):
    best = None
    for room in room_list:
        distance = math.dist(point, (room["centre"][0], room["centre"][1]))
        if best is None or distance < best[0]:
            best = (distance, room["room"])
    return best[1] if best else None


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return {"visited": []}


def save_state(state):
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")


def pursue(locked):
    """Close on the locked enemy and swing. Returns True if it is gone or damaged."""
    point = ME.read_pos()
    if point is None:
        return False
    gap = math.dist(point, (locked["x"], locked["z"]))
    if not pso_input.allowed():
        return False
    if gap > MELEE:
        # beyond melee reach: cast, because techniques carry that far and the operator one-shots at 36-69 units this way
        pso_input.hold("b", 0.25)
        time.sleep(0.45)
        return True
    MB.attack_while_stepping((locked["x"], locked["z"]), swings=3)
    return True


def now_y():
    """The player's current height, for height-aware planning."""
    point = ME.read_pos()
    if point is None:
        return None
    try:
        import struct as _struct
        pointer = int.from_bytes(S.read_memory(0x8050EA10, 4), "big")
        blob = S.read_memory(pointer + 0x38, 12)
        if len(blob) == 12:
            return _struct.unpack(">fff", blob)[1]
    except Exception:                                            # noqa: BLE001
        return None
    return None


def room_height(room):
    """Median floor height of a room from the room database, when available."""
    try:
        import json as _json
        index = _json.loads(Path(r"D:\gBox\pso-ds\rooms\index.json").read_text(encoding="utf-8"))
        entry = index.get(str(floor())) or {}
        payload = _json.loads((Path(r"D:\gBox\pso-ds\rooms") / entry.get("file", "")).read_text(encoding="utf-8"))
        for record in payload.get("rooms") or []:
            if record.get("room") == room:
                return record.get("height", {}).get("median")
    except Exception:                                            # noqa: BLE001
        return None
    return None


ORDER = Path(r"D:\gBox\pso-ds\goto-order.json")
_last_order = [0.0]


def take_order():
    """The pending map order, if it is newer than the last one consumed."""
    try:
        payload = json.loads(ORDER.read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return None
    if payload.get("t", 0) <= _last_order[0]:
        return None
    _last_order[0] = payload.get("t", 0)
    return {"x": payload["x"], "z": payload["z"]}


def main():
    room_list = rooms()
    graph_floor = floor()
    state = load_state()
    visited = set(state.get("visited", []))
    locked = None
    locked_at = 0.0
    log(f"=== self-play v2 on floor {floor()}, {len(room_list)} rooms, visited {sorted(visited)}")
    while True:
        if not pso_input.allowed():
            time.sleep(0.4)
            continue
        point = ME.read_pos()
        if point is None:
            time.sleep(0.4)
            continue
        if floor() != graph_floor:
            graph_floor = floor()
            room_list = rooms()
            visited = set()
            log(f"floor changed to {graph_floor} - reloaded {len(room_list)} rooms, visited reset")
        room = room_of(point, room_list)
        if room is not None and room not in visited:
            visited.add(room)
            state["visited"] = sorted(visited)
            save_state(state)
            log(f"entered room {room} at ({point[0]:.0f},{point[1]:.0f})", {"event": "room", "room": room})

        present = {row["pointer"]: row for row in enemies(point)}
        if locked is not None:
            current = present.get(locked["pointer"])
            if current is None or current["hp"] == 0:
                log(f"target {locked['class']} down", {"event": "kill", "class": locked["class"]})
                locked = None
            elif time.time() - locked_at > GIVE_UP:
                log(f"giving up on {locked['class']} after {GIVE_UP:.0f}s "
                    f"(hp {current['hp']})", {"event": "give_up", "class": locked["class"]})
                locked = None

        if locked is None:
            candidates = [row for row in present.values() if row["hp"] > 0]
            if candidates:
                locked = min(candidates, key=lambda row: row["distance"])
                locked_at = time.time()
                log(f"locking target {locked['class']} at {locked['distance']:.0f} units "
                    f"(hp {locked['hp']})", {"event": "lock", "class": locked["class"], "hp": locked["hp"]})

        if locked is not None:
            locked["distance"] = math.dist(point, (locked["x"], locked["z"]))
            pursue(locked)
            continue

        order = take_order()
        if order is not None:
            log(f"following the map order to ({order['x']:.0f},{order['z']:.0f})", {"event": "order", **order})
            here = ME.read_pos()
            if here is not None:
                import nav3
                route, raw_cells, legs = nav3.plan_h(here, (order["x"], order["z"]), start_height=now_y())
                if route:
                    log(f"  order route: {raw_cells} cells -> {legs} legs")
                    for waypoint in route[1:]:
                        RUN.run_to(ME.read_pos, (waypoint[0], waypoint[1]), tolerance=8.0, budget=20.0)
                        if not pso_input.allowed():
                            break
                else:
                    RUN.run_to(ME.read_pos, (order["x"], order["z"]), tolerance=10.0, budget=30.0)
            continue

        if not room_list:
            # no map for this floor: explore rather than invent destinations
            import random
            here = ME.read_pos()
            if here is None:
                time.sleep(0.4)
                continue
            bearing = random.uniform(0, 6.283)
            reach = random.uniform(90.0, 220.0)
            goal = (here[0] + math.cos(bearing) * reach, here[1] + math.sin(bearing) * reach)
            log(f"no map for floor {floor()} - wandering toward ({goal[0]:.0f},{goal[1]:.0f})",
                {"event": "wander", "goal": [round(goal[0]), round(goal[1])]})
            import nav3
            route, raw_cells, legs = nav3.plan_h(here, goal, start_height=now_y())
            if route:
                for waypoint in route[1:4]:
                    RUN.run_to(ME.read_pos, (waypoint[0], waypoint[1]), tolerance=10.0, budget=20.0)
                    if not pso_input.allowed():
                        break
            else:
                RUN.run_to(ME.read_pos, goal, tolerance=15.0, budget=25.0)
            continue

        candidates = [r for r in room_list if r["room"] not in visited] or room_list
        if not candidates:
            time.sleep(0.5)
            continue
        target = min(candidates, key=lambda r: math.dist(point, (r["centre"][0], r["centre"][1])))
        log(f"nothing to fight - walking to room {target['room']} "
            f"({target['centre'][0]:.0f},{target['centre'][1]:.0f})", {"event": "travel", "room": target["room"]})
        here = ME.read_pos()
        if here is not None:
            import nav3
            route, raw_cells, legs = nav3.plan_h(here, (target["centre"][0], target["centre"][1]),
                                                 start_height=now_y(), goal_height=room_height(target["room"]))
            if route:
                log(f"  height-aware route: {raw_cells} cells -> {legs} legs")
                for waypoint in route[1:]:
                    arrived, elapsed, final, travelled, cycles = RUN.run_to(
                        ME.read_pos, (waypoint[0], waypoint[1]), tolerance=10.0, budget=25.0)
                    if not pso_input.allowed():
                        break
            else:
                RUN.run_to(ME.read_pos, (target["centre"][0], target["centre"][1]), tolerance=22.0, budget=40.0)
        time.sleep(0.3)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        log("stopped")
