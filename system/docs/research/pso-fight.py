"""Kill the nearest enemy - the thing "progressing" actually requires in PSO.

In a PSO cave the progression chain is: **kill enemies -> they drop the key -> the key opens `TODoorCave02` -> the next area**. The bot has 709 autoplay steps and zero kills,
so it is travelling without fighting, and without kills it can never open a door.

The semantic profile makes the fight measurable: every enemy is an entity with `kind: "enemy"`, a `class` (here `TObjEneShark`), a position and **`hp`** - so a swing can be
verified by the enemy's HP dropping rather than by hoping.

This turns to the nearest enemy, closes to melee range, and swings with A (the attack button while a weapon is drawn - the sabre is out), watching that enemy's HP each swing.
"""
import math
import time

from pso_pad import Pad, call


def state(pad):
    return call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}


def me(state_now) -> dict:
    return state_now.get("player") or {}


def enemies(state_now) -> list:
    return [e for e in (state_now.get("entities") or [])
            if str(e.get("kind")) == "enemy" and e.get("hp") is not None]


def bearing(fx, fz, tx, tz) -> float:
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

    for round_index in range(24):
        now = state(pad)
        player = me(now)
        if not player:
            print("no player")
            break
        x, z = float(player.get("x") or 0), float(player.get("z") or 0)
        living = enemies(now)
        if not living:
            print("no enemies left in the room")
            break

        target = min(living, key=lambda e: (float(e.get("x") or 0) - x) ** 2 + (float(e.get("z") or 0) - z) ** 2)
        tx, tz = float(target.get("x") or 0), float(target.get("z") or 0)
        distance = math.hypot(tx - x, tz - z)
        want = bearing(x, z, tx, tz)
        error = ((want - float(player.get("heading_deg") or 0) + 540.0) % 360.0) - 180.0
        print(f"  {round_index:2d}: {target.get('class')} hp {target.get('hp')} at {distance:5.1f} "
              f"| me ({x:7.1f},{z:7.1f}) heading err {error:+6.1f}")

        if target.get("hp") is not None and float(target.get("hp")) <= 0:
            print("  TARGET IS DEAD")
            break

        if abs(error) > 18:
            # measured polarity: left increases heading_deg, right decreases it
            hold(pad, "left" if error > 0 else "right", min(0.45, max(0.1, abs(error) / 240.0)))
        elif distance > 38:
            hold(pad, "up", min(0.9, max(0.25, distance / 200.0)))
        else:
            tap(pad, "a")          # swing
            time.sleep(0.35)
            tap(pad, "a")
        time.sleep(0.35)

    final = state(pad)
    player = me(final)
    living = enemies(final)
    print(f"\nplayer at ({player.get('x')},{player.get('z')}) hp {player.get('hp')}/{player.get('hp_max')}")
    print("enemies still alive:", [(e.get('class'), e.get('hp')) for e in living][:6])
    print("shot:", pad.shot("combat"))
