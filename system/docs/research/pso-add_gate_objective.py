"""Give the bot an actual objective: walk to the nearest gate and cross it.

The travel branch was a blind sweep - `hold(left or right, 0.3)` then `hold(up, 0.7)` - which is why the bot wandered across rooms instead of proceeding through them. It had no idea
where a door was.

The state already lists them: every field entity with `kind == "gate"`, with `x`/`z`. Fields measured **19-24 gates** each. So "proceed to the next room" becomes a target like any other,
and the same distance hill-climb that closed on an enemy from 210 units steers to it:

* nearest gate, note the distance;
* inside ~20 units, walk straight through it (which is the operator's requirement - and `walk_through` is on, so geometry will not stop it);
* outside, hill-climb: turn a side, step, and keep that side only if the distance fell;
* log the number of **distinct** gates approached, which is the honest count of how much of the room has been explored.

This replaces "wander and hope" with "go to a door and cross it", and it uses the same evidence rule everywhere else does: measure, then act.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

old = """        else:
            # travel: the game needs the character to cross the floor to find the key and the door
            sweep = time.time() - started
            hold(pad, "left" if int(sweep) % 2 else "right", 0.3)
            hold(pad, "up", 0.7)
            moved += 1"""

new = """        else:
            # No enemies here. Instead of sweeping blindly, walk to a DOOR: the state lists every gate with its
            # position (fields carry 19-24 of them), so "proceed to the next room" becomes a target to steer at.
            gates = [e for e in (now.get("entities") or []) if str(e.get("kind")) == "gate"
                     and e.get("x") is not None and e.get("z") is not None]
            if gates:
                gate = min(gates, key=lambda e: (float(e.get("x") or 0) - x) ** 2
                           + (float(e.get("z") or 0) - z) ** 2)
                gx, gz = float(gate.get("x") or 0), float(gate.get("z") or 0)
                gdist = math.hypot(gx - x, gz - z)
                gates_seen.add((round(gx / 25.0), round(gz / 25.0)))     # distinct gates, coarsely binned
                if gdist <= 20.0:
                    # close enough to cross: walk straight through it, walk_through keeps geometry out of the way
                    hold(pad, "up", 0.9)
                    crossed.append((round(gx / 25.0), round(gz / 25.0)))
                else:
                    gate_side = globals().get("GATE_SIDE", 1)
                    before_g = gdist
                    hold(pad, "left" if gate_side > 0 else "right", 0.18)
                    hold(pad, "up", 0.75)
                    after_p = state(pad).get("player") or {}
                    ax, az = float(after_p.get("x") or 0), float(after_p.get("z") or 0)
                    if math.hypot(gx - ax, gz - az) > before_g - 0.5:
                        globals()["GATE_SIDE"] = -gate_side
                moved += 1
            else:
                # a room with no gates listed: sweep, but keep it short so the next sample can find one
                hold(pad, "left" if int(time.time()) % 2 else "right", 0.25)
                hold(pad, "up", 0.6)
                moved += 1"""

count = text.count(old)
print("travel branch anchor count:", count)
if count != 1:
    raise SystemExit("travel branch not unique - refusing to guess")
text = text.replace(old, new, 1)

# counters for the new objective
old_counters = "    last_position, stuck, killed, moved, closest = None, 0, 0, 0.0, 999.0"
new_counters = "    last_position, stuck, killed, moved, closest = None, 0, 0, 0.0, 999.0\n    gates_seen, crossed = set(), []"
if text.count(old_counters) == 1:
    text = text.replace(old_counters, new_counters, 1)
    print("gate counters added")

old_return = '    return f"played {seconds:.0f}s, {moved} travel steps, closest approach {closest:.1f}"'
new_return = '    return (f"played {seconds:.0f}s, {moved} travel steps, closest approach {closest:.1f}, "\n            f"gates approached {len(gates_seen)}, crossed {len(crossed)}")'
if text.count(old_return) == 1:
    text = text.replace(old_return, new_return, 1)
    print("return reports gates")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
