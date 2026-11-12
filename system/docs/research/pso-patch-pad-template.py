"""Make every launch bind controller port 1 to the bot's virtual pad, which needs no focus.

Measured on the running session:

```
C:\\...\\Dolphin-x64\\User\\Config\\GCPadNew.ini:
  Device = XInput/0/Gamepad          <- slot 0, a controller that may not exist
  Device = DInput/0/Keyboard Mouse
```

`_setup_vpad` fell back to the template again (no gBox virtual-pad comment), and the template binds **XInput slot 0**. Meanwhile the plane's own documentation
is explicit that a virtual pad is the one input path that needs no focus: *"Dolphin's XInput backend polls it every frame with
`Dolphin.Input.BackgroundInput=True` whether or not the window is focused."*

Two changes make every launch use the bot's pad:

1. **`PAD_INI_WIN`** (the template the launch writes) binds GCPad1 to **`XInput/2/Gamepad`** - the slot the bot's pad lands on, because slots 0 and 1 are the
   operator's two controllers.
2. **`_want_vpad` returns False**, so the app does not create a competing pad and overwrite the binding with its own slot. The bot owns the pad; the app
   just points the emulator at it.

Order matters: the bot creates its pad **first** (so slot 2 is occupied by it), then the launch writes `XInput/2` and the emulator polls a pad that exists. That
is what lets an agent-owned session be driven at all - no window, no focus, no keyboard.
"""
import pathlib
import re

adapters = pathlib.Path(r"C:\_tools\gBox\system\gbox\adapters.py")
text = adapters.read_text(encoding="utf-8")

# 1. the template the launch writes
start = text.find('PAD_INI_WIN = """[GCPad1]')
if start < 0:
    raise SystemExit("PAD_INI_WIN not found")
window = text[start:start + 600]
print("--- current template head ---")
print(window[:260])

device_match = re.search(r"(PAD_INI_WIN = \"\"\"\[GCPad1\]\nDevice = )([^\n]+)", text)
if not device_match:
    raise SystemExit("GCPad1 Device line not found in PAD_INI_WIN")
print("current device:", device_match.group(2))

if device_match.group(2).strip() == "XInput/2/Gamepad":
    print("template already binds slot 2")
else:
    text = text[:device_match.start(2)] + "XInput/2/Gamepad" + text[device_match.end(2):]
    print("template now binds XInput/2/Gamepad")

# 2. do not let the app create a competing pad
old_want = """        from . import vpad_win
        return vpad_win.available()"""
new_want = """        return False   # the bot owns the virtual pad (XInput/2); the template points the emulator at it"""
if text.count(old_want) == 1:
    text = text.replace(old_want, new_want, 1)
    print("_want_vpad now returns False so the template binding survives")
else:
    print("_want_vpad pattern count", text.count(old_want))

adapters.write_text(text, encoding="utf-8")
print("done")
