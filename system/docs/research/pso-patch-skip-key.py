"""Stop chasing key-locked doors: they need a key the bot does not have yet.

The log is unambiguous - the same door, state 224, for seven attempts with distances jumping 17 → 61 → 51 → 21 → 133 → 109 → 166 units as the nearest
candidate changed between cycles. State 224 is gBox's own documented value for **key-locked**, and pressing it repeatedly does nothing because the key is an
item the bot has not picked up.

So a key-locked door is recorded once and then **not chosen as a destination**. The bot explores the rooms it can, fights what is there (keys and items
drop from enemies and boxes), and comes back once it has something to open it with. A door in state 0 (closed but unlocked) and state 880 (animating)
remain valid targets - those open on a press.

This is the difference between exploring a level and being stuck at one wall for minutes at a time.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\play_rooms.py")
text = path.read_text(encoding="utf-8")

# 1. never target a key-locked door
old = """        if "Door" in name and hp <= 0:"""
new = """        if "Door" in name and state == 224 and not getattr(press_switches, "allow_key", False):
            continue                                   # key-locked: needs an item the bot does not have yet
        if "Door" in name and hp <= 0:"""
if text.count(old) == 1:
    text = text.replace(old, new, 1)
    print("key-locked doors are no longer destinations")
else:
    print("filter anchor count", text.count(old))

# 2. and do not press at them in the near-door step either
old_near = """            if doors_now and doors_now[0]["distance"] < 40:"""
new_near = """            openable = [door for door in doors_now if door["state"] != 224]
            if openable and openable[0]["distance"] < 40:
                doors_now = openable"""
if text.count(old_near) == 1:
    text = text.replace(old_near, new_near, 1)
    print("the near-door press ignores key-locked doors")
else:
    print("near anchor count", text.count(old_near))

path.write_text(text, encoding="utf-8")
print("done")
