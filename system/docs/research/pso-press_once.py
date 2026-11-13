"""Press each switch once, then move on.

The log showed the same key being pressed indefinitely:

```
INTERACT: pressed A on TObjDoorKey at 13.0 units (switch)
INTERACT: pressed A on TObjDoorKey at 13.0 units (switch)
INTERACT: pressed A on TObjDoorKey at 13.0 units (switch)
```

The entity stays in RAM after it is activated - PSO keeps the object and flips its stage flag - so a selection rule based
on "the nearest reachable switch" keeps choosing the one already done and the bot never looks at the door it just
unlocked. That is the same class of mistake as ranking by class without checking reachability: the choice is made from
the object list alone, with no memory of what has already been tried.

Fix: remember each switch by its pointer with a timestamp, and **skip any switch pressed in the last
`PRESSED_FORGET_S = 45` seconds**. After that it may be considered again, because a switch can legitimately need a second
press (a key that resets when its door closes), so this is a cooldown rather than a permanent block.

With the switch out of the running, the next priority becomes what the level actually wants: the door that just opened,
or the teleporter beyond it.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

# 1. the cooldown map at module scope
if "PRESSED_SWITCHES" not in text:
    anchor = "TRIVIAL_HP = 40"
    if text.count(anchor) != 1:
        raise SystemExit("TRIVIAL_HP anchor count: %d" % text.count(anchor))
    text = text.replace(
        anchor,
        "PRESSED_SWITCHES = {}      # switch pointer -> when it was pressed, so each is pressed once then left alone\n" + anchor,
        1)
    print("PRESSED_SWITCHES added")

# 2. skip switches on cooldown when choosing, and record a press
OLD_SELECT = '''            if idist <= 25.0:'''
NEW_SELECT = '''            if idist <= 25.0 and rank == 1:
                already = PRESSED_SWITCHES.get(str(ient.get("ptr")))
                if already and (time.time() - already) < 45.0:
                    continue                          # this switch was just pressed; look at the door instead
            if idist <= 25.0:'''
count = text.count(OLD_SELECT)
print("press anchor count:", count)
if count == 1:
    text = text.replace(OLD_SELECT, NEW_SELECT, 1)
    print("switches on cooldown are skipped")

OLD_RECORD = '''                for _ in range(3):
                    tap(pad, "a")
                    time.sleep(0.35)'''
NEW_RECORD = '''                for _ in range(3):
                    tap(pad, "a")
                    time.sleep(0.35)
                if rank == 1:
                    PRESSED_SWITCHES[str(ient.get("ptr"))] = time.time()'''
count = text.count(OLD_RECORD)
print("record anchor count:", count)
if count == 1:
    text = text.replace(OLD_RECORD, NEW_RECORD, 1)
    print("a press is recorded so it is not repeated")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
