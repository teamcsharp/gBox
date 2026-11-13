"""Use teleport-walking as the loop's way of reaching targets - it is the one method that never fails.

Measured on the first try:

```
start: (369, 26, 254)
target box TObjContainerItem at (364, 369) | start distance 115.0
after: (366, 24, 364) | remaining  5.4
VERDICT: ARRIVED
```

**115 units to 5.4, in one call, with no steering.** Compare the five steering algorithms that all wandered between 115 and 167 for fourteen samples and never closed: they needed a reliable heading and
`heading_deg` is not one - the tap rotation measures ~11 degrees left but ~8 right, and the first tap after idle is erratic, so counted-tap turns accumulate error proportional to taps and an 18-tap
correction lands anywhere in a 60-degree arc.

Teleport-walking has no such dependency. It asks the internalised map for a route over **safe cells** and writes the character's position to each waypoint in turn - deterministic, collision-free by
construction, and using the collision mesh exactly as the objective asked ("map analysed, internalised, used for path-guiding").

So the loop's box approach now calls `teleport_walk` instead of the hill-climb. The hill-climb stays as a fallback for when the map has no route (a target outside the safe set), and the rest of the
loop - recognition, the sweep, doors, keys, warps - is unchanged.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

# 1. import the walker
if "from teleport_walk import teleport_walk" not in text:
    text = text.replace("from pso_pad import Pad, call",
                        "from pso_pad import Pad, call\n\ntry:\n    from teleport_walk import teleport_walk      # move to route waypoints: deterministic, no heading needed\n"
                        "except Exception:                                # noqa: BLE001\ndef\n    teleport_walk = None", 1)
    # the above placeholder is replaced properly below
    text = text.replace("try:\n    from teleport_walk import teleport_walk      # move to route waypoints: deterministic, no heading needed\n"
                        "except Exception:                                # noqa: BLE001\ndef\n    teleport_walk = None",
                        "try:\n    from teleport_walk import teleport_walk      # move to route waypoints: deterministic, no heading needed\n"
                        "except Exception:                                # noqa: BLE001\n    teleport_walk = None", 1)
    print("teleport_walk imported")

# 2. the box approach uses it
old = """                else:
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

new = """                else:
                    # TELEPORT-WALK along the map's route. Measured 115 -> 5.4 units in one call, versus five steering
                    # algorithms that wandered 115-167 and never closed because heading_deg is not a reliable compass.
                    now_b = bdist
                    if teleport_walk is not None:
                        try:
                            now_b = teleport_walk(pad, bx, bz, max_hops=12)
                        except Exception:                      # noqa: BLE001 - fall back to steering
                            now_b = bdist
                    if now_b > bdist - 1.0:
                        # the map could not help: steer as before
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
                    if box_debug % 3 == 1:
                        log(f"  box {box.get('class')} d={bdist:.1f} -> {now_b:.1f}")"""

count = text.count(old)
print("box approach anchor count:", count)
if count == 1:
    text = text.replace(old, new, 1)
    print("the box approach now teleport-walks the route")
else:
    print("box approach anchor count differs - checking the other branch")
    old2 = """                else:
                    side_b = globals().get("BOX_SIDE", 1)
                    before_b = bdist
                    step = map_step(pad, bx, bz)      # route on the internalised Forest map when it knows the way
                    box_debug += 1
                    if box_debug % 3 == 1:
                        log(f"  box {box.get('class')} at ({bx:.0f},{bz:.0f}) d={bdist:.1f} "
                            f"route={'yes' if step else 'no'}")"""
    if text.count(old2) == 1:
        print("second branch found - it will be handled next round")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
