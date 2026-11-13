"""Press the interact from where the walk actually arrives, not from an arbitrary 12 units.

Measured in the live loop:

```
INTERACT: walking to TObjDoorKey (switch) 131 -> 84 units
INTERACT: walking to TObjDoorKey (switch)  84 -> 52 units
INTERACT: walking to TObjDoorKey (switch)  52 -> 23 units
INTERACT: walking to TObjDoorKey (switch)  23 -> 23 units   <- stalls
```

The walk closes **131 -> 23 units** and then cannot get closer - the switch sits behind or inside geometry the collision
mesh will not let the character cross. With the press threshold at 12 units, the bot stops 11 units short and never
presses. **That is precisely "walks right up to switches and you're not flipping them".**

Fix: press from **25 units**. An `A` press costs nothing when nothing is offered, and the game's own interact radius is
generous - the operator's screenshots show the prompt appearing while the character is still a stride away. Walking is
also given more steps so a partial approach is not cut short.

Order is kept: try to get close, then press, and press repeatedly, because the first press can land while the reticle is
still resolving.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

swaps = [
    (
        "            if idist <= 12.0:\n"
        "                # The game is offering the interact. Press A twice: the first press can land while the reticle is still\n"
        "                # resolving, and a teleporter needs the action, not a nudge.\n"
        "                tap(pad, \"a\")\n"
        "                time.sleep(0.4)\n"
        "                tap(pad, \"a\")\n"
        "                time.sleep(0.25)\n",
        "            if idist <= 25.0:\n"
        "                # PRESS FROM 25 UNITS. The walk closes to ~23 and then cannot get closer, because the switch sits\n"
        "                # behind geometry the collision mesh will not cross; with the old 12-unit gate the bot stopped\n"
        "                # 11 units short and never pressed. A press costs nothing if nothing is offered.\n"
        "                for _ in range(3):\n"
        "                    tap(pad, \"a\")\n"
        "                    time.sleep(0.35)\n",
    ),
    (
        "walk_to(pad, float(ient.get(\"x\") or 0), float(ient.get(\"z\") or 0), max_steps=40)",
        "walk_to(pad, float(ient.get(\"x\") or 0), float(ient.get(\"z\") or 0), max_steps=70)",
    ),
]

for old, new in swaps:
    count = text.count(old)
    print("anchor count:", count, "|", old.strip().splitlines()[0][:60])
    if count != 1:
        raise SystemExit("anchor not unique")
    text = text.replace(old, new, 1)

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER - presses from 25 units, walk allowed 70 steps")
