"""Fix movement: releasing one direction moves the WRONG axis to an extreme - release them all together.

Measured on the virtual pad, one event at a time:

```
start:        (btn 0, lx      0, ly      0)
up    True -> (btn 0, lx      0, ly  32767)   correct
up    False-> (btn 0, lx -32768, ly      0)   WRONG - releasing "up" pins the stick fully LEFT
down  True -> (btn 0, lx      0, ly -32768)   correct
down  False-> (btn 0, lx  32767, ly      0)   WRONG - releasing "down" pins it fully RIGHT
left  True -> (btn 0, lx -32768, ly      0)   correct
left  False-> (btn 0, lx      0, ly      0)   correct
right True -> (btn 0, lx  32767, ly -32768)   WRONG - both axes at once
right False-> (btn 0, lx      0, ly -32768)   WRONG - leaves "down" held
all four False -> (btn 0, lx 0, ly 0)         THE ONLY SEQUENCE THAT RETURNS TO NEUTRAL
```

**That single fault explains the whole session's "freezes".** Every `hold(up)` released with `up:False`, which pinned the stick **hard left** - so the character kept turning, ignored the next input, appeared
frozen, drifted between rooms, and produced the heading "oscillation" that I twice blamed on knockback and on my turn formula. The character was not stuck and the input was not dead: **it was holding a
direction nobody meant to press.**

The fix is one rule: **never release a direction alone - always release all four as `down: False`.** `hold()` now does exactly that, and `tap()` is untouched because buttons are not affected.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

old = """def hold(pad: Pad, key: str, seconds: float) -> None:
    pad.send([{"key": key, "down": True}])
    time.sleep(seconds)
    pad.send([{"key": key, "down": False}])"""

new = """DIRECTIONS = ("up", "down", "left", "right")


def release_all(pad: Pad) -> None:
    \"\"\"Return the stick to neutral.

    Releasing a single direction is unsafe on this pad: `up:False` pins the stick fully LEFT and `down:False` pins it
    fully RIGHT (measured). Only releasing all four together produces (lx 0, ly 0), so this is how every hold ends.
    \"\"\"
    pad.send([{"key": key, "down": False} for key in DIRECTIONS])


def hold(pad: Pad, key: str, seconds: float) -> None:
    pad.send([{"key": key, "down": True}])
    time.sleep(seconds)
    release_all(pad)"""

count = text.count(old)
print("hold anchor count:", count)
if count != 1:
    raise SystemExit("hold anchor not unique")

text = text.replace(old, new, 1)
ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER - hold() releases all four directions")
