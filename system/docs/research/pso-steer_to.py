"""Go straight to a target: turn by counted taps, then walk in measured bursts.

The calibration explains the zigzag completely, and it is not a steering algorithm problem - it is that I had the input model wrong:

```
left 0.15s: +43.4 deg
left 0.30s: +46.2 deg
left 0.45s: +47.7 deg      <- the SAME ~46 degrees whatever the duration
up   0.5s : 9.9 units (20 units/s)
up   1.0s : 0.0 units      <- a long press does not walk at all
```

**A direction press rotates a fixed ~46 degrees, not at a rate.** So `hold(pad, "left", 0.16)` - what every approach in this session used - turned the character a **full 46 degrees every time**. Correcting a 20-degree error overshot it by 26 degrees, next iteration overshot the other way, and the character careened across the room. **That is the zigzag, exactly.**

**And a long forward press does not move**: 0.5 s gives 10 units, 1.0 s gives zero. So walking has to be done in short bursts, not held.

So the approach becomes deterministic instead of heuristic:

* **turn by counted taps**: `round(|error| / 46)` taps of `left` (error > 0) or `right` (error < 0). No rate, no guess;
* **step in 0.5 s bursts** (~10 units each), re-measuring between them so the last step cannot overshoot;
* the **error** comes from `heading_deg`, which *is* reliable here - it is `angle & 0xFFFF` scaled to degrees, and the "erratic" readings earlier were taken during a boss fight where knockback moved the character between samples.

With turns deterministic and steps bounded, the character can point at a target and walk to it in a straight line.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

HELPER = '''
DEG_PER_TAP = 46.0      # measured: a direction press rotates ~46 degrees whatever its duration
WALK_BURST = 0.5        # ~10 units per burst; a longer hold does not walk at all


def steer_to(pad: Pad, tx: float, tz: float) -> float:
    """Turn to face (tx,tz) with counted taps, then take one short step. Returns the remaining distance.

    Taps, not holds: a press is a fixed ~46-degree rotation, so holding over-rotates by a full step every correction
    and the character zigzags. Counting taps makes the facing deterministic.
    """
    me = (state(pad).get("player") or {})
    x, z = float(me.get("x") or 0), float(me.get("z") or 0)
    heading = float(me.get("heading_deg") or 0)
    distance = math.hypot(tx - x, tz - z)
    if distance < 1.0:
        return distance
    want = (math.degrees(math.atan2(tx - x, tz - z)) + 360.0) % 360.0
    error = ((want - heading + 540.0) % 360.0) - 180.0
    taps = int(round(abs(error) / DEG_PER_TAP))
    if taps > 0:
        key = "left" if error > 0 else "right"
        for _ in range(min(taps, 6)):
            tap(pad, key)
            time.sleep(0.12)
        time.sleep(0.2)
        me = (state(pad).get("player") or {})
        x, z = float(me.get("x") or 0), float(me.get("z") or 0)
        heading = float(me.get("heading_deg") or 0)
        want = (math.degrees(math.atan2(tx - x, tz - z)) + 360.0) % 360.0
        error = ((want - heading + 540.0) % 360.0) - 180.0
    if abs(error) < 35:
        hold(pad, "up", WALK_BURST)
        time.sleep(0.15)
    return math.hypot(tx - x, tz - z)


'''

anchor = "def play(pad: Pad, seconds: float = 120.0) -> str:"
if text.count(anchor) != 1:
    raise SystemExit("play anchor count: %d" % text.count(anchor))
if "def steer_to(" not in text:
    text = text.replace(anchor, HELPER.lstrip("\n") + anchor, 1)
    print("steer_to() added")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
