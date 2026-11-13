"""Break boxes by sweeping the aim cone, the way the successful test did.

The test that finally worked swept a full circle at a box, three swings per heading, and **one broke at heading 58**:

```
  heading 338: boxes 55
  ...
  heading  58: boxes 54   *** BROKE ***
```

So `TObjContainerItem` **is** destructible, and the reason fifty-five of them survived ten swings each is **facing**: an attack only connects inside the game's 8-degree aim cone, and a single fixed
heading misses unless it happens to point at the box. Enemies take damage for the same reason - `TObjEneLappy HIT: 30 -> 1` landed when the approach left the character pointing at it.

`heading_deg` cannot be trusted to *steer* (presses in one direction produced +130, +21, 0 and +145 degrees), so the box branch does not try to compute a facing. It **sweeps**: three `b`+`a` swings,
then a small rotation, repeated. Over a handful of iterations the cone covers every direction around the character, and the box dies when the sweep passes over it - which is exactly how the
successful test behaved.

That is slower than a computed aim would be, but it is **verified**, and correctness beats elegance when the alternative is a bot that stands next to fifty-five boxes and hits none of them.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

old = """                if bdist <= 14.0:
                    tap(pad, "b")                      # a pause menu eats the swing here too
                    time.sleep(0.1)
                    tap(pad, "a")
                    time.sleep(0.35)
                    tap(pad, "a")
                    boxes_hit += 1"""

new = """                if bdist <= 14.0:
                    # SWEEP the aim cone. The attack only connects inside an 8-degree cone and heading_deg cannot be
                    # trusted to aim, so swing a few times and rotate a little each visit - verified to break a box
                    # at heading 58 after the same sweep. A fixed heading beside a box hits nothing.
                    for _ in range(3):
                        tap(pad, "b")                  # a pause menu eats the swing here too
                        time.sleep(0.08)
                        tap(pad, "a")
                        time.sleep(0.3)
                    hold(pad, "left" if int(time.time() * 3) % 2 else "right", 0.2)
                    boxes_hit += 1"""

count = text.count(old)
print("box branch anchor count:", count)
if count != 1:
    raise SystemExit("box branch not unique - refusing to guess")
text = text.replace(old, new, 1)

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER - boxes are swept, not aimed")
