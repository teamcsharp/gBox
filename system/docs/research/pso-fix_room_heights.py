"""Fix the height lookup in room_db: room cells are world coordinates, the height table is keyed by cell index."""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\room_db.py")
text = path.read_text(encoding="utf-8")

old = '        cell_heights = [height_table[cell] for cell in cells if cell in height_table]'
new = ('        index_of = lambda cell: (int(math.floor(cell[0] / 10.0)), int(math.floor(cell[1] / 10.0)))\n'
       '        cell_heights = [height_table[index_of(cell)] for cell in cells if index_of(cell) in height_table]')
if text.count(old) != 1:
    raise SystemExit(f"pattern count {text.count(old)}")
text = text.replace(old, new)
path.write_text(text, encoding="utf-8")
print("height lookup now converts world coordinates to cell indices")
