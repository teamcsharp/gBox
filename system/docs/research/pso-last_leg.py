"""The last 29 units onto the platform, then A.

The character is at `(361.5, -2.9)`, room 40 - inside x range and 29 units south of the platform at `(360.0, 26.0)`. A short, well-controlled walk north should finish it,
using the measured polarity: `left` increases `heading_deg`, `right` decreases it, and `up` walks along the facing.

Then A at the platform, and the room/position afterwards say whether the warp took.
"""
import math
import time

from pso_pad import Pad, call

TARGET = (360.0, 26.0)


def player(pad):
    state = call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}
    return state.get("player") or {}


def hold(pad, key, secs):
    pad.send([{"key": key, "down": True}])
    time.sleep(secs)
    pad.send([{"key": key, "down": False}])


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)
    for attempt in range(14):
        me = player(pad)
        x, z = float(me.get("x") or 0), float(me.get("z") or 0)
        heading = float(me.get("heading_deg") or 0)
        want = (math.degrees(math.atan2(TARGET[0] - x, TARGET[1] - z)) + 360.0) % 360.0
        error = ((want - heading + 540.0) % 360.0) - 180.0
        distance = math.hypot(TARGET[0] - x, TARGET[1] - z)
        print(f"  {attempt:2d}: ({x:7.1f},{z:7.1f}) heading {heading:5.1f} want {want:5.1f} err {error:+6.1f} dist {distance:5.1f}")
        if distance < 12:
            print("\nON THE PLATFORM - pressing A")
            pad.send([{"key": "a", "down": True}, {"key": "a", "down": False}])
            time.sleep(6)
            me = player(pad)
            print("after A:", (me.get("x"), me.get("z")), "| room", me.get("room"))
            print("shot:", pad.shot("platform_final"))
            break
        if abs(error) > 12:
            hold(pad, "left" if error > 0 else "right", min(0.45, max(0.1, abs(error) / 240.0)))
        else:
            hold(pad, "up", min(0.9, max(0.3, distance / 160.0)))
        time.sleep(0.2)
    else:
        me = player(pad)
        print("\nstopped at", (me.get("x"), me.get("z")), "| room", me.get("room"))
        print("shot:", pad.shot("platform_attempt"))
