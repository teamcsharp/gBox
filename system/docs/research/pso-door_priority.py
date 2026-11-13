"""Once a switch is pressed, stop considering switches until a door has been reached.

The 45-second cooldown only suppressed **the one** switch that was pressed, and this Forest room holds **three** door
keys. So the bot pressed key A, then key B was still eligible and closer, then key C, then key A's cooldown had expired -
a cycle that never reached a door:

```
INTERACT: pressed A on TObjDoorKey at 12.4 units (switch)
INTERACT: walking to TObjDoorKey (switch) 49 -> 13 units
INTERACT: pressed A on TObjDoorKey at 12.8 units (switch)
```

Fix: while **any** switch has been pressed in the last `RECENT_PRESS_S = 60` seconds, switches are **demoted below doors**.
The character has told the level which door it wants opened, so the next thing to do is walk to that door - not find
another switch. After 60 seconds without a press the switches become eligible again, because a floor can legitimately
have several keys and the bot should not ignore a second one forever.

That makes the order dynamic rather than fixed:

* **no recent press** - switch (1) before door (2): find a key and use it;
* **recent press** - door (2) before switch (3): walk through the way that key opened.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

OLD = '''            if idist <= 400.0:
                interact.append((rank, idist, candidate))'''
NEW = '''            if idist <= 400.0:
                # DEMOTE SWITCHES WHILE A DOOR IS WAITING. Only the pressed switch used to be suppressed, so with three
                # door keys the bot cycled between them and never reached the door any of them opened. While a press
                # is recent, doors outrank switches; after the window, switches return to the front.
                recent_press = max(PRESSED_SWITCHES.values()) if PRESSED_SWITCHES else 0.0
                if rank == 1 and (time.time() - recent_press) < 60.0:
                    rank = 3
                interact.append((rank, idist, candidate))'''
count = text.count(OLD)
print("rank append anchor count:", count)
if count != 1:
    raise SystemExit("rank append not unique")
text = text.replace(OLD, NEW, 1)
print("switches are demoted below doors while a press is recent")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
