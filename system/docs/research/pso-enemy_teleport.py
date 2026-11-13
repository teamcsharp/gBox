"""Reach enemies the same way boxes are reached: teleport-walk the map's route.

The box approach proved the method - **115 units to 5.4 in one call**, fourteen containers destroyed - while the enemy branch still used the old hill-climb, which is the thing that wandered between 115
and 167 for fourteen samples because it needs a heading `heading_deg` cannot provide.

So the enemy approach becomes the same call. Everything else about combat stays: the sweep (three `b`+`a` swings then a rotate) inside the **real PMT range of 22 units**, the HP tracking that logs a HIT,
and the give-up budget that walks away from something it cannot hurt.

The fallback is kept: if the map has no route (target outside the safe set, or the character off it), the old hill-climb runs so nothing regresses where the map cannot help.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

old = """            else:
                approach_side = globals().get("APPROACH_SIDE", 1)
                before = distance
                hold(pad, "left" if approach_side > 0 else "right", 0.18)
                hold(pad, "up", 0.75)
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

new = """            else:
                # TELEPORT-WALK to the enemy, exactly as the boxes are reached: the map's route over safe cells, no
                # heading involved. Measured on boxes: 115 units -> 5.4 in one call. The hill-climb that used to be
                # here wandered 115-167 for fourteen samples because heading_deg is not a reliable compass.
                walked = False
                if teleport_walk is not None:
                    try:
                        teleport_walk(pad, tx, tz, max_hops=10)
                        walked = True
                    except Exception:                      # noqa: BLE001
                        walked = False
                if not walked:
                    # the map could not help: steer as before
                    approach_side = globals().get("APPROACH_SIDE", 1)
                    before = distance
                    hold(pad, "left" if approach_side > 0 else "right", 0.18)
                    hold(pad, "up", 0.75)
                    found_after = state(pad)
                    player_after = (found_after.get("player") or {})
                    px = float(player_after.get("x") or 0)
                    pz = float(player_after.get("z") or 0)
                    after_enemies = [e for e in (found_after.get("entities") or [])
                                     if str(e.get("kind")) == "enemy" and e.get("hp") is not None
                                     and float(e.get("hp")) > 0]
                    if after_enemies:
                        near = min(after_enemies, key=lambda e: (float(e.get("x") or 0) - px) ** 2
                                   + (float(e.get("z") or 0) - pz) ** 2)
                        after_distance = math.hypot(float(near.get("x") or 0) - px, float(near.get("z") or 0) - pz)
                        if after_distance > before - 0.5:
                            globals()["APPROACH_SIDE"] = -approach_side
                moved += 1"""

count = text.count(old)
print("enemy approach anchor count:", count)
if count != 1:
    raise SystemExit("enemy approach not unique - refusing to guess")
text = text.replace(old, new, 1)
print("the enemy approach now teleport-walks")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
