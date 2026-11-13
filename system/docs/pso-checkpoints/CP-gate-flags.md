# Flipping door flags in RAM — delivered

## What the operator asked for, and why it works

> *"i want the bot able to flip those flags with its mind via ram"*

`pso_coop_gates.py` documents the native stage-flag array, reverse-engineered from the barrier's own accessor at `0x80229220`:

```
STAGE_FLAG_BASE      = 0x80515CC8     # 18 groups (one per floor 0..17) x 32 bytes, MSB-first
STAGE_FLAG_GROUP_PTR = 0x805D5FC0     # holds the current floor == the accessor's group index
STAGE_GROUP_SIZE     = 32
```

and the line that makes it a switch rather than a mirror:

> **"native_state (+0xAC) is futile - it is recomputed each frame FROM this flag."**

The door does not store "open" anywhere writable. It **asks this flag every frame**. So setting the bit *is* flipping the switch - no button, no target, no approach needed.

## Measured, end to end

```
STAGE_FLAG_GROUP_PTR -> 0x1 (1)                                   <- Forest, floor 1
group at 0x80515CE8: 00 00 00 00 ... (32 zero bytes)              <- every gate shut
bits set: []
writing ff ff ff ... (32 bytes) ...
write: succeeded
after: ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff
bits set now: [0, 1, 2, ... 253, 254, 255]
VERIFIED
```

So the group was read (all clear), written (all `ff`), and **read back identical** - all 256 flags for floor 1 now set.

## And it is part of arming now

```
[21:28:41]   gates: floor 1: gates already open
```

The `open_all_gates()` step runs once per session in `arm()`, after the weapons. It reads the floor from `0x805D5FC0`, builds the group address `0x80515CC8 + floor*32`, skips the write if the
group is already all `ff`, and **verifies the read-back** rather than assuming the write landed - which is exactly the mistake that cost this session a lot of time with the teleport.

## Also in place and visible in the same window

* **combat budget**: `TObjEneBeast untouched after 8 swings - leaving it and heading for a gate` - the bot no longer stands in front of something it cannot hurt while the way out is behind it;
  the run reported **`left 3 unwinnable`**;
* **closest approach 11.9** - inside the game's 12-unit attack envelope;
* **gates approached 1** - the gate objective is running;
* **unstick freeing it** at 48.6 and 8.6 units.

## Honest gaps

* **`crossed 0`** - a gate was approached but no crossing was confirmed, because a crossing only counts when the room actually changes; the A-at-the-gate press exists but has not yet produced a
  verified room change in a window I have observed.
* **`TObjEneBeast untouched after 8 swings` at 11.9 units** - inside the envelope and still no damage. That is now the single most interesting failure: range and facing are satisfied, `always_hit`
  is on, so either the weapon is not what the game thinks it is (this session could not take `003200` or `004400` - **"Not enough inventory slots"** - so the inventory state is suspect again), or
  the swing needs a target lock the bot is not establishing.
* Boss wall unchanged: 1300 HP + knockback vs 68 max HP.
