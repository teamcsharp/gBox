"""Teach self-play which rooms are unreachable, so it never targets them.

The map audit found that Forest 2 rooms 1, 2 and 13 cannot be reached from room 0 through the walkable graph even after doorway cells are included:
room 13 has no doorway in the mesh at all, and rooms 1 and 2 connect only to each other. Whatever the reason - a secret room, a mesh segmentation
artefact, or a route the collision mesh classifies as wall - the consequence for the bot is concrete: picking one of those rooms as a destination
means walking into geometry and never arriving.

`room_db` already computes reachability per floor. This makes self-play read that audit and exclude unreachable rooms from the candidate list, so an
unreachable destination can never be chosen.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\selfplay2.py")
text = path.read_text(encoding="utf-8")

helper = '''AUDIT = Path(r"D:\\gBox\\pso-ds\\routes\\map-audit.json")


def unreachable_rooms(floor_number):
    """Rooms the map audit proved unreachable on this floor, so they are never chosen as a destination."""
    try:
        entries = json.loads(AUDIT.read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return set()
    for entry in entries if isinstance(entries, list) else [entries]:
        if int(entry.get("floor", -1)) == int(floor_number):
            return set(entry.get("unreachable_rooms") or [])
    return set()


def rooms():'''
text = text.replace("def rooms():", helper, 1)

old = '''        candidates = [r for r in room_list if r["room"] not in visited] or room_list'''
new = '''        blocked = unreachable_rooms(graph_floor)
        usable = [r for r in room_list if r["room"] not in blocked] or room_list
        candidates = [r for r in usable if r["room"] not in visited] or usable'''
if text.count(old) != 1:
    raise SystemExit(f"candidate pattern count {text.count(old)}")
text = text.replace(old, new)
path.write_text(text, encoding="utf-8")
print("self-play now excludes rooms the audit proved unreachable")
