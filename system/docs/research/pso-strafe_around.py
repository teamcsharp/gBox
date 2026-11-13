"""Go around obstacles: if forward is blocked, strafe sideways - measured 90 units of free movement.

The freeze probe finally named the failure, and it is not a lock:

```
*** FROZEN ***  position (202,219) y 17.7 room 11 | nearest: TObjEneBeast at 12.2 units
    up   :   0.0 units      <- blocked
    down :  53.9 units
    left :  90.6 units      <- free, and far
    right:  38.0 units
  up again afterwards: 75.8 units
```

**Forward is blocked by something (an enemy at 12.2 units, or a wall), and the other three directions are wide open.** The bot's approach only ever pressed `up`, so it got 0, and to a viewer that looks exactly like the bot "struggling and zigzagging" - it is pressing into a wall.

So `steer_to` gains obstacle avoidance:

* after a forward step, **measure whether it moved**;
* if it did not, **turn roughly 90 degrees with counted taps** (9 taps at ~10 degrees) and take a sideways step - which the probe shows covers 38-90 units;
* re-aim on the next call, because the strafe changes both position and facing.

That turns "blocked" from a stall into a detour, using the direction that is provably free.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

old = """    if abs(error) < 35:
        hold(pad, "up", WALK_BURST)
        time.sleep(0.15)
    return math.hypot(tx - x, tz - z)"""
new = """    if abs(error) < 35:
        before = (x, z)
        hold(pad, "up", WALK_BURST)
        time.sleep(0.15)
        after_player = (state(pad).get("player") or {})
        after = (float(after_player.get("x") or 0), float(after_player.get("z") or 0))
        if math.dist(before, after) < 1.5:
            # FORWARD IS BLOCKED. The probe showed the other three directions are wide open (left alone covered 90
            # units), so turn ~90 degrees with counted taps and take a sideways step instead of grinding into it.
            for _ in range(9):
                tap(pad, "left")
                time.sleep(0.1)
            time.sleep(0.15)
            hold(pad, "up", WALK_BURST)
            time.sleep(0.15)
    return math.hypot(tx - x, tz - z)"""

count = text.count(old)
print("steer_to anchor count:", count)
if count != 1:
    raise SystemExit("steer_to body not unique - refusing to guess")
text = text.replace(old, new, 1)
print("steer_to now strafes when forward is blocked")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
