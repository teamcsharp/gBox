"""Press the button at the door. Walking into a gate is not the same as opening it.

The gate branch walks through as soon as it is within 20 units:

```python
if gdist <= 20.0:
    hold(pad, "up", 0.9)          # <- no A press at all
```

But in PSO a door, switch or gate is **activated with A**. That is the operator's complaint in one sentence - *"why is the bot unable to press that button directly in front of him, go through that door"* - and it is almost certainly what has been
happening: the bot reaches the door, does not press the button, and stands there while the gate-seeking considers it done.

So the crossing becomes an explicit sequence, re-checked at each stage:

1. walk until the gate is within ~14 units;
2. **press A** (the action button) and give the game a moment;
3. walk forward to cross;
4. confirm the room changed - if it did, the door worked; if not, press A again.

The confirmation matters as much as the press: "crossed" was being counted as soon as the character was near a gate and pushed forward, which is why one window could report 12 crossings while the room never changed.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

old = """                if gdist <= 20.0:
                    # close enough to cross: walk straight through it, walk_through keeps geometry out of the way
                    hold(pad, "up", 0.9)
                    crossed.append((round(gx / 25.0), round(gz / 25.0)))"""

new = """                if gdist <= 20.0:
                    # A gate is ACTIVATED with A - walking into it does nothing on its own. Press the button, walk
                    # through, and only count a crossing when the room actually changes.
                    room_before = player.get("room")
                    tap(pad, "b")
                    time.sleep(0.12)
                    tap(pad, "a")                                   # the button
                    time.sleep(0.35)
                    hold(pad, "up", 0.9)                            # walk through the opening
                    time.sleep(0.25)
                    after_gate = state(pad).get("player") or {}
                    if after_gate.get("room") != room_before:
                        crossed.append((round(gx / 25.0), round(gz / 25.0)))
                        log(f"  crossed a gate: room {room_before} -> {after_gate.get('room')}")
                    else:
                        tap(pad, "a")                               # maybe a switch rather than a door
                        time.sleep(0.25)
                        hold(pad, "up", 0.7)"""

count = text.count(old)
print("gate-cross anchor count:", count)
if count != 1:
    raise SystemExit("gate-cross block not unique - refusing to guess")
text = text.replace(old, new, 1)

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER - gates are pressed with A and crossings are confirmed by room change")
