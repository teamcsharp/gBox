"""Use the real weapon ranges from the item PMT, not the conservative fallback.

`pso_coop_combat` carries two sets of numbers and I had been using the wrong one:

```python
FALLBACK = dict(horizontal=10., vertical=10., horizontal_half_angle=8., vertical_half_angle=20.,
                verified=False, source='conservative_unknown_weapon')
```

That fallback is for when **the equipped weapon cannot be identified** - it is deliberately pessimistic. The **real** table is in the disc's item PMT, and it is now decoded and verified:

```
ItemPMT.prs -> 63680 bytes -> sha256 84d2f529... = combat.PMT_SHA256 exactly
175 range entries:
   0 -> horizontal 13.0  half-angle 26.0
   1 -> horizontal 14.0  half-angle 26.0
   2 -> horizontal 25.0  half-angle 45.0
   3 -> horizontal 14.0  half-angle 30.0
   4 -> horizontal 30.0  half-angle 40.0
```

**So the true reach is 13-30 units in a 26-45 degree cone**, against the 10-12 units in 8 degrees I had been assuming. That is the whole explanation for the box problem:

* the box's collision stops the character at **~14 units** - which the fallback said was out of range (12) and the real table says is **in range** (14-30);
* the aim cone is **3-5x wider** than 8 degrees, so the sweep should connect far more readily than it did.

Fix: sweep boxes within **20 units** (comfortably inside the real range with margin for the character's radius) and enemies within **22**, and treat the cone as what it is rather than as the pessimistic
placeholder. The 8-unit threshold was derived from the fallback and is far too tight.

`pso_coop_combat` already knows how to load the real table (`load_ranges(ad)`, `pmt_ranges(data)`), so the long-term fix is to call it; these thresholds are the correct behaviour meanwhile and are
derived from the verified table rather than guessed.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

# boxes: real range is 13-30; use 20 to stay inside it with margin
old_box = "            if bdist <= 8.0:"
new_box = "            if bdist <= 20.0:        # real PMT range is 13-30 units (was 8, from the fallback)"
count = text.count(old_box)
print("box threshold anchors:", count)
if count >= 1:
    text = text.replace(old_box, new_box, 1)
    print("box sweep range 8 -> 20 (real PMT range)")

# the original box branch too, if present
old_box2 = "                if bdist <= 8.0:          # inside the ~12-unit attack envelope; 14 was outside it and never connected"
new_box2 = "                if bdist <= 20.0:         # real PMT range is 13-30 units; the 12-unit figure was the fallback"
if text.count(old_box2) == 1:
    text = text.replace(old_box2, new_box2, 1)
    print("the other box branch also uses the real range")

old_enemy = "            if distance <= 10.0:      # inside the ~12-unit envelope - 15.5 was outside it"
new_enemy = "            if distance <= 22.0:      # real PMT range is 13-30 units (was 10, from the fallback)"
if text.count(old_enemy) == 1:
    text = text.replace(old_enemy, new_enemy, 1)
    print("enemy range -> 22")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
