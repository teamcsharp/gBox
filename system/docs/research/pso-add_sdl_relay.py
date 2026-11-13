"""Relay the operator's controller when it is a HID/SDL pad that XInput cannot see.

Measured on this machine:

* XInput slots: **slot 0 = gBox's virtual pad, slots 1-3 absent** - so `operator_slot()` finds nothing and `watch_xinput`
  logs *"no operator pad to mirror"* and returns. That is why the operator's controller never reaches the game.
* Windows devices: an **Xbox 360 controller** (`HID\\VID_045E&PID_028E`) and a **DualSense** (`VID_054C&PID_0CE6`), both
  enumerated as **HID**, not XInput.
* SDL: **exactly one joystick - "Xbox 360 Controller", 6 axes, 11 buttons.**

So the pad is present and readable, just not through the API the mirror was written against. `watch_sdl` reads it with
pygame and feeds the **same** relay path as `watch_xinput`: the same key names, the same `pad_lease` takeover signal,
and the same `/api/sessions/{sid}/input` post when `RELAY` is on. The A/B swap matches `_XI` exactly (`0x1000` is "b"
and `0x2000` is "a"), because RetroPad's convention is the one the rest of gBox already speaks.
"""
import pathlib
import py_compile

PADSTATE = pathlib.Path(r"C:\_tools\gBox\system\gbox\padstate.py")
text = PADSTATE.read_text(encoding="utf-8")
py_compile.compile(str(PADSTATE), doraise=True)
print("padstate.py compiles BEFORE")

if "def watch_sdl(" in text:
    print("watch_sdl already present")
else:
    WATCHER = '''

def watch_sdl(server: str, headers: dict, sid: str, alive) -> None:
    """Mirror the operator's SDL/HID controller into the session, the way watch_xinput does for real XInput pads.

    An Xbox 360 pad that enumerates as HID (measured on this PC) never answers XInputGetState, so the XInput mirror
    finds no operator pad at all. SDL does see it, and this reads the same state from there: buttons by index, the
    left stick for movement, the triggers for L2/R2, then the identical relay logic.
    """
    try:
        import pygame
    except ImportError:
        print("padstate: pygame/SDL not available - cannot mirror a HID controller", flush=True)
        return
    import httpx

    pygame.init()
    pygame.joystick.init()
    if pygame.joystick.get_count() <= 0:
        print("padstate: SDL reports no joystick - nothing to mirror", flush=True)
        return
    joy = pygame.joystick.Joystick(0)
    joy.init()
    print(f"padstate: mirroring the operator's SDL pad '{joy.get_name()}' "
          f"({joy.get_numaxes()} axes, {joy.get_numbuttons()} buttons)", flush=True)

    # SDL button index -> gBox key name. The A/B swap mirrors _XI: XInput 0x1000 ("A") is "b" here and 0x2000 is "a".
    BUTTONS = {0: "b", 1: "a", 2: "y", 3: "x", 4: "l", 5: "r", 6: "select", 7: "start", 8: "l3", 9: "r3"}
    held, last_stick, chording, last_active = set(), (0.0, 0.0, 0.0, 0.0), False, 0.0

    with httpx.Client(base_url=server, headers=headers, timeout=3) as c:
        while alive():
            time.sleep(1 / 30)
            try:
                pygame.event.pump()
            except Exception:                                              # noqa: BLE001 - never kill the mirror
                continue
            now = {name for index, name in BUTTONS.items() if index < joy.get_numbuttons() and joy.get_button(index)}
            if joy.get_numaxes() > 4 and joy.get_axis(4) > 0.5:            # left trigger
                now.add("l2")
            if joy.get_numaxes() > 5 and joy.get_axis(5) > 0.5:            # right trigger
                now.add("r2")

            def axis(index):
                value = joy.get_axis(index) if index < joy.get_numaxes() else 0.0
                return 0.0 if abs(value) < 0.24 else max(-1.0, min(1.0, value))   # same deadzone idea as the XInput path

            stick = (axis(0), -axis(1), axis(2) if joy.get_numaxes() > 2 else 0.0,
                     -axis(3) if joy.get_numaxes() > 3 else 0.0)
            if not now and stick == last_stick:
                continue
            ev = [{"key": k, "down": True} for k in now - held] + [{"key": k, "down": False} for k in held - now]
            before, held, last_stick = held, now, stick
            moved = any(abs(v) > 0.3 for v in stick)
            fire, chording = chord_step(sid, before, now, moved, chording)
            if not chording:
                pad_lease(sid, now | stick_keys(stick))
            if fire and CHORD.get(sid):
                threading.Thread(target=CHORD[sid], daemon=True).start()
            if now or moved:
                t = time.time()
                if t - last_active >= 0.7 and not chording and ANCHOR.get(sid):
                    threading.Thread(target=ANCHOR[sid], args=(t,), daemon=True).start()
                last_active = t
            if RELAY.get(sid) and ev and (now or moved):
                # The operator is playing: put their presses on the session's input queue so the bot yields and the
                # game receives them. Sticks only past a real deflection, so resting drift cannot starve the bot.
                try:
                    relay_events = [e for e in ev if not e["key"].endswith(("left", "right", "up", "down"))] or ev
                    for event in relay_events:
                        c.post(f"/api/sessions/{sid}/input", json=event)
                except Exception:                                          # noqa: BLE001
                    pass
'''
    anchor = "\ndef watch_xinput("
    if text.count(anchor) != 1:
        raise SystemExit("watch_xinput anchor count: %d" % text.count(anchor))
    text = text.replace(anchor, WATCHER + "\ndef watch_xinput(", 1)
    print("watch_sdl added to padstate.py")

PADSTATE.write_text(text, encoding="utf-8")
py_compile.compile(str(PADSTATE), doraise=True)
print("padstate.py compiles AFTER")
