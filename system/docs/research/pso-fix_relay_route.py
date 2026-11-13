"""Send the operator's relays through the route that provably reaches the game.

`watch_sdl` currently posts to `/api/sessions/{sid}/input`. That queue is drained by the app's `_pump`, and I measured earlier in this session that presses through it **do not move the
character** - the app's own autoplay reported hundreds of `steps` while the character stood still, whereas `vpad.apply` moved it 211 units through a gate.

The relay runs **inside the worker**, which holds the live adapter in `SESSIONS[sid]`, so it can call the same `vpad.apply` the session input path uses when it works. So: apply directly
to the virtual pad when the adapter is available, and fall back to posting on the queue otherwise. That way the operator's controller reaches the game by the shortest proven path.
"""
import pathlib
import py_compile

PADSTATE = pathlib.Path(r"C:\_tools\gBox\system\gbox\padstate.py")
text = PADSTATE.read_text(encoding="utf-8")
py_compile.compile(str(PADSTATE), doraise=True)
print("padstate.py compiles BEFORE")

old = """            if RELAY.get(sid) and ev and (now or moved):
                # The operator is playing: put their presses on the session's input queue so the bot yields and the
                # game receives them. Sticks only past a real deflection, so resting drift cannot starve the bot.
                try:
                    relay_events = [e for e in ev if not e["key"].endswith(("left", "right", "up", "down"))] or ev
                    for event in relay_events:
                        c.post(f"/api/sessions/{sid}/input", json=event)
                except Exception:                                          # noqa: BLE001
                    pass"""

new = """            if RELAY.get(sid) and ev and (now or moved):
                # The operator is playing. Sticks only past a real deflection, so resting drift cannot starve the bot.
                relay_events = [e for e in ev if not e["key"].endswith(("left", "right", "up", "down"))] or ev
                # Apply straight through the virtual pad when we are in the worker process: that is the route measured
                # to actually move the character (211 units through a gate), while the /input queue is drained by a
                # pump that reports steps without moving it.
                applied = False
                try:
                    from . import tools as _tools
                    adapter = (_tools.SESSIONS or {}).get(sid)
                    vpad = getattr(adapter, "vpad", None)
                    if vpad is not None:
                        vpad.apply(relay_events)
                        applied = True
                except Exception:                                          # noqa: BLE001
                    applied = False
                if not applied:
                    try:
                        for event in relay_events:
                            c.post(f"/api/sessions/{sid}/input", json=event)
                    except Exception:                                      # noqa: BLE001
                        pass"""

count = text.count(old)
print("relay post anchor count:", count)
if count != 1:
    raise SystemExit("relay post block not unique - refusing to guess")
text = text.replace(old, new, 1)

PADSTATE.write_text(text, encoding="utf-8")
py_compile.compile(str(PADSTATE), doraise=True)
print("padstate.py compiles AFTER - SDL relay applies through vpad.apply first")
