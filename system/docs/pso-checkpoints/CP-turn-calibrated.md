# The turn model was wrong by 4x - and the steerer still does not converge

## The calibration was the real fault

Two input measurements, both from a calm room, both contradicting what every approach in this session assumed:

```
TAP (instant down+up):
  left  tap 2/3/4: +11.3  +12.0  +10.5     <- ~11 deg per tap
  right tap 2/3/4: -10.4   -5.6   -7.2      <- ~-8 deg per tap

HOLD:
  left 0.15s: +43.4   left 0.30s: +46.2   left 0.45s: +47.7     <- ~46 deg whatever the duration
  up   0.5s : 9.9 units        up 1.0s : 0.0 units              <- long walks do not happen
```

**A direction press is a fixed rotation, not a rate** - and a **tap** is about **10 degrees** while a **0.15-0.45 s hold** is about **46**. Every approach I wrote used `hold(..., 0.16)`, so **each correction over-rotated by four times the error** and the character careened. **That is the zigzag the operator has been watching**, and it was never a pathfinding problem - the map routes fine (`route=yes`) and the targets are known.

`DEG_PER_TAP` is now **10.0** (was 46) and the tap cap raised to 20 so a 180-degree correction is possible.

## And it still does not converge

Tested directly against a box **229 units** away:

```
 0: pos (202,  6) heading 114.7 | dist 254.1
 1: pos (173,-69) heading 110.4 | dist 288.9
 2: pos (250, 62) heading  32.2 | dist 256.6
 3: pos (239, 99) heading 345.0 | dist 251.8
 4..11: pos (239, 99) heading 345.0 | dist 245.5     <- frozen
```

It moves, wanders, and then **freezes** - the same wedging that has recurred all session. So the calibration fix is **necessary but not sufficient**: the steerer now turns the right amount, and the character still does not close on the target.

## Honest position

**What is proven working:**

* **targets are known from RAM** - boxes, enemies, keys, doors and warps are all identified by class with positions;
* **the map routes** - A\* over 90,986 Forest safe cells, `route=yes` to a box, 162 -> 14 units;
* **the attack connects** - real PMT ranges (13-30 units, 26-45 deg); **boxes 59 -> 56**;
* **the turn model is now correct** - ~10 deg per tap, measured.

**What is not working:** the **execution** of a route - turning and stepping without wander or freeze. The turn was one cause (4x over-rotation, now fixed); the leftover is the wedging, which recurs at ~14 units from boxes and randomly elsewhere, and which the relocation unstuck only sometimes fixes.

**The next measurement should be the freeze itself**, not the steering: log what the character is doing when it stops accepting movement - the same instrumented approach that found the box-collision answer. **Guessing at steering maths while the character intermittently stops walking would be treating a symptom.**
