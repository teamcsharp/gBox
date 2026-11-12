"""Only chase real, nearby switches: the bot was walking away toward a phantom.

The log shows it:

```
20:22:16   switch TObjDoorKey state 1129705297 at 92 units
20:23:00     step+press x1: at 142.3 units, state 1129705297
```

`1129705297` is not a door state - the real values are 0 closed, 2 open, 224 key, 240 special - so that entity is **not a switch**; it is a `TObjDoorKey`
whose struct no longer carries a state, most likely a despawned or far-room door. The bot walked **toward it and got further away** (92 → 142 units)
while enemies hit it (hp 40 → 27).

Two guards, both narrow:

  * **range**: switches matter within the room they open, so the search drops from 120 units to **40**;
  * **state**: only 0, 2, 224 and 240 are accepted. Anything else is not a door the bot can operate and is skipped.

Nothing else changes - the real key door at 12 units, which is the one the operator pointed at, still qualifies.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\play_rooms.py")
text = path.read_text(encoding="utf-8")

text = text.replace("SWITCH_RANGE = 120.0", "SWITCH_RANGE = 40.0")
print("switch range: 120 -> 40 units")

old = """        distance = math.dist((me[0], me[2]), (x, z))
        if distance <= SWITCH_RANGE:
            out.append({"class": name, "x": x, "y": y, "z": z, "state": state, "distance": distance})"""
new = """        distance = math.dist((me[0], me[2]), (x, z))
        if state not in (0, 2, 224, 240):
            continue                                   # not a door state: a despawned or unrelated door entity
        if distance <= SWITCH_RANGE:
            out.append({"class": name, "x": x, "y": y, "z": z, "state": state, "distance": distance})"""
if text.count(old) == 1:
    text = text.replace(old, new, 1)
    print("only real door states are accepted")
else:
    print("state filter anchor count", text.count(old))

path.write_text(text, encoding="utf-8")
print("done")
