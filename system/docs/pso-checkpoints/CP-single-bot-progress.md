# One bot, 1197 units of real travel, and boxes that will not break yet

## With the duplicate gone, the movement is finally clean

```
moved 1197 units | rooms [8, 12] | room changes 4
```

**1197 units in two minutes, four room changes.** That is more travel in one window than any previous run managed across several, and it is what a single controller with a trustworthy view
of the world looks like. The same window shows the unstuck working:

```
[23:20:15]   wedged at (426,29,-18) - relocating +15,+0 at the same height
[23:20:21]   relocation freed it (34.1 units)
```

So the two-bot fault really was the thing making the character appear frozen: two loops disagreeing about where it was, each concluding it was stuck.

## Boxes: the honest state

**55 containers in the room, 0 destroyed.** Tested directly rather than inferred:

* teleported to **8.0 units** from the nearest `TObjContainerItem`;
* pressed `b` then `a` **ten times**;
* box count: **55 before, 55 after** - unchanged;
* and the profile reports the container's `hp` as **`None`**, so the box's own damage state is not exposed to the semantic layer at all.

**So either the swings are not connecting with the box, or boxes are not damageable through the `hp` path the profile reads.** The operator's own screenshot showed green triangles on a box, which means the game considers it actionable - so the likely answer is **facing**: the teleport put the character 8 units away but at an arbitrary heading, and the attack only connects inside the game's 8° aim cone. Enemies do take damage when that cone is satisfied (`TObjEneLappy HIT: 30 -> 1`).

**The next test is therefore: turn to face the box before swinging** - and the honest way to do that is the same distance hill-climb that closes on enemies, since `heading_deg` cannot be trusted for steering.

## Also true this round

```
[23:19:40]   difficulty: Normal (already, hp_max 68)
[23:19:41]   floor_rares: succeeded
[23:19:43]   enemy_drops: succeeded
[23:19:43]   gates: floor 1: gates already open
[23:19:43]   NOTE from operator: kill the wolves in this room
[23:19:43]   note internalized: prioritising enemies
```

and the one remaining inventory casualty:

```
give 009d00 / 003200 / 004400: failed "Not enough inventory slots"
```

This session has been alive for hours and its inventory is full from repeated gifting; `survival` still succeeded. **A fresh session clears it**, and the arm-once logic prevents the accumulation that
caused it.

## What the environment lesson bought

Twice this session "the bot is broken" was really **the app being down**, **an orphaned Dolphin holding the worker**, and here **a duplicated process from a python launcher**. Checking the
environment first is now the habit, and it turned a "the character is permanently stuck" conclusion into a one-line root cause.
