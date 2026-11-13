# Doors unlocked in RAM as it walks — the operator's requirement

## What was asked

> *"Not only does it need to flip switches, it needs to be able to flip these switches with its mind to just unlock doors as it walks up to them. I want it to just unlock doors as I walk up to them in the game."*

## What was wrong before

Two faults, both visible in the logs:

1. **It stopped 12 units from the key and pressed A from there.** The interaction range is much shorter — the green triangles in the operator's screenshots appear only when the game considers
   something action-able, which is close range and facing. Ninety steps of pressing A at 12 units did nothing.
2. **The flag write went to the wrong floor.** Arming logged `gates: floor 0` because it read `STAGE_FLAG_GROUP_PTR` while still in the city. The Forest is floor **1**, so the unlock landed on the
   wrong floor and the Forest doors stayed shut.

## What it does now

**`unlock_floor()`** — called on a cadence **inside `play()`**, so it always reads the floor the character is standing on:

* read the floor from `0x805D5FC0`;
* if that floor's 32-byte group at `0x80515CC8 + floor*32` is not already `0xFF`, write it;
* **verify the read-back** and report.

Doors recompute their open state from these flags every frame — `pso_coop_gates`: *"native_state (+0xAC) is futile — it is recomputed each frame FROM this flag"* — so the write **is** the unlock.
No proximity, no target, no press.

## Verified

Standalone, driving the bot to the door:

```
floor unlock at start: floor 1 unlocked
[  0] floor 1 already open
*** CROSSED: room 14 -> 11 at step 1 ***
```

In the running loop:

```
[21:54:15]   gates: floor 1: gates already open
[21:55:03]   doors: floor 1 already open
[21:57:22]   doors: floor 1 already open
```

## Recognition comes from memory, not vision — as required

The bot does not look at the screen. It reads the entity table and classifies with the game's own documented model, `pso_coop_gates.forward_candidates`:

```
SWITCH_CLASSES = {'TLazerFenceSw', 'TObjDoorKey'}
DOOR_CLASSES   = {'TObjDoor', 'TObjLazerFenceNorm', 'TOBarrierEnergy01'}
```

> *"Switches/panels sort before doors so the gate is opened before it is crossed; nearest-first within a class."*

Measured against the live entity table, that is exactly what is there:

```
 13.0  gate  TObjDoorKey  SWITCH  (6.6, 362.4)
 98.7  gate  TObjDoor     DOOR    (53.2, 290.5)
```

and `TObjDoorKey` is in `SWITCH_CLASSES` — **the key the bot was ignoring was already classifiable from memory.** It just was not being asked.

## Still open — and it is now only one thing

`TObjEneBeast untouched after 8 swings` at **closest approach 12.1** — inside the game's envelope, `always_hit` on, and **still no damage**. The inventory refused `003200` and `004400` earlier with
"Not enough inventory slots", so the equipped weapon is the remaining suspect.

Everything else in the run is behaving: `left 2 unwinnable` (the combat budget leaves what it cannot hurt), `unstick` freeing the character repeatedly (1.4 to 33.3 units), no stderr.
