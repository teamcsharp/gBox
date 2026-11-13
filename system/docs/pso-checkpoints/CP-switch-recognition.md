# The bot now recognises door switches from RAM — and it landed a hit

## The requirement

> *"The bot needs to be able to detect and understand that there are door switches. So if there's a door switch into proximity, the bot needs to know that. It needs to understand in the matrix via the code of the RAM that there is a door key that has to be pressed."*

## What was missing

The loop walked to the nearest `gate` **by distance only**. It could not tell a `TObjDoorKey` from a `TObjDoor`, so it treated a switch as a place to stand and pressed A from 12–20 units away, where the press
does nothing. The information was there in RAM the whole time — the entity's **class**.

## What it does now

`play()` classifies the room's forward affordances with the game's own model, `pso_coop_gates.forward_candidates`, read from the live entity table:

```
SWITCH_CLASSES = {'TLazerFenceSw', 'TObjDoorKey'}          -> must be PRESSED
DOOR_CLASSES   = {'TObjDoor', 'TObjLazerFenceNorm', 'TOBarrierEnergy01'}   -> walked through
```

and the branch is different for each:

* **a switch**: log `DOOR KEY <class> detected N units ahead - going to press it`, hill-climb to within **6.5 units**, then `b` + `a` and log `pressed the door key ... at N units`;
* **a door**: walk through at 18 units, and only count a crossing when the **room actually changes**;
* nothing classifiable: short sweep so the next sample can find something.

The 6.5-unit threshold is the fix for the "stands in front of the key and never presses it" complaint: the previous 20-unit approach was outside the game's interaction range.

## And a hit landed

```
[21:59:47]   TObjEneLappy HIT: 30 -> 1
```

**The first damage from the loop itself**, and it came in the same run where every gift succeeded — `give 009d00`, `give 003200`, `give 004400` and `survival` all `succeeded`. The earlier sessions that
reported "untouched after 8 swings" were the ones where the inventory refused a weapon, which is consistent with the hypothesis that the character was effectively unarmed.

`closest approach 11.5` and `12.1` in the same windows confirm the approach is putting the character inside the game's envelope.

## Also verified in the run

```
[21:59:28]   gates: floor 1: gates already open
[22:00:24]   doors: floor 1 already open
[22:02:23]   doors: floor 1 already open
[21:59:47]   TObjEneLappy HIT: 30 -> 1
[22:00:29]   TObjEneBeast untouched after 8 swings - leaving it and heading for a gate
```

no stderr, 17–22 travel steps per window, and the combat budget leaving what it cannot hurt.

## Honest gaps

* **`gates approached 0, crossed 0`** in these windows — no switch was inside the 70-unit detection radius, so the new key-press path has not yet fired in a window I observed. The classifier itself is
  proven (`TObjDoorKey` at 13.0 units was found when I drove it by hand, and that run crossed room 14 -> 11).
* `TObjEneBeast untouched after 8 swings` still appears alongside the hit — different enemies, and the budget correctly gives up on those.
* Boss wall unchanged: 1300 HP + knockback vs 68 max HP.
