# Boxes stop the character at ~14 units - and that is outside the melee reach

## What the measured approach revealed

With a real hill-climb on measured distance, the pattern is unambiguous:

```
box TObjContainerItem d=14.6 -> 14.6 side=+1 route=yes
box TObjContainerItem d=14.0 -> 14.0 side=+1 route=yes
box TObjContainerItem d=14.1 -> 14.1 side=-1 route=yes
box TObjContainerItem d=14.2 -> 14.2 side=-1 route=yes
```

**At 14 units the character does not move at all** - every side, every time. It is not oscillating any more; it is **blocked**. The farther samples confirm the approach itself works (122.1 -> 95.4, and 210 away when it overshot), so the machinery is fine and **14 units is a wall**.

## And that explains the earlier success and the present failure together

The controlled test that broke a box placed the character **7 units** away - **by teleport**. That bypassed collision entirely, which is why 7 worked there and cannot be reached by walking.

So the real constraint is:

* **the box's own collision stops the character at ~14 units** - the same family as the enemy body that blocks at ~16.7;
* **the melee envelope is ~12 units** (`pso_coop_combat`: horizontal range 12, half-angle 8);
* **14 > 12**, so a melee swing from where the character can stand **cannot connect**.

**The attack was never mis-aimed here. It is out of range by about two units, and the collision model decides that.**

## What that means for the fix

**Melee cannot break boxes.** Not with better aiming, not with more sweeping - the character cannot stand close enough. The options are:

1. **a ranged weapon** - the bot already equips `RED HANDGUN` (`004400`, ATA 46) as the third gift, so it is the **active** weapon. A handgun's range is far beyond 12 units, which is exactly what this situation needs. If the sweep still does not connect, the question becomes whether the handgun's shots require a line of sight the box blocks.
2. **verify the envelope actually in force** - the fallback in `pso_coop_combat` is `horizontal=10` when the weapon cannot be independently identified, and a *pistol* has a different table entry from a sword. The number that matters is the range for **the equipped item**, which the PMT holds.
3. **accept that boxes are out of reach and stop prioritising them** - the operator asked to practice on boxes, but if the collision model makes them unbreakable from where a character can stand, the practice should be on enemies the ranged weapon can reach.

## Honest position

**Nothing about this is a recognition, mapping or steering failure any more.** The map routes to a box (`route=yes`), the approach converges until blocked, and the block is the game's collision at 14 units against a 12-unit melee reach.

**The next measurement is whether the equipped weapon is ranged and what its range actually is** - which the item PMT answers, and which decides between option 1 and option 3 above.
