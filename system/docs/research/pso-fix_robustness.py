"""Robustness: a menu is the first suspect for "stuck", and a body block needs a strafe, not a turn.

Two failures from the last round, both now understood:

1. **A pause menu eats everything.** PSO's pause menu is opened by START (which *toggles* it), and while it is open the character cannot move and A does menu things. Every "frozen" episode
   was either this or a blocked direction, and from the position alone they are indistinguishable. So the unstick now presses **B first** - the cancel button - before spending effort on
   directions.

2. **An enemy body is not a wall.** The character stopped at ~16.7 units because the enemy's own collision blocks it, and turning alone cannot fix that: the answer is to step **back**
   (`down`), then move **sideways** (`left`/`right` are turns, so the strafe is a turn plus a forward step), which changes the approach angle around the body.

Both go in `play()` and `unstick()`, so the loop stops relying on a single direction being free.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

# ---- 1. unstick: cancel any menu before spending effort on directions -------------------------------------------
old_unstick = """    for attempt in range(attempts):
        for key in ("up", "left", "right", "down", "left", "right"):"""
new_unstick = """    for attempt in range(attempts):
        # A pause menu looks exactly like a blocked direction from the position alone, and it is the more common
        # cause - it was what froze the character twice. Cancel it before testing directions.
        tap(pad, "b")
        time.sleep(0.25)
        for key in ("up", "left", "right", "down", "left", "right"):"""
if text.count(old_unstick) != 1:
    raise SystemExit("unstick anchor count: %d" % text.count(old_unstick))
text = text.replace(old_unstick, new_unstick, 1)
print("unstick now cancels a menu first")

# ---- 2. play: when the approach is blocked, back off and strafe ---------------------------------------------------
old_approach = """            elif distance > 12:
                hold(pad, "up", min(0.55, max(0.2, (distance - 8) / 160.0)))
                moved += 1"""
new_approach = """            elif distance > 12:
                before_move = state(pad).get("player") or {}
                start = (float(before_move.get("x") or 0), float(before_move.get("z") or 0))
                hold(pad, "up", min(0.55, max(0.2, (distance - 8) / 160.0)))
                after_move = state(pad).get("player") or {}
                end = (float(after_move.get("x") or 0), float(after_move.get("z") or 0))
                if math.dist(start, end) < 1.0:
                    # an enemy body blocks the approach, and it is not a wall: step back, then go round it
                    log("  approach blocked - backing off and strafing around the body")
                    hold(pad, "down", 0.4)
                    hold(pad, "left" if int(time.time()) % 2 else "right", 0.45)
                    hold(pad, "up", 0.5)
                moved += 1"""
if text.count(old_approach) != 1:
    raise SystemExit("approach anchor count: %d" % text.count(old_approach))
text = text.replace(old_approach, new_approach, 1)
print("play now backs off and strafes when the approach is blocked")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
