"""When every direction is blocked and there is no remembered good position, drop to ground level.

The teleport did not fire: `GOOD_POSITION` was empty because the character had been stuck since launch and so never recorded a position where it moved. Meanwhile the tell in the state is
`y = 27.153` while the surrounding floor reads `y = 0.1` (measured in the Dragon arena and elsewhere). The character is standing on a **raised ledge/alcove**, which is exactly the state
where all four directions and the backward retreat all report 0.0 units.

So the last resort does not need a remembered position at all: **write the same x and z with y at ground level.** The character drops off the ledge onto the floor beneath it, which is a
place it demonstrably can walk (every field room reads y ~0.1). This is the same `write_memory(ptr + 0x38, pack(">fff", x, y, z))` primitive the city warp already uses, so it is
proven on this build.

Guard: only when the whole retreat failed, at most twice, and it reports whether the position actually changed.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

old = """        if retreated < 0.5 and GOOD_POSITION.get("x") is not None and TELEPORT_ATTEMPTS["count"] < 2:
            # Nothing moved in any direction and the retreat is blocked too: this is a ledge, not a menu.
            TELEPORT_ATTEMPTS["count"] += 1
            good = (GOOD_POSITION["x"], GOOD_POSITION["y"], GOOD_POSITION["z"])
            log(f"  every direction is blocked - reloading at the last good position {good[0]:.1f},{good[2]:.1f}")
            landed = teleport(pad, *good)
            log(f"  teleport {'landed' if landed else 'did not take'}")
            if landed:
                TELEPORT_ATTEMPTS["count"] = 0
                return "up\""""

new = """        if retreated < 0.5 and TELEPORT_ATTEMPTS["count"] < 2:
            # Every direction blocked and the retreat blocked: a ledge, not a menu. Drop to ground level at the same
            # x/z - the fields all read y ~0.1, and a character standing at y 27 cannot walk anywhere.
            TELEPORT_ATTEMPTS["count"] += 1
            here = state(pad).get("player") or {}
            hx, hz = float(here.get("x") or 0), float(here.get("z") or 0)
            hy = float(here.get("y") or 0)
            log(f"  every direction is blocked at y {hy:.1f} - dropping to ground level at {hx:.1f},{hz:.1f}")
            landed = teleport(pad, hx, 0.1, hz)
            log(f"  drop {'landed' if landed else 'did not take'}")
            if landed:
                TELEPORT_ATTEMPTS["count"] = 0
                hold(pad, "up", 0.6)
                return "up\""""

count = text.count(old)
print("teleport block anchor count:", count)
if count != 1:
    raise SystemExit("teleport block not unique - refusing to guess")
text = text.replace(old, new, 1)

# record a good position for much smaller movements too, so the fallback has something to remember
old_track = 'if last_position and math.dist((x, z), (last_position[0], last_position[1])) > 3.0:'
if text.count(old_track) == 1:
    text = text.replace(old_track, 'if last_position and math.dist((x, z), (last_position[0], last_position[1])) > 1.0:', 1)
    print("good positions are recorded after 1 unit of movement (was 3)")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
