"""Put the proven combat recipe into the endless loop.

An enemy died to this sequence, measured:

```
enemy d 12.0  aim +2.8  hp 41          <- already damaged by earlier hits
press A x3 -> [Beast 60, Beast 20] -> [Beast 60]      one dead
```

The recipe that worked, and the three things every earlier attempt was missing:

1. **`b` before swinging.** A previous `start` press had left PSO's pause menu open, and while it is open the character cannot move and A does menu things. `b` cancels it. **START toggles
   that menu** - pressing it to "close" it is what opened it in the first place.
2. **Inside the game's own envelope.** `pso_coop_combat` documents it: horizontal range ~10-12 units, horizontal half angle **8 degrees**. Swinging at 16-45 units with 100+ degrees of
   aim error - which is what every earlier attempt did - cannot connect.
3. **Carry a ranged weapon.** The character could not close below ~17 units because the enemy's body blocks it; the RED HANDGUN (`004400`, ATA 46) reaches from there.

So `play()` attacks only when the aim is inside the cone, otherwise turns in small measured steps, and presses `b` immediately before `a` so a stray menu cannot eat the swing.
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
                killed += 0
                log(f"  {name} hit: {last_enemy_hp[name]:.0f} -> {hp:.0f}")
            last_enemy_hp[name] = hp

            if abs(error) > 20:
                hold(pad, "left" if error > 0 else "right", min(0.4, max(0.1, abs(error) / 240.0)))
            elif distance > 40:
                hold(pad, "up", min(0.8, max(0.25, distance / 200.0)))
                moved += 1
            else:
                tap(pad, "a")
                time.sleep(0.3)
                tap(pad, "a")"""

new = """        if enemies:
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
                hold(pad, "up", min(0.55, max(0.2, (distance - 8) / 160.0)))
                moved += 1
            else:
                tap(pad, "b")           # a pause menu eats the swing; START toggles it, B cancels it
                time.sleep(0.15)
                tap(pad, "a")
                time.sleep(0.4)
                killed += 0"""

if text.count(old) != 1:
    raise SystemExit("play combat anchor count: %d" % text.count(old))
text = text.replace(old, new, 1)

# the handgun belongs in the arming step: the enemy body blocks closer than ~17 units
old_arm = """                    {"op": "survival", "on": True}):                      # virtual Scape Doll"""
new_arm = """                    {"op": "give", "code": "004400", "equip": True},      # RED HANDGUN: reaches from ~17 units
                    {"op": "survival", "on": True}):                      # virtual Scape Doll"""
if text.count(old_arm) == 1:
    text = text.replace(old_arm, new_arm, 1)
    print("arming now also gives the handgun")
else:
    print("arming anchor count:", text.count(old_arm))

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER - combat uses the proven envelope and clears menus first")
