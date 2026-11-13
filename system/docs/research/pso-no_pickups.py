"""Do not pick items up. Keep the bag empty, as the operator asked.

Their words: *"dont pick up items if the inventory is full. thats the point dont do that. Also dont fill up the inventory. Keep the inventory empty. The character has unlimited scape dolls so dont
carry monomates, trimates, monofluid, difluid or anything except items for the game"*.

The loop had no pickup policy at all - the reticle rule pressed `A` at **anything** actionable within 12 units, which included loose drops, so every broken box and every enemy kill added to a bag
that was already full. That is exactly how a 30-slot inventory fills up: not in one burst, but by pressing at pickups for hours.

So loose items are now **excluded from the reticle rule**: `TItem*` classes (`TItemMoney`, `TItemEquipBase`, and the rest of the family) are skipped. The item stays on the floor for the operator,
the bag stays empty, and nothing is ever "not picked up because it was full" because nothing is picked up at all.

Enemies, boxes, traps, keys and doors are unaffected - those are the actionable things worth pressing at, and they are not items.

The weapon gifts stay, because a HUmar with no weapon cannot fight: three `give` calls once per session (arm-once) are the minimum needed, and the operator's objection was to **consumables** and to
the bag filling with loot.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

old = """                if not (kind == "enemy" or kind == "object" or kind == "gate"):
                    continue"""
new = """                if not (kind == "enemy" or kind == "object" or kind == "gate"):
                    continue
                # NEVER pick items up: TItemMoney / TItemEquipBase and the rest of the loose-drop family are skipped.
                # The operator wants the bag empty - the character has unlimited Scape Dolls and needs no monomates,
                # trimates, monofluids or difluids - and a full bag is what stopped pickups working in the first place.
                if candidate_class.startswith("TItem") or candidate_class.startswith("TObjItem"):
                    continue"""
count = text.count(old)
print("reticle filter anchor count:", count)
if count != 1:
    raise SystemExit("reticle filter not unique - refusing to guess")
text = text.replace(old, new, 1)
print("loose items are no longer picked up")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
