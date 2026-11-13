"""Sweep on enemies as well: the same aim cone that hid the boxes hides the beasts.

The box test settled it - a swing connects only inside an **8-degree** cone, and a fixed heading beside a target misses it:

```
  heading  58: boxes 54   *** BROKE ***      <- the only heading that connected
```

The enemy branch still swings **once** at whatever heading the approach left:

```python
if distance <= 15.5:
    tap(pad, "b"); tap(pad, "a")
```

which is exactly the pattern that produced `TObjEneBeast untouched after 8 swings` over and over. The enemy is not invulnerable; the cone was simply pointing somewhere else.

So the enemy branch gets the same treatment the box branch now has: **three `b`+`a` swings, then a small rotation**, repeated while the enemy is in range. Over a few iterations the cone sweeps
every direction and at least one of them faces the target. Against a 60 HP enemy that is a kill; against an Ultimate 1556 HP beast it is slow but finally real progress instead of none.

This is the single highest-value change available: **the bot has never reliably damaged an enemy**, and every downstream goal - levels, Ultimate, end credits - is gated on exactly that.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

old = """            if distance <= 15.5:
                tap(pad, "b")           # a pause menu eats the swing; START toggles it, B cancels it
                time.sleep(0.12)
                tap(pad, "a")
                time.sleep(0.45)
                killed += 0"""

new = """            if distance <= 15.5:
                # SWEEP the aim cone here too. An attack only connects inside 8 degrees and heading_deg cannot be
                # trusted to aim (presses in one direction gave +130, +21, 0 and +145 degrees), so swing three times
                # and rotate a little each visit. This is the fix for "untouched after 8 swings".
                for _ in range(3):
                    tap(pad, "b")       # a pause menu eats the swing; START toggles it, B cancels it
                    time.sleep(0.08)
                    tap(pad, "a")
                    time.sleep(0.3)
                hold(pad, "left" if int(time.time() * 3) % 2 else "right", 0.2)
                killed += 0
                attacks += 1"""

count = text.count(old)
print("enemy swing anchor count:", count)
if count != 1:
    raise SystemExit("enemy swing block not unique - refusing to guess")
text = text.replace(old, new, 1)

old_decl = "    reticle_hits = 0                                    # presses made because something actionable was close"
new_decl = ("    reticle_hits = 0                                    # presses made because something actionable was close\n"
            "    attacks = 0                                         # swing bursts aimed by sweeping the cone")
if text.count(old_decl) == 1:
    text = text.replace(old_decl, new_decl, 1)
    print("attack counter declared")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER - enemies are swept like boxes")
