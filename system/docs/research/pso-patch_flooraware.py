"""Make self-play floor-aware, so it explores Forest 2 now that the level changed.

`selfplay2.py` reads Forest 1's room graph unconditionally, which is wrong the moment the floor changes - and the operator has just completed Forest 1
and moved to floor 2. The mesh room graph for Forest 2 already exists (`forest2-rooms-mesh.json`, 14 rooms).

The room list is now chosen by the live floor id each time it is needed, so a level transition is followed automatically.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\selfplay2.py")
text = path.read_text(encoding="utf-8")

old = '''def rooms():
    try:
        return json.loads(ROOMS.read_text(encoding="utf-8")).get("rooms") or []
    except Exception:                                            # noqa: BLE001
        return []'''
new = '''def rooms():
    """The room graph for the floor the player is on - Forest 1 or Forest 2."""
    try:
        current = floor()
    except Exception:                                            # noqa: BLE001
        current = 1
    path = ROOMS.parent / f"forest{current}-rooms-mesh.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("rooms") or []
    except Exception:                                            # noqa: BLE001
        try:
            return json.loads(ROOMS.read_text(encoding="utf-8")).get("rooms") or []
        except Exception:                                        # noqa: BLE001
            return []'''
if text.count(old) != 1:
    raise SystemExit(f"pattern count {text.count(old)}")
text = text.replace(old, new)

# the room list must be refreshed when the floor changes, so reload it inside the loop
old_loop = "    room_list = rooms()\n    state = load_state()"
new_loop = "    room_list = rooms()\n    graph_floor = floor()\n    state = load_state()"
if text.count(old_loop) == 1:
    text = text.replace(old_loop, new_loop)

old_check = '''        point = ME.read_pos()
        if point is None:
            time.sleep(0.4)
            continue
        room = room_of(point, room_list)'''
new_check = '''        point = ME.read_pos()
        if point is None:
            time.sleep(0.4)
            continue
        if floor() != graph_floor:
            graph_floor = floor()
            room_list = rooms()
            visited = set()
            log(f"floor changed to {graph_floor} - reloaded {len(room_list)} rooms, visited reset")
        room = room_of(point, room_list)'''
if text.count(old_check) == 1:
    text = text.replace(old_check, new_check)

path.write_text(text, encoding="utf-8")
print("selfplay2 is floor-aware")
