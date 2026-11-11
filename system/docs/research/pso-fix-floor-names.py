"""Fix the map filenames for floors >= 10 and for areas whose collision file has no layout suffix.

Two defects:
  * `height_map.py` built `map_forest0{floor}c.rel`, which becomes `map_forest010c.rel` for floor 10 - a three-digit name that does not exist;
  * `map_area.py` joined an empty layout with an underscore, producing `map_boss01_c.rel` when the file is really `map_boss01c.rel`.

Both made otherwise valid areas unmapable.
"""
import pathlib

height = pathlib.Path(r"C:\_tools\gBox\.tmp\height_map.py")
text = height.read_text(encoding="utf-8")
old = 'rel = REL / f"map_forest0{floor}c.rel"'
new = 'rel = REL / f"map_forest{int(floor):02d}c.rel"'
count = text.count(old)
print(f"height_map pattern count: {count}")
if count == 1:
    text = text.replace(old, new)
    height.write_text(text, encoding="utf-8")
    print("height_map: floor names now zero-padded to two digits")

area = pathlib.Path(r"C:\_tools\gBox\.tmp\map_area.py")
atext = area.read_text(encoding="utf-8")
old_join = '''    source = REL / f"map_{area}_{layout}c.rel"'''
new_join = '''    suffix = f"_{layout}" if layout else ""
    source = REL / f"map_{area}{suffix}c.rel"'''
count = atext.count(old_join)
print(f"map_area pattern count: {count}")
if count == 1:
    atext = atext.replace(old_join, new_join)
    area.write_text(atext, encoding="utf-8")
    print("map_area: areas without a layout suffix now resolve")
