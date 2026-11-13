"""Damage a boss: boss entities are huge, so melee range has to be measured from their body, not their origin.

The bot is in the Dragon arena and moves constantly - positions sweep 100+ units and its own HP drops 44 -> 20 - yet `TBoss1Dragon` stays at **hp 1300**. The attack branch only
fires when the target is within 40 units of its recorded position, and for a boss that position is the centre of a very large body: standing against its flank is still hundreds
of units away. So the bot swings at air while the boss hits it.

The fix is to give a boss target a much larger reach, and to verify by the only thing that matters - the boss's HP going down.

`TBoss1DragonColli_C` (hp 0) is the boss's collision proxy and is not a damageable target, so it is filtered out.
"""
import math
import time

from pso_pad import Pad, call

BOSS_REACH = 220.0        # a boss body is large; its origin can be far from its surface


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
    boss_hp = None
    for round_index in range(30):
        now = state(pad)
        player = now.get("player") or {}
        if not player:
            print("no player")
            break
        x, z = float(player.get("x") or 0), float(player.get("z") or 0)
        heading = float(player.get("heading_deg") or 0)

        enemies = [e for e in (now.get("entities") or [])
                   if str(e.get("kind")) == "enemy" and e.get("hp") and float(e.get("hp")) > 0
                   and "Colli" not in str(e.get("class"))]
        if not enemies:
            print("no damageable enemies")
            break
        boss = min(enemies, key=lambda e: (float(e.get("x") or 0) - x) ** 2 + (float(e.get("z") or 0) - z) ** 2)
        bx, bz = float(boss.get("x") or 0), float(boss.get("z") or 0)
        hp = float(boss.get("hp"))
        distance = math.hypot(bx - x, bz - z)
        if boss_hp is not None and hp < boss_hp:
            print(f"  *** {boss.get('class')} took damage: {boss_hp:.0f} -> {hp:.0f} ***")
        boss_hp = hp

        want = (math.degrees(math.atan2(bx - x, bz - z)) + 360.0) % 360.0
        error = ((want - heading + 540.0) % 360.0) - 180.0
        print(f"  {round_index:2d}: {boss.get('class')} hp {hp:.0f} dist {distance:6.1f} "
              f"| me ({x:7.1f},{z:7.1f}) hp {player.get('hp')} err {error:+6.1f}")

        if abs(error) > 30:
            hold(pad, "left" if error > 0 else "right", min(0.4, max(0.12, abs(error) / 240.0)))
        elif distance > BOSS_REACH:
            hold(pad, "up", min(1.0, max(0.3, distance / 400.0)))
        else:
            tap(pad, "a")
            time.sleep(0.2)
            tap(pad, "a")
        time.sleep(0.2)

    final = state(pad)
    enemies = [e for e in (final.get("entities") or []) if str(e.get("kind")) == "enemy" and e.get("hp")]
    print("\nenemies:", [(e.get("class"), e.get("hp")) for e in enemies][:4])
    print("shot:", pad.shot("boss_fight"))
