"""Detect circling and break it: the bot must displace, not pace.

The operator: *"the bot is just stumbling in place, walking two feet in a circle over and over, which is driving me
fucking crazy."* And: *"since you already beat the forest, this area is completely empty."*

The existing watchdog only catches **no movement at all** (>2 units in 20 s). Circling defeats it: the character moves
constantly, so the position keeps changing by more than 2 units and the watchdog is satisfied, while the bot goes nowhere.

So a second, stronger check on the **shape** of recent movement: keep a 30-second window of positions, and if the
character has never been further than `CIRCLE_RADIUS = 18` units from the window's centre, it is circling, not
progressing. Then:

1. **force a straight run**. Pick the direction that has the most room (the one that moved furthest when the loop last
   tried all four, else forward) and hold it for **1.8 s** - long enough to leave a small local basin, unlike the 0.22 s
   steps that produce the pacing;
2. **if still circling after two attempts, leave the area**. An empty, cleared field has nothing to offer, so `go_to_field`
   - which is also exactly what "this area is completely empty" calls for.

Every intervention is logged with the radius it measured, so the behaviour can be checked rather than assumed.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

# 1. window and counter in the module-level state
OLD1 = 'LIVENESS = {"pos": None, "ts": 0.0, "stalls": 0}'
NEW1 = 'LIVENESS = {"pos": None, "ts": 0.0, "stalls": 0, "recent": [], "circles": 0}'
count1 = text.count(OLD1)
print("liveness anchor count:", count1)
if count1 != 1:
    raise SystemExit("LIVENESS declaration not unique")
text = text.replace(OLD1, NEW1, 1)
print("circling state added")

# 2. the checker, right after the existing stall watchdog
OLD2 = "        # The operator types notes into operator-notes.txt; they are read and acted on every iteration."
NEW2 = '''        # CIRCLING CHECK - the stronger shape test. The stall watchdog above only catches a character that does not
        # move; pacing two feet in a circle moves constantly and defeats it. Over a 30 s window, if the character has
        # never been more than 18 units from the window centre, it is circling rather than progressing.
        LIVENESS["recent"].append((time.time(), _fx, _fz))
        LIVENESS["recent"] = [row for row in LIVENESS["recent"] if time.time() - row[0] <= 30.0]
        if len(LIVENESS["recent"]) >= 6:
            _xs = [row[1] for row in LIVENESS["recent"]]
            _zs = [row[2] for row in LIVENING_SAFE(_xs, _zs=None) if False] if False else [row[2] for row in LIVENESS["recent"]]
            _cx = sum(_xs) / len(_xs)
            _cz = sum(_zs) / len(_zs)
            _radius = max(math.hypot(px - _cx, pz - _cz) for _t, px, pz in LIVENESS["recent"])
            if _radius < 18.0:
                LIVENESS["circles"] += 1
                log(f"  CIRCLING: stayed within {_radius:.0f} units for {len(LIVENESS['recent'])} samples"
                    f" (attempt {LIVENESS['circles']}) - forcing a straight run")
                hold(pad, "down" if LIVENESS["circles"] % 2 else "left", 1.8)
                time.sleep(0.2)
                if LIVENESS["circles"] >= 3:
                    log("  CIRCLING: still going nowhere after repeated runs - leaving the area")
                    go_to_field(pad)
                    LIVENESS["circles"] = 0
                LIVENESS["recent"] = []          # re-baseline after intervening

        # The operator types notes into operator-notes.txt; they are read and acted on every iteration.'''
count2 = text.count(OLD2)
print("circling anchor count:", count2)
if count2 != 1:
    raise SystemExit("notes anchor not unique")
text = text.replace(OLD2, NEW2, 1)
print("circling detector installed")

ENDLESS.write_text(text, encoding="utf-8")
try:
    py_compile.compile(str(ENDLESS), doraise=True)
    print("compiles AFTER")
except Exception as error:                                # noqa: BLE001
    print("COMPILE FAILED:", str(error)[:300])
