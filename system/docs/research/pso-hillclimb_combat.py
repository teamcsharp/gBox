"""Close on an enemy without trusting the heading field.

Five attempts to steer by `heading_deg` have all been defeated by the same thing: the readings are not consistent with the presses. Measured just now, on a calm field with the pad neutral
- `left` 0.15 s gave **+129.6 degrees**, `left` 0.30 s gave **+21.5**, `left` 0.50 s gave **+0.0**, and `right` 0.15 s gave **+145.0** (the wrong sign). Whatever that field holds, it is not
a heading a controller can servo to.

So this does not use it. It **hill-climbs on distance**, the one quantity that is unambiguous:

1. pick the nearest enemy, note the distance;
2. turn one way and step forward;
3. if the distance **fell**, keep turning that way; if it **rose**, turn the other way.

That is control by evidence: the only thing the loop needs to know is whether it is getting closer, and it can measure that every iteration. Once inside the game's attack envelope (12 units) it
cancels any menu with `b` and swings with `a`, and reports the enemy's HP as the proof.
"""
import math
import time

from pso_pad import Pad, call

DIRECTIONS = ("up", "down", "left", "right")
ENVELOPE = 15.5        # the body block holds it at 12-16, and the verified kill landed at d 12.0


def state(pad):
    return call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}


def tap(pad, key):
    pad.send([{"key": key, "down": True}, {"key": key, "down": False}])


def press(pad, key, secs):
    pad.send([{"key": key, "down": True}])
    time.sleep(secs)
    pad.send([{"key": key, "down": False} for key in DIRECTIONS])


def nearest(state_now):
    me = state_now.get("player") or {}
    enemies = [e for e in (state_now.get("entities") or [])
               if str(e.get("kind")) == "enemy" and e.get("hp") is not None and float(e.get("hp")) > 0]
    if not enemies:
        return None, me
    target = min(enemies, key=lambda e: (float(e.get("x") or 0) - float(me.get("x") or 0)) ** 2
                 + (float(e.get("z") or 0) - float(me.get("z") or 0)) ** 2)
    distance = math.hypot(float(target.get("x") or 0) - float(me.get("x") or 0),
                          float(target.get("z") or 0) - float(me.get("z") or 0))
    return (target, distance), me


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)
    best_hp, side, swings = {}, 1, 0

    for step in range(120):
        now = state(pad)
        found, me = nearest(now)
        if not found:
            # nothing here: sweep to find something
            press(pad, "left" if side > 0 else "right", 0.3)
            press(pad, "up", 0.7)
            time.sleep(0.2)
            continue
        target, distance = found
        hp = float(target.get("hp") or 0)
        key = (str(target.get("class")), round(float(target.get("x") or 0)), round(float(target.get("z") or 0)))
        if key in best_hp and hp < best_hp[key]:
            print(f"  *** HIT: {best_hp[key]:.0f} -> {hp:.0f} ***")
        best_hp[key] = hp

        if step % 6 == 0:
            print(f"  {step:3d}: {target.get('class')} hp {hp:5.0f} d {distance:6.1f} side {side:+d} | me hp {me.get('hp')}")

        if distance <= ENVELOPE:
            tap(pad, "b")
            time.sleep(0.12)
            tap(pad, "a")
            swings += 1
            time.sleep(0.45)
            continue

        # hill-climb: turn one way, step, and see whether we got closer
        before = distance
        press(pad, "left" if side > 0 else "right", 0.18)
        press(pad, "up", 0.75)
        time.sleep(0.15)
        found_after, _ = nearest(state(pad))
        after = found_after[1] if found_after else before
        if after > before - 0.5:
            side = -side                       # that way did not help: try the other
        time.sleep(0.1)

    final = state(pad)
    enemies = [e for e in (final.get("entities") or []) if str(e.get("kind")) == "enemy"]
    print("\nswings:", swings, "| remaining:", [(e.get("class"), e.get("hp")) for e in enemies][:4])
