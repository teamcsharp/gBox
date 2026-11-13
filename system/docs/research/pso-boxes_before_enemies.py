"""Boxes are handled before enemies, by a small insert rather than moving code blocks.

Moving the whole box block above the enemy branch risks breaking `play()`'s structure for no benefit. A focused insert does the same job safely: at the top of the enemy branch, if a container is within
reach of a short walk, handle **it** first and `continue`. Everything else keeps its existing order.

The instrumented run proved this is the blocker: **no `box` sample was ever logged**, because every room had a `TObjEneBeast` and the enemy branch ran first - so the bot spent its windows on an
Ultimate-spawned 1556 HP enemy it cannot hurt and never touched the 59 containers.

Boxes are the right target here:
* **destructible at this level** - one broke at heading 58 in the controlled test;
* **they do not fight back**, so the aim cone can be perfected without being thrown 80 units between swings;
* **breaking them is progress**, where swinging at an unkillable beast is not.

And the operator asked for exactly this: *"practice attacking by attacking and destroying the boxes"*.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

old = """        if enemies:
            target = min(enemies, key=lambda e: (float(e.get("x") or 0) - x) ** 2
                         + (float(e.get("z") or 0) - z) ** 2)"""
new = """        # BOXES FIRST. They are destructible at this level and do not fight back, so they are where the attack can
        # be perfected - and the instrumented run showed the box branch never ran because enemies were always present.
        nearby_boxes = [e for e in (now.get("entities") or [])
                        if ("Container" in str(e.get("class")) or "Capsule" in str(e.get("class"))
                            or "Trap" in str(e.get("class")))
                        and e.get("x") is not None and e.get("z") is not None]
        if nearby_boxes:
            box = min(nearby_boxes, key=lambda e: (float(e.get("x") or 0) - x) ** 2
                      + (float(e.get("z") or 0) - z) ** 2)
            bx, bz = float(box.get("x") or 0), float(box.get("z") or 0)
            bdist = math.hypot(bx - x, bz - z)
            if bdist <= 60.0:
                if bdist <= 8.0:
                    for _ in range(3):
                        tap(pad, "b")
                        time.sleep(0.08)
                        tap(pad, "a")
                        time.sleep(0.3)
                    hold(pad, "left" if int(time.time() * 3) % 2 else "right", 0.2)
                    boxes_hit += 1
                else:
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
                        log(f"  box {box.get('class')} d={bdist:.1f} route={'yes' if step else 'no'}")
                moved += 1
                time.sleep(0.1)
                continue

        if enemies:
            target = min(enemies, key=lambda e: (float(e.get("x") or 0) - x) ** 2
                         + (float(e.get("z") or 0) - z) ** 2)"""
count = text.count(old)
print("enemy branch anchor count:", count)
if count != 1:
    raise SystemExit("enemy branch not unique - refusing to guess")
text = text.replace(old, new, 1)
print("boxes are now handled before enemies")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
