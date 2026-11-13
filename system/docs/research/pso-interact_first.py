"""Interact first: warps, door keys and fence switches outrank boxes and enemies.

The operator's rule, stated twice and ignored twice: *"if the target appears, that means that there's something needs to
be interacted with. If your indicator changes into an interact indicator, that means you need to interact with an
element."* And: *"it found the teleporter. Go to the next level."*

Two structural faults made the loop walk straight past them:

1. **boxes outranked everything** - this room holds **79 containers**, so the box branch consumed every iteration and its
   `continue` meant the warp/key/door code below it was unreachable. The bot walked right up to `TObjDoorKey` at 115
   units and never touched it.
2. **the warp/key/door code lived in the `else:` of `if enemies:`** - so even with no boxes, a room containing any enemy
   would skip them entirely. This Forest room has three.

Both are fixed by moving interaction to the **top** of the frame, ahead of the box branch, ranked warp > switch > the
rest, nearest first:

* within **12 units** - the game is offering the interact, so press `A` (twice, because the first press can land while
  the reticle is still resolving) and log it;
* within **400 units** - route to it with `walk_to`, which is the proven walking path (60.8 -> 9.5 units, no teleports).

No vision is involved: the classes come from RAM, exactly as the operator demanded - `Warp*`, `TObjDoorKey`,
`TLazerFenceSw`, `TOKeyGenericSw`. Progress is not loot, and a level-exit teleporter is the whole point of clearing a
floor.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

anchor = "        # BOXES FIRST."
if text.count(anchor) != 1:
    raise SystemExit("box branch anchor count: %d" % text.count(anchor))

BLOCK = '''        # INTERACT FIRST, AHEAD OF EVERYTHING. The operator: "if your indicator changes into an interact indicator,
        # that means you need to interact with an element" and "it found the teleporter. Go to the next level."
        # These outrank boxes and enemies because they are PROGRESS: a level-exit teleporter, the door key that opens
        # the way on, the fence switch. The classes come from RAM, so no vision is involved:
        # Warp*, TObjDoorKey, TLazerFenceSw and TOKeyGenericSw are already named by the class registry.
        interact = []
        for candidate in (now.get("entities") or []):
            candidate_class = str(candidate.get("class"))
            if candidate.get("x") is None or candidate.get("z") is None:
                continue
            if "Warp" in candidate_class:
                rank = 0                                  # a level exit is the strongest signal in the room
            elif candidate_class in ("TObjDoorKey", "TLazerFenceSw", "TOKeyGenericSw"):
                rank = 1                                  # the switch that opens the way on
            else:
                continue
            idist = math.hypot(float(candidate.get("x") or 0) - x, float(candidate.get("z") or 0) - z)
            interact.append((rank, idist, candidate))
        if interact:
            interact.sort(key=lambda t: (t[0], t[1]))
            rank, idist, ient = interact[0]
            iclass = str(ient.get("class"))
            kind = "level exit" if rank == 0 else "switch"
            if idist <= 12.0:
                # The game is offering the interact. Press A twice: the first press can land while the reticle is still
                # resolving, and a teleporter needs the action, not a nudge.
                tap(pad, "a")
                time.sleep(0.4)
                tap(pad, "a")
                time.sleep(0.25)
                log(f"  INTERACT: pressed A on {iclass} at {idist:.1f} units ({kind})")
                moved += 1
                continue
            if idist <= 400.0:
                before_i = (x, z)
                walk_to(pad, float(ient.get("x") or 0), float(ient.get("z") or 0), max_steps=40)
                nowat = state(pad).get("player") or {}
                left = math.hypot(float(ient.get("x") or 0) - float(nowat.get("x") or 0),
                                  float(ient.get("z") or 0) - float(nowat.get("z") or 0))
                log(f"  INTERACT: walking to {iclass} ({kind}) {idist:.0f} -> {left:.0f} units")
                moved += 1
                time.sleep(0.1)
                continue

'''

text = text.replace(anchor, BLOCK + anchor, 1)
print("interaction priority block inserted before the box branch")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
