"""A liveness watchdog: the character cannot be left standing still.

This is the invariant the operator asked for — *"the bot should never be standing still… always moving, always
progressing"* — and it is the thing the system was missing. Until now, every branch decided for itself whether it was
getting anywhere, and several decided wrongly: one measured case kept the position at **(487,0) for 180 seconds** while
the log repeated the same walking instruction.

The watchdog runs **at the top of every frame, before any branch**, so no work can pre-empt it:

* it records the position and when it last changed by more than 2 units;
* if **20 seconds** pass with no such change, it logs the stall with the position and the elapsed time, then forces
  motion: `unstick` (every direction, then the same-height relocation);
* if that does not move the character either, it takes a **burst of every direction** in turn, which is the one thing
  measured to work when `up` alone is blocked (`up` 0.0 vs `down` 38.4, `left` 37.6, `right` 29.2);
* the timer resets afterwards either way, so the loop can never spin on the watchdog itself.

The state lives at module level so it survives across `play()` windows - a stall that spans two windows is still a stall,
and resetting the clock every window would hide exactly the failures this is meant to catch.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

# 1. module-level state
if "LIVENESS" not in text:
    anchor = "PRESSED_SWITCHES = {}"
    if text.count(anchor) != 1:
        raise SystemExit("PRESSED_SWITCHES anchor count: %d" % text.count(anchor))
    text = text.replace(
        anchor,
        'LIVENESS = {"pos": None, "ts": 0.0, "stalls": 0}   # watchdog: last known position and when it changed\n' + anchor,
        1)
    print("LIVENESS state added")

# 2. the watchdog itself, before read_notes so no branch can run first
OLD = "        # The operator types notes into operator-notes.txt; they are read and acted on every iteration.\n        read_notes(pad)"
NEW = '''        # LIVENESS WATCHDOG - BEFORE EVERY BRANCH. Nothing may leave the character standing still. Measured failure it
        # exists for: the position unchanged at (487,0) for 180 seconds while the log repeated a walking instruction.
        _frame = state(pad).get("player") or {}
        _fx, _fz = float(_frame.get("x") or 0), float(_frame.get("z") or 0)
        if LIVENESS["pos"] is None or math.dist(LIVENESS["pos"], (_fx, _fz)) > 2.0:
            LIVENESS["pos"] = (_fx, _fz)
            LIVENESS["ts"] = time.time()
        elif (time.time() - float(LIVENESS["ts"] or 0)) > 20.0:
            stalled = time.time() - float(LIVENESS["ts"] or 0)
            LIVENESS["stalls"] += 1
            log(f"  WATCHDOG: no movement for {stalled:.0f}s at ({_fx:.0f},{_fz:.0f}) - forcing motion"
                f" (stall #{LIVENESS['stalls']})")
            unstick(pad)
            _after = state(pad).get("player") or {}
            _ax, _az = float(_after.get("x") or 0), float(_after.get("z") or 0)
            if math.dist((_fx, _fz), (_ax, _az)) < 2.0:
                # The unstick did not free it either. Try every direction in turn: when `up` is blocked the other three
                # have been measured to move 29-38 units each, so a burst of all four almost always breaks a wedge.
                log("  WATCHDOG: unstick did not free it - sweeping every direction")
                for _key in ("down", "left", "right", "up"):
                    hold(pad, _key, 0.55)
                    time.sleep(0.15)
                    _now_at = state(pad).get("player") or {}
                    if math.dist((_fx, _fz), (float(_now_at.get("x") or 0), float(_now_at.get("z") or 0))) > 2.0:
                        break
            LIVENESS["pos"] = None            # re-baseline: the next frame records wherever we ended up
            LIVENESS["ts"] = time.time()

        # The operator types notes into operator-notes.txt; they are read and acted on every iteration.
        read_notes(pad)'''
count = text.count(OLD)
print("watchdog anchor count:", count)
if count != 1:
    raise SystemExit("read_notes anchor not unique")
text = text.replace(OLD, NEW, 1)
print("liveness watchdog installed at the top of every frame")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
