"""Get inside the boss and swing - `walk_through` makes the body passable, so approach to the origin.

The Dragon stayed at 1300 HP across 30 rounds while the bot swung from 205-345 units away. `always_hit`'s own scope says *"targets must still be in range and hittable"*, and a huge
boss's origin sits far from its flank, so **distance to origin** was the wrong thing to minimise by walking around it.

But `walk_through` is on, which means collision no longer stops the character. So it can walk **into** the boss's body until the distance to the origin is genuinely small, and
swing there. That is the one approach that makes "in range and hittable" true for a creature this size instead of guessing a bigger number.

The test is stated in the only terms that matter: the Dragon's HP must go down.
"""
import math
import time

from pso_pad import Pad, call

INSIDE = 70.0        # close enough that the origin itself is near, not the flank


def state(pad):
    return call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}


def hold(pad, key, secs):
    pad.send([{"key": key, "down": True}])
    time.sleep(secs)
    pad.send([{"key": key, "down": False}])


def tap(pad, key):
    pad.send([{"key": key, "down": True}, {"key": key, "down": False}])


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)
    now = state(pad)
    me = now.get("player") or {}
    enemies = [e for e in (now.get("entities") or [])
               if str(e.get("kind")) == "enemy" and e.get("hp") and float(e.get("hp")) > 0
               and "Colli" not in str(e.get("class"))]
    print("player:", (me.get("x"), me.get("z")), "| hp", me.get("hp"))
    print("targets:", [(e.get("class"), e.get("hp"), (e.get("x"), e.get("z"))) for e in enemies][:3])
    if not enemies:
        raise SystemExit("no damageable enemy in this room")

    best_hp = None
    for round_index in range(26):
        now = state(pad)
        me = now.get("player") or {}
        if not me:
            print("no player")
            break
        x, z = float(me.get("x") or 0), float(me.get("z") or 0)
        heading = float(me.get("heading_deg") or 0)
        enemies = [e for e in (now.get("entities") or [])
                   if str(e.get("kind")) == "enemy" and e.get("hp") and float(e.get("hp")) > 0
                   and "Colli" not in str(e.get("class"))]
        if not enemies:
            print("target gone")
            break
        boss = min(enemies, key=lambda e: (float(e.get("x") or 0) - x) ** 2 + (float(e.get("z") or 0) - z) ** 2)
        bx, bz = float(boss.get("x") or 0), float(boss.get("z") or 0)
        hp = float(boss.get("hp"))
        distance = math.hypot(bx - x, bz - z)
        if best_hp is not None and hp < best_hp:
            print(f"  *** DAMAGE: {best_hp:.0f} -> {hp:.0f} ***")
        best_hp = hp

        want = (math.degrees(math.atan2(bx - x, bz - z)) + 360.0) % 360.0
        error = ((want - heading + 540.0) % 360.0) - 180.0
        print(f"  {round_index:2d}: {boss.get('class')} hp {hp:.0f} dist {distance:6.1f} "
              f"| me ({x:7.1f},{z:7.1f}) hp {me.get('hp')} err {error:+6.1f}")

        if distance > INSIDE:
            if abs(error) > 30:
                hold(pad, "left" if error > 0 else "right", min(0.4, max(0.12, abs(error) / 240.0)))
            else:
                hold(pad, "up", min(1.2, max(0.35, distance / 300.0)))
        else:
            if abs(error) > 25:
                hold(pad, "left" if error > 0 else "right", 0.16)
            for _ in range(3):
                tap(pad, "a")
                time.sleep(0.18)
        time.sleep(0.15)

    final = state(pad)
    enemies = [e for e in (final.get("entities") or []) if str(e.get("kind")) == "enemy" and e.get("hp")]
    print("\nfinal:", [(e.get("class"), e.get("hp")) for e in enemies][:3])
    print("shot:", pad.shot("boss_inside"))
