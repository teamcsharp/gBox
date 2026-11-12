"""Find the real doors: hp is the marker, and capsules count as switches.

The entity dump from the live room shows what separates a door the bot can use from one it cannot:

```
 66.9  TObjDoorKey  state=1129705297  hp=0        <- phantom: garbage state AND no hit points
108.5  TObjDoorKey  state=224         hp=32987    <- a real key door
175.3  TObjDoor    state=224         hp=32987    <- real
220.8  TObjDoor    state=0           hp=16256    <- real, closed
 75.2  TOCapsuleAncient01 state=garbage hp=0       <- the capsule the operator pointed at
```

So **`hp > 0` is the reliable test for a door entity**: the phantom that sent the bot walking 92 units away had `hp == 0`, and every real door carries tens of
thousands. The state filter alone could not tell them apart because the state field is also garbage on non-door entities (the player's own reads -1688555871).

Two changes:

  * **doors require `hp > 0`** - the marker that actually holds;
  * **`Capsule` joins the switch words** - the capsule in the screenshot is the sort of object the operator means by "that button needs to be pressed".

Range rises to **150 units** because the nearest real door in this room is **108** away: a door is worth walking to, which is the whole point of opening it.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\play_rooms.py")
text = path.read_text(encoding="utf-8")

text = text.replace('SWITCH_WORDS = ("Door", "Swtch", "Switch", "Key")',
                    'SWITCH_WORDS = ("Door", "Swtch", "Switch", "Key", "Capsule")')
text = text.replace("SWITCH_RANGE = 40.0", "SWITCH_RANGE = 150.0")
print("capsules join the switch words; range 150")

old = """        if state not in (0, 2, 224, 240):
            continue                                   # not a door state: a despawned or unrelated door entity"""
new = """        if "Door" in name and hp <= 0:
            continue                                   # no hit points: a despawned or unrelated door (the live dump shows 0 vs 32987)
        if "Door" in name and state not in (0, 2, 224, 240):
            continue                                   # not a door state"""
if text.count(old) == 1:
    text = text.replace(old, new, 1)
    print("doors now require hit points")
else:
    print("anchor count", text.count(old))

# the switch dict needs hp, so the check above can see it
old_append = '            out.append({"class": name, "x": x, "y": y, "z": z, "state": state, "distance": distance})'
new_append = '            out.append({"class": name, "x": x, "y": y, "z": z, "state": state, "hp": hp, "distance": distance})'
if text.count(old_append) == 1:
    text = text.replace(old_append, new_append, 1)
    print("switch records now carry hp")
else:
    print("append anchor count", text.count(old_append))

path.write_text(text, encoding="utf-8")
print("done")
