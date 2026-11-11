"""Fix doorway_cells: the mesh stores a doorway as scalar x and z, not as a coordinate tuple."""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\nav_doors.py")
text = path.read_text(encoding="utf-8")

start = text.find("    cells = set()")
end = text.find("    return cells", start)
if start < 0 or end < 0:
    raise SystemExit("doorway_cells body not found")
end += len("    return cells")

body = '''    cells = set()
    for door in graph.get("doors") or []:
        x, z = door.get("x"), door.get("z")
        if isinstance(x, (int, float)) and isinstance(z, (int, float)):
            # a doorway is wider than one cell, so include the surrounding cells too
            cx, cz = int(x // CELL), int(z // CELL)
            for dx in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    cells.add((cx + dx, cz + dz))
        centre = door.get("centre")
        if isinstance(centre, (list, tuple)) and len(centre) >= 2:
            cells.add((int(centre[0] // CELL), int(centre[1] // CELL)))
    return cells'''

text = text[:start] + body + text[end:]
path.write_text(text, encoding="utf-8")
print("doorway_cells now reads scalar x/z and includes neighbouring cells")
