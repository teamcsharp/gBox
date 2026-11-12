"""Calibrate what each key does to heading and position, so the walker turns the right way.

The corridor walker drove the character **south to z -316** while aiming at the platform at z +26, which means its turn direction is wrong: it presses `right` to reduce a
positive heading error, and if `right` actually *decreases* `heading_deg` the character turns away and walks off.

This measures it directly: read `heading_deg`, hold a key, read again, and report the sign of the change for `left` and `right`, and the position delta for `up`.
"""
import time

from pso_pad import Pad, call


def me(pad: Pad) -> dict:
    state = call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}
    return state.get("player") or {}


def hold(pad: Pad, key: str, secs: float) -> None:
    pad.send([{"key": key, "down": True}])
    time.sleep(secs)
    pad.send([{"key": key, "down": False}])


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)
    start = me(pad)
    print("start: x %s z %s heading %s room %s"
          % (start.get("x"), start.get("z"), start.get("heading_deg"), start.get("room")))

    for key in ("right", "left"):
        before = me(pad)
        hold(pad, key, 0.5)
        time.sleep(0.6)
        after = me(pad)
        dh = (float(after.get("heading_deg") or 0) - float(before.get("heading_deg") or 0) + 540) % 360 - 180
        print(f"  {key:5s}: heading {before.get('heading_deg')} -> {after.get('heading_deg')} | delta {dh:+.1f} "
              f"| pos ({before.get('x')},{before.get('z')}) -> ({after.get('x')},{after.get('z')})")

    before = me(pad)
    hold(pad, "up", 0.7)
    time.sleep(0.6)
    after = me(pad)
    dx = float(after.get("x") or 0) - float(before.get("x") or 0)
    dz = float(after.get("z") or 0) - float(before.get("z") or 0)
    print(f"  up   : heading {before.get('heading_deg')} | delta ({dx:+.1f},{dz:+.1f}) "
          f"| expected along heading {before.get('heading_deg')}")
