"""Attack the way the game's own combat engine does it - inside its published envelope.

`pso_coop_combat` documents the real numbers, which is what every previous attempt was missing:

```
# Owned PMT minimum positive horizontal range is 12; unarmed is 13.
FALLBACK = dict(horizontal=10., vertical=10., horizontal_half_angle=8., vertical_half_angle=20.)

def geometry(player, target, envelope):
    dx, dz = target['x'] - player['x'], target['z'] - player['z']
    distance = math.hypot(dx, dz)
    desired = math.degrees(math.atan2(dx, dz))
    angle = (desired - player['heading_deg'] + 180) % 360 - 180
    ...
```

and its `recovery()` stands off at `min(envelope['horizontal'] * .55, 20.)` - **about 5.5 units**.

So a normal attack needs **distance inside ~10-12 units** and **aim inside an 8 degree cone**. Swinging at 16.6 units while facing 143 degrees away - which is what every previous attempt did - cannot connect
no matter how often it is repeated.

This implements that test directly: close until the distance is inside the envelope, turn until the aim error is inside the cone, then swing, and treat the target's HP as the only evidence
that a hit landed.
"""
import math
import time

from pso_pad import Pad, call

ENVELOPE_HORIZONTAL = 12.0     # PMT minimum positive range
ENVELOPE_ANGLE = 8.0           # horizontal half angle
STAND_OFF = ENVELOPE_HORIZONTAL * 0.55   # what the engine uses: ~6.6 units


def state(pad):
    return call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}


def geometry(player, target):
    dx, dz = float(target.get("x") or 0) - float(player.get("x") or 0), float(target.get("z") or 0) - float(player.get("z") or 0)
    distance = math.hypot(dx, dz)
    desired = math.degrees(math.atan2(dx, dz))
    angle = (desired - float(player.get("heading_deg") or 0) + 180) % 360 - 180
    return distance, angle


def hold(pad, key, secs):
    pad.send([{"key": key, "down": True}])
    time.sleep(secs)
    pad.send([{"key": key, "down": False}])


def tap(pad, key):
    pad.send([{"key": key, "down": True}, {"key": key, "down": False}])


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)
    last_hp = {}
    hits = 0

    for step in range(80):
        now = state(pad)
        me = now.get("player") or {}
        if not me:
            print("no player")
            break
        enemies = [e for e in (now.get("entities") or [])
                   if str(e.get("kind")) == "enemy" and e.get("hp") is not None and float(e.get("hp")) > 0]
        if not enemies:
            print(f"\nALL ENEMIES DEAD - {hits} hits landed")
            break

        target = min(enemies, key=lambda e: (float(e.get("x") or 0) - float(me.get("x") or 0)) ** 2
                     + (float(e.get("z") or 0) - float(me.get("z") or 0)) ** 2)
        distance, angle = geometry(me, target)
        hp = float(target.get("hp") or 0)
        key_id = round(float(target.get("x") or 0)), round(float(target.get("z") or 0))
        if key_id in last_hp and hp < last_hp[key_id]:
            hits += 1
            print(f"  *** HIT {hits}: {last_hp[key_id]:.0f} -> {hp:.0f} ***")
        last_hp[key_id] = hp

        in_range = distance <= ENVELOPE_HORIZONTAL
        in_cone = abs(angle) <= ENVELOPE_ANGLE
        print(f"  {step:2d}: {target.get('class')} hp {hp:5.0f} d {distance:6.2f} aim {angle:+7.1f} "
              f"| range {'Y' if in_range else 'n'} cone {'Y' if in_cone else 'n'} | me hp {me.get('hp')}")

        if not in_cone:
            # the cone is 8 degrees, so turn in small measured steps toward it
            hold(pad, "left" if angle > 0 else "right", min(0.22, max(0.06, abs(angle) / 400.0)))
        elif not in_range:
            hold(pad, "up", min(0.5, max(0.2, (distance - STAND_OFF) / 120.0)))
        else:
            tap(pad, "a")
            time.sleep(0.22)
            tap(pad, "a")
            time.sleep(0.22)
        time.sleep(0.08)

    final = state(pad)
    enemies = [e for e in (final.get("entities") or []) if str(e.get("kind")) == "enemy"]
    print("\nremaining:", [(e.get("class"), e.get("hp")) for e in enemies][:4])
    print("hits landed:", hits)
    print("shot:", pad.shot("exact_combat"))
