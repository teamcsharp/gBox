"""Fix the teleport: keep the character's own height, and offset it — do not drop it to y=0.1.

The unstuck teleport wrote ground level:

```python
landed = teleport(pad, hx, 0.1, hz)      # wrong: hx/hz may be on a ledge 32 units up
```

The character was frozen at `(483.3, 32.3, 26.3)` - `y = 32.3` - so writing `y = 0.1` put it **inside the terrain**, which is a worse trap than the one it was in. That is why earlier
attempts logged `drop landed` and the character still would not move: the write succeeded and the destination was invalid.

Proven fix, measured directly:

```
before:            (483.3, 32.3, 26.3)
write (+15 x, same y): (498.3, 33.0, 26.3)
after holding up:   8.9 units moved
```

**Relocating by a small offset at the character's own height frees it and it walks normally again.**

So the unstuck now tries a few same-height offsets in turn - forward, back, left, right - and stops at the first that produces movement.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

old = """        if retreated < 0.5 and TELEPORT_ATTEMPTS["count"] < 2:
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

new = """        if retreated < 0.5 and TELEPORT_ATTEMPTS["count"] < 2:
            # Every direction blocked and the retreat blocked: the character is wedged. Relocate it a short distance
            # AT ITS OWN HEIGHT - writing y=0.1 buried it in terrain when it stood at y 32.3, which is why earlier
            # "drop landed" attempts never freed it. Measured: a same-height move of 15 units freed it and it then
            # walked 8.9 units normally.
            TELEPORT_ATTEMPTS["count"] += 1
            here = state(pad).get("player") or {}
            hx = float(here.get("x") or 0)
            hy = float(here.get("y") or 0)
            hz = float(here.get("z") or 0)
            freed = False
            for dx, dz in ((15.0, 0.0), (-15.0, 0.0), (0.0, 15.0), (0.0, -15.0)):
                log(f"  wedged at ({hx:.0f},{hy:.0f},{hz:.0f}) - relocating {dx:+.0f},{dz:+.0f} at the same height")
                if not teleport(pad, hx + dx, hy, hz + dz):
                    continue
                before_move = state(pad).get("player") or {}
                start = (float(before_move.get("x") or 0), float(before_move.get("z") or 0))
                hold(pad, "up", 0.8)
                after_move = state(pad).get("player") or {}
                end = (float(after_move.get("x") or 0), float(after_move.get("z") or 0))
                if math.dist(start, end) > 2.0:
                    log(f"  relocation freed it ({math.dist(start, end):.1f} units)")
                    freed = True
                    break
            if freed:
                TELEPORT_ATTEMPTS["count"] = 0
                return "up\""""

count = text.count(old)
print("teleport block anchor count:", count)
if count != 1:
    raise SystemExit("teleport block not unique - refusing to guess")
text = text.replace(old, new, 1)

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER - relocation keeps the character's own height")
