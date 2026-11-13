"""Break boxes from inside the reach, not from the edge of it.

The loop reaches **14 units** of a box and starts sweeping - and destroys nothing (59 boxes, 0 broken across a 16-sample window). The test that *did* break one had the character placed **7 units** away.

So the swing's reach is shorter than 14. That matches the game's own numbers: the attack envelope in `pso_coop_combat` is **~12 units** horizontal, and the body blocks approach at ~16.7, so the window where
a swing connects is roughly **7-12 units** - and 14 is outside it. Sweeping at 14 is exactly the "swing into empty air" failure, just at a different distance.

Fix: only sweep when the box is within **8 units**, and approach otherwise. 8 sits comfortably inside the 12-unit envelope with margin for the character's own radius, and matches the distance the
successful test used.

The same reasoning applies to the enemy branch, which uses **15.5** - also outside the 12-unit envelope. That is lowered to **10** for the same reason: swinging outside the envelope cannot connect no matter
how well the cone is swept.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

old_box = """                if bdist <= 14.0:"""
new_box = """                if bdist <= 8.0:          # inside the ~12-unit attack envelope; 14 was outside it and never connected"""
count = text.count(old_box)
print("box threshold anchor count:", count)
if count == 1:
    text = text.replace(old_box, new_box, 1)
    print("box sweep range 14 -> 8")

old_enemy = """            if distance <= 15.5:"""
new_enemy = """            if distance <= 10.0:      # inside the ~12-unit envelope - 15.5 was outside it"""
count = text.count(old_enemy)
print("enemy threshold anchor count:", count)
if count == 1:
    text = text.replace(old_enemy, new_enemy, 1)
    print("enemy sweep range 15.5 -> 10")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
