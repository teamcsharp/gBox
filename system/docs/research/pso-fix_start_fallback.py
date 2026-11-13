"""Remove the START fallback from the unstick - it opens the very menu it is trying to clear.

The current fallback, after `b` and every direction has failed:

```python
log("unstick: no direction moved it ... - pressing START and B")
tap(pad, "start")     # <-- this OPENS PSO's pause menu
```

**START toggles the pause menu.** If the character was merely blocked by geometry, pressing START opens a menu, and now it is blocked *and* in a menu - which is how a temporary jam became a permanent
one. `b` is the only cancel in this game.

The replacement: cancel with `b`, then **back off** and **turn then step** - the geometry answer. Strafe attempts alternate sides so a corner on one side does not trap it the same way twice.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

old = """        # nothing physical worked: a menu or a dialogue is the remaining explanation
        log(f"unstick: no direction moved it (attempt {attempt + 1}) - pressing START and B")
        tap(pad, "start")
        time.sleep(0.6)
        tap(pad, "b")
        time.sleep(0.4)
        tap(pad, "a")
        time.sleep(0.4)
    return \"\""""

new = """        # Nothing physical moved it. Cancel any menu - with B only: START *opens* the pause menu, and pressing it
        # here is what turned a temporary jam into a permanent one. Then back off and go round, alternating sides so
        # the same corner cannot trap it twice.
        log(f"unstick: no direction moved it (attempt {attempt + 1}) - cancelling, backing off, going round")
        tap(pad, "b")
        time.sleep(0.5)
        hold(pad, "down", 0.8)
        time.sleep(0.15)
        hold(pad, "left" if attempt % 2 == 0 else "right", 0.5)
        time.sleep(0.15)
        hold(pad, "up", 0.6)
        time.sleep(0.2)
    return \"\""""

count = text.count(old)
print("fallback anchor count:", count)
if count != 1:
    raise SystemExit("unstick fallback anchor not unique")

text = text.replace(old, new, 1)
ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER - the unstick never presses START")
print("START occurrences left in endless.py:", text.count('tap(pad, "start")'))
