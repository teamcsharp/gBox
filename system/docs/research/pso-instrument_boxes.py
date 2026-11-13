"""Instrument the box approach: is the route failing, or the hill-climb?

The box path now has the right sweep and the right range, and the bot still destroys nothing because it never arrives. Two candidates remain and they need different fixes:

* **`map_step()` returns `None`** - the box is outside the internalised map's safe set, or the character is off it, so the route cannot help and the fallback runs;
* **the fallback hill-climb oscillates** - it turns one way, the distance does not improve, it flips, and the character rocks in place.

Logging both every iteration distinguishes them at a glance: `route=yes/no` plus `bdist` shows whether the distance is falling when a route exists, and whether it stalls when it does not.

Boxes are logged by class and position so it is clear which one is being chased, and the chase is capped so a stuck one can be abandoned rather than consuming the whole window.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

old = """                else:
                    side_b = globals().get("BOX_SIDE", 1)
                    before_b = bdist
                    step = map_step(pad, bx, bz)      # route on the internalised Forest map when it knows the way"""
new = """                else:
                    side_b = globals().get("BOX_SIDE", 1)
                    before_b = bdist
                    step = map_step(pad, bx, bz)      # route on the internalised Forest map when it knows the way
                    box_debug += 1
                    if box_debug % 3 == 1:
                        log(f"  box {box.get('class')} at ({bx:.0f},{bz:.0f}) d={bdist:.1f} "
                            f"route={'yes' if step else 'no'}")"""
count = text.count(old)
print("box approach anchor count:", count)
if count != 1:
    raise SystemExit("box approach not unique")
text = text.replace(old, new, 1)
print("box approach instrumented")

old_decl = "    map_steps = 0                                       # steps chosen from the internalised Forest map"
new_decl = ("    map_steps = 0                                       # steps chosen from the internalised Forest map\n"
            "    box_debug = 0                                       # box-approach samples logged")
if text.count(old_decl) == 1:
    text = text.replace(old_decl, new_decl, 1)
    print("box_debug counter declared")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
