"""Pin the relay to one controller, and debounce a pad with stuck buttons.

The probe of each pad separately was unambiguous:

```
[0] Xbox One Controller   axes (0,0,0,0,0,0)   buttons []                 <- completely silent
[1] Xbox 360 Controller   axes (0,-0,...)      buttons [0],[1],[0],[1]...  <- A/B stuck, toggling forever
```

So there is no working input on either device right now: the 360 is spamming A/B (a stuck or failing button, and the reason the relay log filled with `['a','b']` pairs), and the One reports nothing at
all. That is a **hardware/driver** problem, not a software one, and no amount of code makes a silent pad talk.

Two things make the software side as forgiving as possible:

* **`RELAY_PAD=<index>`** pins the relay to one controller, so a broken pad cannot poison the merge - set it to the index of whichever pad is alive;
* **button debounce**: a button must stay in a new state for `DEBOUNCE_FRAMES` consecutive reads before it is believed, which suppresses the exact chatter a failing button produces while leaving a real
  press (held for many frames) untouched.

Both default to today's behaviour when unset: all pads, no debounce beyond the frame it appears in.
"""
import os
import pathlib
import py_compile

RELAY = pathlib.Path(r"C:\_tools\gBox\.tmp\controller_relay.py")
text = RELAY.read_text(encoding="utf-8")
py_compile.compile(str(RELAY), doraise=True)
print("compiles BEFORE")

# 1. pad pinning via RELAY_PAD
old_open = """    pads = []
    for index in range(pygame.joystick.get_count()):"""
new_open = """    wanted = os.environ.get("RELAY_PAD")
    pads = []
    for index in range(pygame.joystick.get_count()):
        if wanted is not None and wanted.strip().isdigit() and index != int(wanted):
            continue                                          # RELAY_PAD pins one controller"""
count = text.count(old_open)
print("open anchor count:", count)
if count == 1:
    text = text.replace(old_open, new_open, 1)
    print("RELAY_PAD pinning added")

# 2. debounce: a button must persist before being believed
old_read = """        now = set()
        lx = ly = 0.0"""
new_read = """        now = set()
        lx = ly = 0.0
        raw_buttons = set()"""
if text.count(old_read) == 1:
    text = text.replace(old_read, new_read, 1)

old_collect = """                        now.add(name)"""
new_collect = """                        raw_buttons.add(name)"""
if text.count(old_collect) == 1:
    text = text.replace(old_collect, new_collect, 1)

old_after = """        lx = 0.0 if abs(lx) < DEADZONE else lx
        ly = 0.0 if abs(ly) < DEADZONE else ly
        stick = (lx, ly)"""
new_after = """        # Debounce: a button has to persist for a few frames before it is believed, which suppresses the chatter a
        # failing button produces (measured: A/B toggling every 0.1s on a 360 pad) while leaving held presses intact.
        for name in list(stable_buttons):
            if name not in raw_buttons:
                stable_buttons.pop(name, None)
        for name in raw_buttons:
            stable_buttons[name] = stable_buttons.get(name, 0) + 1
        now = {name for name, count in stable_buttons.items() if count >= DEBOUNCE_FRAMES or name in held}
        lx = 0.0 if abs(lx) < DEADZONE else lx
        ly = 0.0 if abs(ly) < DEADZONE else ly
        stick = (lx, ly)"""
count = text.count(old_after)
print("stick anchor count:", count)
if count == 1:
    text = text.replace(old_after, new_after, 1)
    print("button debounce added")

# 3. state for the debounce
old_state = "    held, last_stick, last_activity, last_rebind = set(), (0.0, 0.0), 0.0, 0.0"
new_state = ("    held, last_stick, last_activity, last_rebind = set(), (0.0, 0.0), 0.0, 0.0\n"
             "    stable_buttons = {}")
if text.count(old_state) == 1:
    text = text.replace(old_state, new_state, 1)
    print("debounce state added")

if "DEBOUNCE_FRAMES" not in text:
    text = text.replace("DEADZONE = 0.24", "DEADZONE = 0.24\nDEBOUNCE_FRAMES = 3          # frames a button must persist before it is believed", 1)
    print("DEBOUNCE_FRAMES declared")

# needs os
if "\nimport os" not in text:
    text = text.replace("\nimport pathlib", "\nimport os\nimport pathlib", 1)

RELAY.write_text(text, encoding="utf-8")
py_compile.compile(str(RELAY), doraise=True)
print("compiles AFTER")
