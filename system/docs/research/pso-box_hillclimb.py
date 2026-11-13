"""Steer to a box by measured distance, with patience and shorter steps near the target.

The box approach used the map route only to pick a **turn direction from the waypoint's X alone**, then took a fixed **0.7 s** step:

```python
hold(pad, "left" if step[0] >= x else "right", 0.16)
hold(pad, "up", 0.7)
```

Measured consequence: the distance **oscillated** - `94.3 -> 21.0 -> 16.4 -> 65.3 -> 134.5 -> 14.5` - closing to 14 units and then being flung 100 away. Two faults in that line:

* **the turn ignores Z**, so when the waypoint lies mostly along Z the character turns the wrong way;
* **a fixed 0.7 s step is far too long at 15 units** - it overshoots by tens of units, which is the "jump away" half of the pattern.

Both are fixed the way the enemy approach was fixed, and that one is proven (it closed a target from **210 units to 12**): **hill-climb on measured distance with patience**.

* record the distance, turn a side, step, **re-measure**;
* if it improved, keep that side; only flip after **`PATIENCE`** consecutive misses, because a single sample taken too soon is noise - that exact mistake made an earlier hill-climb flip every step;
* **scale the step to the remaining distance** (0.35 s near, 0.6 s far), so 15 units is approached in small moves rather than overshot.

The map still decides *which* box to chase, and `map_step` still supplies a direction when it has one; what changes is that the **movement** decision is now based on what actually happened, not on a
guess about which way is closer.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

old = """                else:
                    step = map_step(pad, bx, bz)
                    if step:
                        hold(pad, "left" if step[0] >= x else "right", 0.16)
                        hold(pad, "up", 0.7)
                        map_steps += 1
                    else:
                        hold(pad, "left" if int(time.time() * 3) % 2 else "right", 0.2)
                        hold(pad, "up", 0.7)
                    box_debug += 1
                    if box_debug % 4 == 1:
                        log(f"  box {box.get('class')} d={bdist:.1f} route={'yes' if step else 'no'}")"""

new = """                else:
                    # Hill-climb on the distance that is actually measured, with patience and a step scaled to the
                    # remaining distance. The map still chooses the box; the movement is decided by what happened.
                    step = map_step(pad, bx, bz)
                    side_b = globals().get("BOX_SIDE", 1)
                    hold(pad, "left" if side_b > 0 else "right", 0.16)
                    hold(pad, "up", 0.35 if bdist < 30.0 else 0.6)
                    time.sleep(0.2)
                    after_b = state(pad).get("player") or {}
                    now_b = math.hypot(bx - float(after_b.get("x") or 0), bz - float(after_b.get("z") or 0))
                    if now_b < bdist - 1.0:
                        box_misses = 0
                    else:
                        box_misses += 1
                        if box_misses >= 3:
                            globals()["BOX_SIDE"] = -side_b
                            box_misses = 0
                    box_debug += 1
                    if box_debug % 4 == 1:
                        log(f"  box {box.get('class')} d={bdist:.1f} -> {now_b:.1f} "
                            f"side={side_b:+d} route={'yes' if step else 'no'}")"""

count = text.count(old)
print("box approach anchor count:", count)
if count != 1:
    raise SystemExit("box approach not unique - refusing to guess")
text = text.replace(old, new, 1)
print("box approach is now a measured hill-climb")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
