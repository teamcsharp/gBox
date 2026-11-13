"""The interact walk must free itself when it is blocked.

Measured directly against the live session:

```
up    ->  0.0 units     <- BLOCKED
down  -> 38.4 units
left  -> 37.6 units
right -> 29.2 units
```

The character was wedged against geometry at (487,0) and **the whole loop did nothing for three minutes**: the log
repeated `INTERACT: walking to TLazerFenceSw (switch) 170 -> 194 units` while the position never changed. The operator
saw it as a frozen stream, but the game was running - it simply could not move.

The cause is structural: the interaction block runs **before** the stuck handling and ends in `continue`, so `stuck` never
increments while the bot is trying to reach a switch. The unstick that exists for exactly this case could never fire.

Fix: the interact walk measures its own progress and, when a leg gains less than 2 units, calls `unstick(pad)` itself.
That is the same routine the rest of the loop uses - it tries every direction, then the same-height relocation - so the
behaviour is consistent rather than a second, bespoke recovery.

This is the third fault of the same shape in the interaction path (reachability before ranking, press range vs walk
range, and now recovery), all from the branch being written before the loop's existing safety nets were considered.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

OLD = '''                nowat = state(pad).get("player") or {}
                left = math.hypot(float(ient.get("x") or 0) - float(nowat.get("x") or 0),
                                  float(ient.get("z") or 0) - float(nowat.get("z") or 0))
                log(f"  INTERACT: walking to {iclass} ({kind}) {idist:.0f} -> {left:.0f} units")'''
NEW = '''                nowat = state(pad).get("player") or {}
                left = math.hypot(float(ient.get("x") or 0) - float(nowat.get("x") or 0),
                                  float(ient.get("z") or 0) - float(nowat.get("z") or 0))
                log(f"  INTERACT: walking to {iclass} ({kind}) {idist:.0f} -> {left:.0f} units")
                if idist - left < 2.0:
                    # THE INTERACT BRANCH MUST FREE ITSELF. It runs before the loop's stuck handling and ends in
                    # `continue`, so `stuck` never incremented while the bot was walking to a switch - and a blocked
                    # character then repeated the same line for minutes (measured: three minutes at (487,0), where
                    # `up` moved 0.0 while down/left/right each moved 30+ units).
                    unstick(pad)'''
count = text.count(OLD)
print("interact walk anchor count:", count)
if count != 1:
    raise SystemExit("interact walk progress check not unique - refusing to guess")
text = text.replace(OLD, NEW, 1)
print("the interact walk now frees itself when blocked")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
