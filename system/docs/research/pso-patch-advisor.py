"""Make self-play equip the weapon the situation calls for before each fight.

The advisor's rules are unit-tested against six situations and match the reference: several close enemies get a wide weapon (Sword/Partisan/Slicer),
one close enemy gets a fast single-target weapon (Saber/Dagger), anything far or flying gets a ranged weapon, and nothing nearby gets no change.

This hooks it into the fight: when a target is locked, the advisor is consulted once and the character equips accordingly. Weapon changes go through
the plane's item operations, which are not keyboard input, so this works even while the game is unfocused and the rest of the bot is waiting.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\selfplay2.py")
text = path.read_text(encoding="utf-8")

old = '''                log(f"locking target {locked['class']} at {locked['distance']:.0f} units "
                    f"(hp {locked['hp']})", {"event": "lock", "class": locked["class"], "hp": locked["hp"]})'''
new = '''                log(f"locking target {locked['class']} at {locked['distance']:.0f} units "
                    f"(hp {locked['hp']})", {"event": "lock", "class": locked["class"], "hp": locked["hp"]})
                try:
                    import weapon_advisor as WA
                    me_point = ME.read_pos()
                    situation = enemies(me_point) if me_point else []
                    wanted, reason = WA.choose(situation, (me_point[0], now_y() or 0.0, me_point[1])) if me_point else (None, "")
                    if wanted:
                        name = WA.equip_class(wanted)
                        log(f"  weapon advice: {reason} -> equipped {name}")
                except Exception as exc:                          # noqa: BLE001
                    log(f"  weapon advice unavailable: {type(exc).__name__}: {str(exc)[:70]}")'''
if text.count(old) != 1:
    raise SystemExit(f"lock pattern count {text.count(old)}")
text = text.replace(old, new)
path.write_text(text, encoding="utf-8")
print("self-play consults the weapon advisor when it locks a target")
