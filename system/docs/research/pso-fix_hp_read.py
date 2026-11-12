"""Read hp in switches(): the filter needs it and the scanner never did."""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\play_rooms.py")
text = path.read_text(encoding="utf-8")

old = """            x, y, z = struct.unpack(">fff", blob[POS:POS + 12])
            state = struct.unpack(">i", blob[0x18C:0x18C + 4])[0]"""
new = """            x, y, z = struct.unpack(">fff", blob[POS:POS + 12])
            state = struct.unpack(">i", blob[0x18C:0x18C + 4])[0]
            hp = struct.unpack(">H", blob[HP:HP + 2])[0]"""

count = text.count(old)
print("pattern count:", count)
if count >= 1:
    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
    print("hp read added to switches()")
else:
    for line in text.splitlines():
        if "state = struct.unpack" in line:
            print("  found:", line.strip())
