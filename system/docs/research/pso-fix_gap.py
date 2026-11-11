"""Fix the NameError in selfplay2.pursue: gap was removed but still referenced."""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\selfplay2.py")
text = path.read_text(encoding="utf-8")

old = "    swing_rounds = 1 if gap > MELEE else 2"
new = '    gap = math.dist(point, (locked["x"], locked["z"]))\n    swing_rounds = 1 if gap > MELEE else 2'

count = text.count(old)
print(f"pattern count: {count}")
if count == 1:
    text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")
    print("fixed: pursue computes gap before using it")
elif "gap = math.dist(point" in text:
    print("already fixed")
else:
    print("pattern not found; showing pursue():")
    start = text.find("def pursue(")
    print(text[start:start + 400])
