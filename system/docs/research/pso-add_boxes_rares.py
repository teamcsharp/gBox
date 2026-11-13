"""Break every box, and keep the rares flowing.

Two things the operator asked for, both verified available on this build (GameCube Plus US rev 2):

* `floor_rares` with a character class spawns a rare on the floor - measured: `{"codes": ["008403"], "spawned": 1, "verified": true}`;
* `enemy_drops` makes every normal enemy drop cycle through a chosen pool - measured: `{"on": true, "verified": ..., "message": "Enemies now drop one item per normal enemy drop event, cycling
  through your selected pool. Boxes are unchanged."}`.

**And the tool documents the limit honestly**: *"Boxes are unchanged"* - and `rare_drops` is Dreamcast-only, so on GameCube the boxes keep their stock tables. What the bot can still do is the thing
the operator actually asked for: **destroy every box**. The containers are ordinary entities in the table - `TObjContainerItem`, `TOCapsuleAncient01` - so they can be walked up to and hit like
anything else, and whatever they drop is then stepped over.

So `play()` gains a container branch, placed **after** enemies (fight what is dangerous first) and **before** warps and doors (loot before leaving):

* nearest container within 45 units -> approach and swing;
* the swing uses the same `b` then `a` recipe as combat, because a pause menu eats it exactly the same way.

And `arm()` now turns the rares on every session, next to Ultimate and the gate flags.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

# ---- 1. break boxes ----------------------------------------------------------------------------------------------
old = """            warps = [e for e in (now.get("entities") or [])
                     if "Warp" in str(e.get("class")) and e.get("x") is not None and e.get("z") is not None]"""
new = """            # BREAK THE BOXES. Containers are ordinary entities in the table (TObjContainerItem, TOCapsuleAncient01),
            # so they can be walked up to and hit. Boxes come before warps and doors: loot before leaving.
            boxes = [e for e in (now.get("entities") or [])
                     if ("Container" in str(e.get("class")) or "Capsule" in str(e.get("class")))
                     and e.get("x") is not None and e.get("z") is not None]
            if boxes:
                box = min(boxes, key=lambda e: (float(e.get("x") or 0) - x) ** 2
                          + (float(e.get("z") or 0) - z) ** 2)
                bx, bz = float(box.get("x") or 0), float(box.get("z") or 0)
                bdist = math.hypot(bx - x, bz - z)
                if bdist <= 14.0:
                    tap(pad, "b")                      # a pause menu eats the swing here too
                    time.sleep(0.1)
                    tap(pad, "a")
                    time.sleep(0.35)
                    tap(pad, "a")
                    boxes_hit += 1
                else:
                    side_b = globals().get("BOX_SIDE", 1)
                    before_b = bdist
                    hold(pad, "left" if side_b > 0 else "right", 0.18)
                    hold(pad, "up", 0.7)
                    time.sleep(0.2)
                    after_b = state(pad).get("player") or {}
                    now_b = math.hypot(bx - float(after_b.get("x") or 0), bz - float(after_b.get("z") or 0))
                    if now_b > before_b - 1.0:
                        box_misses += 1
                        if box_misses >= 4:
                            globals()["BOX_SIDE"] = -side_b
                            box_misses = 0
                    else:
                        box_misses = 0
                moved += 1
                continue

            warps = [e for e in (now.get("entities") or [])
                     if "Warp" in str(e.get("class")) and e.get("x") is not None and e.get("z") is not None]"""

count = text.count(old)
print("warp anchor count:", count)
if count != 1:
    raise SystemExit("warp anchor not unique - refusing to guess")
text = text.replace(old, new, 1)

# counters
old_decl = "    warped, warp_misses, warp_reported = 0, 0, None   # level exits entered, approach misses, last report"
new_decl = ("    warped, warp_misses, warp_reported = 0, 0, None   # level exits entered, approach misses, last report\n"
            "    boxes_hit, box_misses = 0, 0                        # containers destroyed, approach misses")
if text.count(old_decl) == 1:
    text = text.replace(old_decl, new_decl, 1)
    print("box counters declared")

# ---- 2. rares in arming ------------------------------------------------------------------------------------------
old_arm = """    log(f"  difficulty: {set_ultimate(pad)}")"""
new_arm = """    log(f"  difficulty: {set_ultimate(pad)}")
    for payload in ({"op": "floor_rares", "on": True, "character_class": "HUmar"},
                    {"op": "enemy_drops", "on": True,
                     "codes": ["009d00", "003200", "004400", "000100", "000200"]}):
        answer = mods(pad, payload)
        log(f"  {payload['op']}: {answer.get('state')} {str(answer.get('error'))[:60]}")"""
if text.count(old_arm) == 1:
    text = text.replace(old_arm, new_arm, 1)
    print("rares added to arming")
else:
    print("arm anchor count:", text.count(old_arm))

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
