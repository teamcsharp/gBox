"""Stop nav_fast borrowing Forest 1's collision for other floors.

`rel_for_floor` returned a hardcoded mapping and fell back to Forest 1 for anything unknown - so asking for floor 3's rooms silently segmented Forest
1's geometry and wrote it out as `forest3-rooms-mesh.json`. The room centres in that output were Forest 1's, which is how the bug was caught.

The rule now: use the floor's own file when it exists (`map_forest<NN>c.rel`), otherwise fall back as before. With `map_forest03c.rel` present (Cave
1's live layout, identified by matching 94 of 94 live objects to its walkable cells), floor 3 now resolves to Cave 1's geometry.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\nav_fast.py")
text = path.read_text(encoding="utf-8")

start = text.find("def rel_for_floor(")
if start < 0:
    raise SystemExit("rel_for_floor not found")
end = text.find("def cells(", start)
if end < 0:
    raise SystemExit("cells() not found")

body = '''def rel_for_floor(floor=None):
    """The collision file for a floor: the floor's own map when it exists, else the historical fallback."""
    if floor is None:
        return REL
    try:
        candidate = REL.parent / f"map_forest{int(floor):02d}c.rel"
    except (TypeError, ValueError):
        return REL
    if candidate.exists():
        return candidate
    return FLOOR_REL.get(floor, REL)


'''
text = text[:start] + body + text[end:]
path.write_text(text, encoding="utf-8")
print("rel_for_floor now prefers the floor's own map file")
