"""Kill an enemy by actually closing to melee range first.

The reason no hit ever landed is now clear from the numbers: `always_hit` is enabled, and its own scope says *"targets must still be in range and hittable"* - but the fight log
showed the enemy at **226-275 units** while A was being pressed. Melee reach in PSO is a few tens of units, so every swing was into empty air, and the enemy's HP stayed at 60
for 24 rounds.

So this closes the distance first - repeatedly, checking the range every step - and only swings when the target is genuinely near. `walk_through` is on, so geometry no longer
stops the approach.
"""
import math
import time

from pso_pad import Pad, call

MELEE = 45.0          # swing inside this
CLOSE = 30.0          # comfortably inside


def state(pad):
    return call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}


def bearing(fx, fz, tx, tz):
    return (math.degrees(math.atan2(tx - fx, tz - fz)) + 360.0) % 360.0


def hold(pad, key, secs):
    pad.send([{"key": key, "down": True}])
    time.sleep(secs)
    pad.send([{"key": key, "down": False}])


def tap(pad, key):
    pad.send([{"key": key, "down": True}, {"key": key, "down": False}])


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)

    for round_index in range(40):
        now = state(pad)
        player = now.get("player") or {}
        if not player:
            print("no player")
            break
        x, z = float(player.get("x") or 0), float(player.get("z") or 0)
        heading = float(player.get("heading_deg") or 0)
        enemies = [e for e in (now.get("entities") or [])
                   if str(e.get("kind")) == "enemy" and e.get("hp") is not None and float(e.get("hp")) > 0]
        if not enemies:
            print("all enemies dead")
            break
        target = min(enemies, key=lambda e: (float(e.get("x") or 0) - x) ** 2 + (float(e.get("z") or 0) - z) ** 2)
        tx, tz = float(target.get("x") or 0), float(target.get("z") or 0)
        distance = math.hypot(tx - x, tz - z)
        want = bearing(x, z, tx, tz)
        error = ((want - heading + 540.0) % 360.0) - 180.0
        print(f"  {round_index:2d}: {target.get('class')} hp {target.get('hp')} dist {distance:6.1f} "
              f"| me ({x:7.1f},{z:7.1f}) err {error:+6.1f}")

        if distance > MELEE:
            if abs(error) > 25:
                hold(pad, "left" if error > 0 else "right", min(0.35, max(0.1, abs(error) / 260.0)))
            else:
                hold(pad, "up", min(1.0, max(0.3, distance / 300.0)))
        else:
            if abs(error) > 25:
                hold(pad, "left" if error > 0 else "right", 0.18)
            tap(pad, "a")
            time.sleep(0.25)
            tap(pad, "a")
        time.sleep(0.2)

    final = state(pad)
    enemies = [e for e in (final.get("entities") or []) if str(e.get("kind")) == "enemy"]
    print("\nenemies remaining:", [(e.get("class"), e.get("hp")) for e in enemies][:6])
    print("shot:", pad.shot("combat_range"))
