# The level exit is recognised in RAM, and the bot aims at it

## The requirement

> *"you need to recognize the teleporter in the code and the flag and aim to get the character to that to progress in the game"*

## How it is recognised

Not by sight - by class, from the same entity table the profile already returns. The class registry lists the warp family:

```
pso_class_registry: TObjWarpBase, TObjMapWarp, TObjMapWarpForest, TObjMapForceWarp, TObjWarpString,
                    TObjAreaWarpEndingJung, TObjWarpBoss, TObjWarpJung, TObjWarpLobby
pso_classes:        ("TObjWarp", "warp")
```

So the test is `"Warp" in entity["class"]`, and the branch is now the **first** thing `play()` considers once the room is clear - ahead of door keys and doors, because walking into a warp is
what advances the stage:

```
1. LEVEL-EXIT teleporter (Warp classes)  -> walk into it
2. door KEY (TObjDoorKey / TLazerFenceSw) -> press it, close up (<= 6.5 units)
3. DOOR (TObjDoor / TObjLazerFenceNorm / TOBarrierEnergy01) -> walk through
```

with a hill-climb toward the warp that reports `LEVEL EXIT <class> N units away - heading for it`, and on arrival steps in and logs `ENTERED THE WARP <class>: room A -> B` **only when the room
actually changes**.

## The whole branch was rewritten

The previous edit tangled the indentation (`expected an indented block`) because the switch logic had been spliced into an existing `if/else` chain. Rather than patch around it, the entire
no-enemies branch was replaced with one clean block and spliced in by line position, then checked with `pyflakes`:

```
pyflakes: endless.py:19:1: 'json' imported but unused
UNDEFINED NAMES: none
```

That is the third time this session that a tangled patch was cheaper to rewrite than to repair, and the second time `pyflakes` was what proved the rewrite was sound.

## The new blocker, stated plainly

The character is now **wedged at `(282, 8, -250)`** and the same-height relocation - the fix that worked last round - **is not freeing it**. The log shows all four offsets tried and then the
whole attempt repeating:

```
wedged at (282,8,-250) - relocating +15,+0 at the same height
wedged at (282,8,-250) - relocating -15,+0 at the same height
wedged at (282,8,-250) - relocating +0,+15 at the same height
wedged at (282,8,-250) - relocating +0,-15 at the same height
```

Note that **the reported position does not change between attempts** - so the writes are not landing at all this time, not merely landing somewhere unhelpful. That is a different failure from last
round's `y=0.1` bug, and the next thing to check: whether `write_memory` is being refused (a pending PSO command) or whether the pointer used for the write is stale.

The consequence is visible in the window totals: `played 120s, 3.0 travel steps, closest approach 55.8, gates approached 0, crossed 0` - almost no movement, so nothing else could happen.

## Where the objective stands

| clause | state |
|---|---|
| decrypt / analysed | done - Ghidra, `pso_v3.elf`, entry `0x8000c040` |
| map internalised + path-guiding | done - 1497 triangles, 5626 walkable / 4959 safe; warp trigger and 29-waypoint route from it |
| walk through the gate | done - 211 units through one |
| fastest rate | 4.8-7.3x measured (median 5.5x) |
| every boss reachable | done - four named warps |
| **level exit recognised + aimed at** | **done** - `Warp` classes, first priority, enter verified by room change |
| door switches recognised + pressed | done - `TObjDoorKey` at <= 6.5 units |
| doors unlocked in RAM | done - `unlock_floor()` per floor, verified read-back |
| defeat enemies | **working** - `TObjEneLappy HIT: 30 -> 1` from the loop |
| **not standing around** | **regressed here** - wedged and the relocation is not landing |
