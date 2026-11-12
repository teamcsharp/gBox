"""Walk to the warp with tank controls: turn toward the target, then walk forward.

PSO drives like a tank - `left`/`right` rotate the character and `up` walks along its facing - which is why the straight-line walker wandered without converging: it kept
pressing "up" while facing somewhere else. The semantic profile hands over `heading_deg` on every read:

```
"player": {"x": 228.995, "z": 253.999, "heading_deg": 270.0, ...}
```

so the controller is the real one: read the heading, work out the bearing to the warp, turn until aligned, walk, repeat. That is path-guiding from the profile, and it is
what the `explore` mission assumes when it has a field to work with.
"""
import math
import time

from pso_pad import Pad, call

TARGET = (254.0, 25.0)
TOLERANCE = 20.0


def player(pad: Pad) -> dict:
    state = call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST")
    return (state or {}).get("player") or {}


def hold(pad: Pad, key: str, secs: float) -> None:
    pad.send([{"key": key, "down": True}])
    time.sleep(secs)
    pad.send([{"key": key, "down": False}])


def bearing(from_x: float, from_z: float, to_x: float, to_z: float) -> float:
    """Degrees clockwise from north, matching the profile's `heading_deg` convention."""
    return (math.degrees(math.atan2(to_x - from_x, to_z - from_z)) + 360.0) % 360.0


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)
    for step in range(40):
        me = player(pad)
        if not me:
            print("no player")
            break
        x, z = float(me.get("x") or 0.0), float(me.get("z") or 0.0)
        heading = float(me.get("heading_deg") or 0.0)
        want = bearing(x, z, *TARGET)
        error = ((want - heading + 540.0) % 360.0) - 180.0        # -180..180, positive = turn right
        distance = math.hypot(TARGET[0] - x, TARGET[1] - z)
        print(f"  {step:2d}: ({x:7.1f},{z:7.1f}) heading {heading:5.1f} want {want:5.1f} "
              f"err {error:+6.1f} dist {distance:6.1f}")

        if distance <= TOLERANCE:
            print("\nAT THE WARP - pressing A")
            pad.press("a")
            time.sleep(4)
            me = player(pad)
            print("  after A:", (me.get("x"), me.get("z")), "| room", me.get("room"))
            print("  shot:", pad.shot("after_warp_A"))
            break

        if abs(error) > 12:
            key = "right" if error > 0 else "left"
            hold(pad, key, min(0.7, max(0.18, abs(error) / 180.0)))
            time.sleep(0.25)
            continue

        hold(pad, "up", min(1.4, max(0.35, distance / 120.0)))
        time.sleep(0.3)
