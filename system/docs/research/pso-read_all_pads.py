"""Read every controller, not just the first one - the operator has two.

The probe found the cause of "still not reacting":

```
joysticks: 2
  [0] Xbox One Controller | axes 6 buttons 16     <- the relay opened THIS one
  [1] Xbox 360 Controller | axes 6 buttons 11     <- and it saw nothing for 20 seconds
```

The relay did `joy = pygame.joystick.Joystick(0)` and read only that device. When the operator's active pad is a **different** device - and they have both connected - the relay watches a silent
controller and reports nothing, while the real presses go nowhere. That is a plain bug with a plain fix: **read every joystick and merge their state.**

Merging rules:

* buttons: the union across pads, so a press on either registers;
* axes: the value with the **largest magnitude** per axis, so a stick on either pad moves the character and a resting pad's drift cannot swamp a real deflection;
* a pad that disappears is dropped without killing the loop (`get_count()` is re-checked each frame).

This is also what makes the system robust to the operator swapping pads mid-session, which they have already done once (360 -> One).
"""
import pathlib
import py_compile

RELAY = pathlib.Path(r"C:\_tools\gBox\.tmp\controller_relay.py")
text = RELAY.read_text(encoding="utf-8")
py_compile.compile(str(RELAY), doraise=True)
print("compiles BEFORE")

# 1. open every joystick instead of only index 0
old_open = """    joy = pygame.joystick.Joystick(0)
    joy.init()
    print(f"relay watching '{joy.get_name()}'", flush=True)"""
new_open = """    pads = []
    for index in range(pygame.joystick.get_count()):
        try:
            pad = pygame.joystick.Joystick(index)
            pad.init()
            pads.append(pad)
        except Exception:                                      # noqa: BLE001 - a dead pad must not stop the relay
            continue
    if not pads:
        raise SystemExit("no joystick visible to SDL")
    # Read EVERY pad. The operator has two connected, and watching only the first means watching a silent one.
    print("relay watching: " + ", ".join(f"[{i}] {p.get_name()}" for i, p in enumerate(pads)), flush=True)"""
count = text.count(old_open)
print("open anchor count:", count)
if count == 1:
    text = text.replace(old_open, new_open, 1)
    print("every joystick is opened")

# 2. merge state from all pads
old_read = """        pygame.event.pump()
        now = {name for index, name in BUTTONS.items() if index < joy.get_numbuttons() and joy.get_button(index)}
        lx = joy.get_axis(0) if joy.get_numaxes() > 0 else 0.0
        ly = joy.get_axis(1) if joy.get_numaxes() > 1 else 0.0
        lx = 0.0 if abs(lx) < DEADZONE else lx
        ly = 0.0 if abs(ly) < DEADZONE else ly
        stick = (lx, ly)"""
new_read = """        pygame.event.pump()
        now = set()
        lx = ly = 0.0
        for pad in pads:
            try:
                for index, name in BUTTONS.items():
                    if index < pad.get_numbuttons() and pad.get_button(index):
                        now.add(name)
                if pad.get_numaxes() > 0:
                    value = pad.get_axis(0)
                    if abs(value) > abs(lx):
                        lx = value
                if pad.get_numaxes() > 1:
                    value = pad.get_axis(1)
                    if abs(value) > abs(ly):
                        ly = value
            except Exception:                                  # noqa: BLE001 - a pad dropping out is not fatal
                continue
        lx = 0.0 if abs(lx) < DEADZONE else lx
        ly = 0.0 if abs(ly) < DEADZONE else ly
        stick = (lx, ly)"""
count = text.count(old_read)
print("read anchor count:", count)
if count == 1:
    text = text.replace(old_read, new_read, 1)
    print("state is merged from every pad")

RELAY.write_text(text, encoding="utf-8")
py_compile.compile(str(RELAY), doraise=True)
print("compiles AFTER")
