"""On floors with no room graph, wander instead of following another floor's rooms.

`rooms()` falls back to Forest 1's graph when the current floor has no mesh, which is actively harmful: on Cave 1 the bot would plan towards Forest 1
room centres that do not exist in that area, which is one source of "walking into a wall".

The correct behaviour without a map is to explore: pick a point a moderate distance away in a random direction, walk to it, repeat. The height-aware
planner still applies, and the warp watcher keeps looking for the area warp, so a real exit is still discovered if the bot crosses it.

A room graph is only used when the file for THIS floor exists, so a missing map can no longer masquerade as a known one.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\selfplay2.py")
text = path.read_text(encoding="utf-8")

# rooms() must not fall back to another floor's graph
old = '''    path = ROOMS.parent / f"forest{current}-rooms-mesh.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("rooms") or []
    except Exception:                                            # noqa: BLE001
        try:
            return json.loads(ROOMS.read_text(encoding="utf-8")).get("rooms") or []
        except Exception:                                        # noqa: BLE001
            return []'''
new = '''    path = ROOMS.parent / f"forest{current}-rooms-mesh.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("rooms") or []
    except Exception:                                            # noqa: BLE001
        return []'''
if text.count(old) != 1:
    raise SystemExit(f"rooms fallback count {text.count(old)}")
text = text.replace(old, new)

# wander when there is no graph for this floor
old_travel = '''        candidates = [r for r in room_list if r["room"] not in visited] or room_list
        if not candidates:
            time.sleep(0.5)
            continue'''
new_travel = '''        if not room_list:
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
            continue'''
if text.count(old_travel) != 1:
    raise SystemExit(f"travel candidate count {text.count(old_travel)}")
text = text.replace(old_travel, new_travel)
path.write_text(text, encoding="utf-8")
print("self-play wanders on unmapped floors and no longer borrows another floor's rooms")
