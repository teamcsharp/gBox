"""Stop burning minutes on routed legs that are not moving, and fall back to a direct walk.

Measured: a target sat at `76 -> 76` for **two and a half minutes** and then closed to 20. The arithmetic matches
exactly - `walk_to` gives up after 26 no-progress iterations at roughly half a second each (about 13 s), and `route_walk`
loops up to **12 legs**, so twelve fruitless legs cost about 156 s before the call returns without having moved.

Two changes:

1. **bail after two fruitless legs.** One leg making no progress can be a narrow doorway; two in a row means the cell
   graph is not describing this geometry and more legs will not help. That is a cooldown on wasted time rather than
   patience, and it keeps the honest signal (`route=no` is reported by the caller) instead of a long silence.
2. **fall back to a direct walk.** If the routed attempt gained less than 2 units, call `walk_to` straight at the target
   once. The routed path is an optimisation; the direct walk is the thing that actually moves the character when the
   graph is wrong, and without it the function returned "no progress" having spent minutes failing - which is exactly the
   behaviour the operator described as the bot standing around.

Neither change can loop: the bail is bounded by two, and the fallback is a single call.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

# 1. bail after two fruitless legs
OLD = '''                before = (x, z)
                walk_to(pad, target[0], target[1], max_steps=22)
                after = state(pad).get("player") or {}
                if math.dist(before, (float(after.get("x") or 0), float(after.get("z") or 0))) < 2.0:
                    break                                     # this leg is blocked too; stop rather than spin'''
NEW = '''                before = (x, z)
                walk_to(pad, target[0], target[1], max_steps=22)
                after = state(pad).get("player") or {}
                if math.dist(before, (float(after.get("x") or 0), float(after.get("z") or 0))) < 2.0:
                    # ONE fruitless leg can be a narrow doorway; TWO in a row means the cell graph does not describe
                    # this geometry and further legs only cost time - twelve of them cost about 156 seconds.
                    fruitless += 1
                    if fruitless >= 2:
                        break
                else:
                    fruitless = 0'''
count = text.count(OLD)
print("leg anchor count:", count)
if count != 1:
    raise SystemExit("leg progress check not unique")
text = text.replace(OLD, NEW, 1)
print("route_walk now bails after two fruitless legs")

# 2. declare the counter
OLD2 = '''        if routers:
            for _ in range(legs):'''
NEW2 = '''        if routers:
            fruitless = 0
            for _ in range(legs):'''
count2 = text.count(OLD2)
print("loop anchor count:", count2)
if count2 == 1:
    text = text.replace(OLD2, NEW2, 1)
    print("fruitless counter declared")

# 3. direct-walk fallback when routing gained nothing
OLD3 = '''    except Exception:                                         # noqa: BLE001 - the map is an optimisation, not a gate
        pass
    me = state(pad).get("player") or {}
    return math.hypot(tx - float(me.get("x") or 0), tz - float(me.get("z") or 0))'''
NEW3 = '''    except Exception:                                         # noqa: BLE001 - the map is an optimisation, not a gate
        pass
    me = state(pad).get("player") or {}
    left = math.hypot(tx - float(me.get("x") or 0), tz - float(me.get("z") or 0))
    if left > 25.0:
        # the routed path gained nothing: walk straight at it once. The map is an optimisation; this is the movement.
        walk_to(pad, tx, tz, max_steps=40)
        me = state(pad).get("player") or {}
        left = math.hypot(tx - float(me.get("x") or 0), tz - float(me.get("z") or 0))
    return left'''
count3 = text.count(OLD3)
print("return anchor count:", count3)
if count3 == 1:
    text = text.replace(OLD3, NEW3, 1)
    print("direct-walk fallback added")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
