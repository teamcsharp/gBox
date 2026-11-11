"""Save each room's cell list in the database so the minimap can draw the actual room shape."""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\room_db.py")
text = path.read_text(encoding="utf-8")

old = '            "cells": room.get("cells"),'
new = '            "cells": room.get("cells"),\n            "cell_list": cells,'
count = text.count(old)
print(f"pattern count: {count}")
if count == 1:
    text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")
    print("cell_list is now stored per room")
elif '"cell_list": cells' in text:
    print("already stored")
else:
    print("pattern not found")
