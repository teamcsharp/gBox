"""Put the hill-climbing approach into the loop - it is the first steering that works.

The heading-based controller never converged: aim readings swung +130 / +21 / 0 / +145 for presses in the same direction, which is not a signal to servo on. Hill-climbing on **distance**
does converge - it closed `TObjEneBeast` from **210 units to 12.0** - and when the swing threshold was raised to 15.5 it **killed an enemy** (the room went from two beasts to one), which is
the second verified kill of the session and the first the loop can reproduce.

So `play()` now:

1. picks the nearest enemy and the distance to it;
2. inside the game's envelope (~12-15 units, since the enemy body blocks closer than ~16.7) it presses `b` then `a`;
3. outside it, turns one way, steps forward, and **re-measures**: if the distance fell it keeps that side, if it rose it flips.

No heading, no assumption about which way is "toward" - just "did that make me closer".
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

old = """        if enemies:
            target = min(enemies, key=lambda e: (float(e.get("x") or 0) - x) ** 2
                         + (float(e.get("z") or 0) - z) ** 2)
            tx, tz = float(target.get("x") or 0), float(target.get("z") or 0)
            distance = math.hypot(tx - x, tz - z)
            error = ((bearing(x, z, tx, tz) - heading + 540.0) % 360.0) - 180.0
            name = str(target.get("class"))
            hp = float(target.get("hp"))
            if name in last_enemy_hp and hp < last_enemy_hp[name]:
                log(f"  {name} hit: {last_enemy_hp[name]:.0f} -> {hp:.0f}")
            last_enemy_hp[name] = hp

            # The game's own envelope (pso_coop_combat): ~12 units, 8 degree half angle. Outside the cone the swing
            # cannot connect, so turn first in small measured steps; inside it, cancel any menu with B and swing.
            if abs(error) > 8:
                hold(pad, "left" if error > 0 else "right", min(0.22, max(0.06, abs(error) / 400.0)))
            elif distance > 12:
                before_move = state(pad).get("player") or {}
                start = (float(before_move.get("x") or 0), float(before_move.get("z") or 0))
                hold(pad, "up", min(0.55, max(0.2, (distance - 8) / 160.0)))
                after_move = state(pad).get("player") or {}
                end = (float(after_move.get("x") or 0), float(after_move.get("z") or 0))
                if math.dist(start, end) < 1.0:
                    # an enemy body blocks the approach, and it is not a wall: step back, then go round it
                    log("  approach blocked - backing off and strafing around the body")
                    hold(pad, "down", 0.4)
                    hold(pad, "left" if int(time.time()) % 2 else "right", 0.45)
                    hold(pad, "up", 0.5)
                moved += 1
            else:
                tap(pad, "b")           # a pause menu eats the swing; START toggles it, B cancels it
                time.sleep(0.15)
                tap(pad, "a")
                time.sleep(0.4)
                killed += 0"""

new = """        if enemies:
            target = min(enemies, key=lambda e: (float(e.get("x") or 0) - x) ** 2
                         + (float(e.get("z") or 0) - z) ** 2)
            tx, tz = float(target.get("x") or 0), float(target.get("z") or 0)
            distance = math.hypot(tx - x, tz - z)
            name = str(target.get("class"))
            hp = float(target.get("hp"))
            if name in last_enemy_hp and hp < last_enemy_hp[name]:
                log(f"  {name} HIT: {last_enemy_hp[name]:.0f} -> {hp:.0f}")
            last_enemy_hp[name] = hp

            # Nothing here trusts `heading_deg`: presses in one direction produced +130, +21, 0 and +145 degrees, so
            # it is not a signal to servo on. Instead hill-climb on DISTANCE - turn a side, step, and keep that side
            # only if it made us closer. That is how an enemy was closed from 210 units to 12 and killed.
            if distance <= 15.5:
                tap(pad, "b")           # a pause menu eats the swing; START toggles it, B cancels it
                time.sleep(0.12)
                tap(pad, "a")
                time.sleep(0.45)
                if len(enemies) < enemy_count_before:
                    killed += 1
                    log(f"  killed one - {len(enemies)} left")
            else:
                approach_side = globals().get("APPROACH_SIDE", 1)
                before = distance
                hold(pad, "left" if approach_side > 0 else "right", 0.18)
                hold(pad, "up", 0.75)
                after_state = state(pad).get("player") or {}
                now_target = [e for e in (after_state.get("entities") or [])] if False else None
                found_after = state(pad)
                after_enemies = [e for e in (found_after.get("entities") or [])
                                 if str(e.get("kind")) == "enemy" and e.get("hp") is not None
                                 and float(e.get("hp")) > 0]
                if after_enemies:
                    near = min(after_enemies, key=lambda e: (float(e.get("x") or 0) - float((found_after.get("player") or {}).get("x") or 0)) ** 2
                               + (float(e.get("z") or 0) - float((found_after.get("player") or {}).get("z") or 0)) ** 2)
                    px = float((found_after.get("player") or {}).get("x") or 0)
                    pz = float((found_after.get("player") or {}).get("z") or 0)
                    after_distance = math.hypot(float(near.get("x") or 0) - px, float(near.get("z") or 0) - pz)
                    if after_distance > before - 0.5:
                        globals()["APPROACH_SIDE"] = -approach_side
                moved += 1"""

count = text.count(old)
print("combat block anchor count:", count)
if count != 1:
    raise SystemExit("combat block not unique - refusing to guess")

text = text.replace(old, new, 1)

# enemy_count_before needs defining each iteration
old_head = """        enemies = [e for e in (now.get("entities") or [])
                   if str(e.get("kind")) == "enemy" and e.get("hp") is not None and float(e.get("hp")) > 0]"""
new_head = """        enemies = [e for e in (now.get("entities") or [])
                   if str(e.get("kind")) == "enemy" and e.get("hp") is not None and float(e.get("hp")) > 0]
        enemy_count_before = len(enemies)"""
if text.count(old_head) == 1:
    text = text.replace(old_head, new_head, 1)
    print("enemy_count_before defined")
else:
    print("enemy list anchor count:", text.count(old_head))

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER - the loop hill-climbs on distance")
