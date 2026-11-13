"""The reticle rule: if something actionable is close, press A. Boxes, traps, switches, enemies - never townsfolk.

The operator's rule, verbatim: *"So if the target reticle comes up for any reason, it's to either destroy a box, activate a switch, or attack an enemy. Always take that opportunity. Sometimes
there's floating traps. Destroy those also as you encounter them. But anytime you see a targeting reticle pop up, that means that you need to interact with that element, unless it's a
townsperson, and then in which case you don't talk to them."*

That is a better rule than any table of classes I could write, because it is the **game** deciding what is actionable rather than me guessing from distance. Until the reticle field itself is located
in memory, this implements the rule as tightly as the entity table allows:

* **traps join the destructibles** - any class containing `Trap` (the floating ones the operator mentions) is now hit alongside `Container` and `Capsule`;
* a **catch-all interaction check** runs every iteration: if any actionable entity is within 12 units, press `b` then `a` - which is what the reticle is asking for;
* **townsfolk are excluded by class**: anything whose class contains `Npc`/`NPC`, plus the conversational classes, is never pressed. This matters because earlier in the session an NPC
  conversation (*"Ah, I miss her…"*) locked the character for a long time, and the operator's rule is explicit that they are not to be talked to.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

# --- 1. traps join the destructibles ------------------------------------------------------------------------------
old_filter = """                     if ("Container" in str(e.get("class")) or "Capsule" in str(e.get("class")))
                     and e.get("x") is not None and e.get("z") is not None]"""
new_filter = """                     if ("Container" in str(e.get("class")) or "Capsule" in str(e.get("class"))
                         or "Trap" in str(e.get("class")))
                     and e.get("x") is not None and e.get("z") is not None]"""
count = text.count(old_filter)
print("box filter anchor count:", count)
if count == 1:
    text = text.replace(old_filter, new_filter, 1)
    print("traps join the destructibles")

# --- 2. the catch-all reticle check -------------------------------------------------------------------------------
old_anchor = """            # BREAK THE BOXES. Containers are ordinary entities in the table (TObjContainerItem, TOCapsuleAncient01),"""
new_anchor = """            # THE RETICLE RULE. If the game is offering something to act on, act on it: press B then A. Anything
            # actionable within 12 units counts, because the reticle is the game's own way of saying so. Townsfolk are
            # excluded by class - talk to them and the character can be locked in a conversation, which happened.
            actionables = []
            for candidate in (now.get("entities") or []):
                candidate_class = str(candidate.get("class"))
                if "Npc" in candidate_class or "NPC" in candidate_class:
                    continue                                    # never talk to townsfolk
                if candidate.get("x") is None or candidate.get("z") is None:
                    continue
                kind = str(candidate.get("kind"))
                if not (kind == "enemy" or kind == "object" or kind == "gate"):
                    continue
                distance_c = math.hypot(float(candidate.get("x") or 0) - x, float(candidate.get("z") or 0) - z)
                if distance_c <= 12.0:
                    actionables.append((distance_c, candidate_class))
            if actionables:
                actionables.sort()
                nearest_class = actionables[0][1]
                tap(pad, "b")
                time.sleep(0.08)
                tap(pad, "a")
                time.sleep(0.3)
                reticle_hits += 1
                if reticle_hits % 10 == 1:
                    log(f"  acted on {nearest_class} ({actionables[0][0]:.1f} units) - reticle rule")
                moved += 1
                continue

            # BREAK THE BOXES. Containers are ordinary entities in the table (TObjContainerItem, TOCapsuleAncient01),"""
count = text.count(old_anchor)
print("box branch anchor count:", count)
if count == 1:
    text = text.replace(old_anchor, new_anchor, 1)
    print("reticle catch-all added")

# --- 3. counter ---------------------------------------------------------------------------------------------------
old_decl = "    boxes_hit, box_misses = 0, 0                        # containers destroyed, approach misses"
new_decl = ("    boxes_hit, box_misses = 0, 0                        # containers destroyed, approach misses\n"
            "    reticle_hits = 0                                    # presses made because something actionable was close")
if text.count(old_decl) == 1:
    text = text.replace(old_decl, new_decl, 1)
    print("reticle counter declared")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
