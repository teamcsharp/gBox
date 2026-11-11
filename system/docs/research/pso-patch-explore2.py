"""Add a precise fallback to explore2: when the minimap shows no exit marker, steer at the door that the room graph says joins
the current room to the target room (forest1-rooms.json carries each door's room pair), instead of at the target room's centre.
"""
import json
import pathlib

PATH = pathlib.Path(r"C:\_tools\gBox\.tmp\explore2.py")
text = PATH.read_text(encoding="utf-8")

OLD_HELPER = '''def pick_marker(point, room, markers):
    """The minimap marker whose bearing points at the chosen room."""
    room_bearing = bearing(point, room["centre"])
    best = None
    for marker in markers:
        error = abs(((marker["bearing"] - room_bearing) + 180) % 360 - 180)
        if best is None or error < best[0]:
            best = (error, marker)
    return best'''

NEW_HELPER = '''def pick_marker(point, room, markers):
    """The minimap marker whose bearing points at the chosen room, or (None, None) when the map shows no exits."""
    if not markers:
        return None, None
    room_bearing = bearing(point, room["centre"])
    best = None
    for marker in markers:
        error = abs(((marker["bearing"] - room_bearing) + 180) % 360 - 180)
        if best is None or error < best[0]:
            best = (error, marker)
    return best[0], best[1] if best else (None, None)


def connecting_door(current_room, target_room):
    """The doorway the room graph says links two rooms, or None."""
    try:
        data = json.loads(pathlib.Path(r"D:\\gBox\\pso-ds\\routes\\forest1-rooms.json").read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return None
    for door in data.get("doors", []):
        rooms = door.get("rooms") or []
        if len(rooms) >= 2 and {rooms[0], rooms[1]} == {current_room, target_room}:
            return door
    return None'''

assert text.count(OLD_HELPER) == 1, text.count(OLD_HELPER)
text = text.replace(OLD_HELPER, NEW_HELPER)

OLD_FALLBACK = '''        markers = ME.exits_from_map()
        if not markers:
            log("no exit markers on the minimap; falling back to the room centre")
            E.STEER.step_toward(pso_input.hold, ME.read_pos, target_room["centre"], tolerance=25.0, max_steps=12, log=None)
            continue
        error, marker = pick_marker(point, target_room, markers)'''

NEW_FALLBACK = '''        markers = ME.exits_from_map()
        error, marker = pick_marker(point, target_room, markers)
        if marker is None:
            door = connecting_door(current, target_room["room"])
            if door is not None:
                log(f"no exit marker; room graph links {current} -> {target_room['room']} via "
                    f"{door['class']} at ({door['x']:.0f},{door['z']:.0f})")
                through, position, reason = door_pass2.approach(
                    door_pass2.GameDeps(), (door["x"], door["z"]), straight_steps=6, attempts=8)
                log(f"  through={through} at {None if position is None else tuple(round(v) for v in position)} ({reason})")
                continue
            log("no exit marker and no door edge; falling back to the room centre")
            E.STEER.step_toward(pso_input.hold, ME.read_pos, target_room["centre"], tolerance=25.0, max_steps=12, log=None)
            continue'''

assert text.count(OLD_FALLBACK) == 1, text.count(OLD_FALLBACK)
text = text.replace(OLD_FALLBACK, NEW_FALLBACK)

if "import pathlib" not in text:
    text = text.replace("import json\nimport math", "import json\nimport math\nimport pathlib")

PATH.write_text(text, encoding="utf-8")
print("explore2 has the room-graph door fallback")
