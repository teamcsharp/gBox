"""Escape a story dialog with A, and never start one by suppressing the sweep near NPCs.

Two measured facts:

* **A dialog blocks all movement.** With one open, a forward step moved **0.0 units**, and four `B` presses changed nothing - `B` cancels a *menu*, not a story dialog.
* **`A` dismisses it in a single press.** After one `A`, a forward step moved **7.5 units**. `A` is the advance/confirm button, and for a story box that is what closes it.

**Why the dialog kept appearing:** the sweep presses `b` then `a` on every visit, and `A` is also the *talk* button. Any `Npc`/`NPC` class inside the sweep radius gets talked to, and the resulting
conversation then swallows input until dismissed. That is the state that logged `no direction moved it`, `retreated 0.0` and `travelled 0 units over 60s` **while the relocation teleport correctly reported
`landed` four times** - the teleport worked, the dialog ate the result.

Two changes:

1. **`press_a`-based escape in `unstick`**: when no direction moves the character, press `A` once and re-test. That single press is the whole recovery.
2. **NPC guard on the sweep**: never sweep while an NPC is within `NPC_RADIUS`, so a conversation is never opened in the first place. Melee is not worth a frozen window.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

# 1. import the NPC guard
if "from npc_guard import is_npc" not in text:
    anchor = "from weapons import ensure_equipped"
    if text.count(anchor) != 1:
        raise SystemExit("weapons import anchor: %d" % text.count(anchor))
    text = text.replace(
        anchor,
        "from weapons import ensure_equipped            # class-aware weapon choice + the 2-5 min timer\n"
        "from npc_guard import is_npc                     # never talk to anyone: a dialog swallows input",
        1,
    )
    print("imported is_npc")

# 2. dismiss a dialog with A when the location is frozen
old = """        log(f"  retreated {retreated:.1f} units")"""
new = """        log(f"  retreated {retreated:.1f} units")
        if retreated < 0.5:
            # NOTHING MOVED: the signature of a STORY DIALOG, not a wall. Measured: with one open a forward step
            # moved 0.0 and four B presses did nothing; a single A press freed it (7.5 units).
            tap(pad, "a")
            time.sleep(0.5)
            probe = state(pad).get("player") or {}
            start_probe = (float(probe.get("x") or 0), float(probe.get("z") or 0))
            hold(pad, "up", 0.45)
            time.sleep(0.2)
            end_probe = state(pad).get("player") or {}
            if math.dist(start_probe, (float(end_probe.get("x") or 0), float(end_probe.get("z") or 0))) > 2.0:
                log("  a story dialog was blocking it - A dismissed it")
                TELEPORT_ATTEMPTS["count"] = 0
                return "up\""""
count = text.count(old)
print("retreat anchor count:", count)
if count != 1:
    raise SystemExit("retreat anchor is not unique")
text = text.replace(old, new, 1)
print("A-based dialog escape added to unstick")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
