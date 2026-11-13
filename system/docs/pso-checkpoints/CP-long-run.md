# A long run: exploration is solid, and the boss wall is character power

## What a 100-second sample shows

```
 0: room 7  pos ( 64.1, -19.6) hp 68 | enemies 0
 4: room 7  pos ( 44.6, -41.2) hp 68 | enemies 0
 8: room 7  pos ( 64.9, -20.2) hp 68 | enemies 0
12: room 10 pos (-31.3, 164.0) hp 68 | enemies 0
16: room 10 pos (-21.1, 170.4) hp 68 | enemies 0

moved 558 units | rooms visited [7, 10, 11] | enemy-count drops 0
```

**558 units in about a hundred seconds, three rooms crossed, never standing still.** That is the exploration clause holding up over a long run, not just a short test. The rooms it crossed were
**empty** - the enemies had already been fought - which is why the kill counter did not move here.

## The boss wall, measured again

`boss_warp target=dragon` succeeded and `TBoss1Dragon` was present at **1300 HP**. Seventy steps of attack attempts later:

```
 0: boss hp 1300 d 270.6 aim  -13.5 | me hp 68
 6: boss hp 1300 d  35.9 aim +118.9 | me hp 68
18: boss hp 1300 d 283.2 aim -122.5 | me hp 46
24: boss hp 1300 d 174.0 aim  +18.6 | me hp 22
66: boss hp 1300 d 317.4 aim -155.7 | me hp 12
```

**The boss never lost a point.** The aim column is the reason: it swings **-172 to +186**, because the Dragon throws the character around - there is no window where the 8° cone holds long enough
to swing inside it. `always_hit` removes the accuracy roll but not the range-and-facing requirement, so it cannot help here.

**And the character cannot outlast it either**: 68 HP against a boss that takes it to 12 in a minute. The Scape Doll keeps it alive, but reviving at 12 HP next to a 1300 HP boss is not progress.

## So the honest split

| what | state |
|---|---|
| **movement** | **fixed and reliable** - the `release_all` rule; 99 units across five directions, 558 units of travel |
| **exploration** | **working** - rooms 7, 10 and 11 crossed unaided |
| **killing normal enemies** | **working** - a verified kill (`hp 41 -> 20 -> dead` at `d 12.0`, `aim +2.8`, B then A); the loop also took a field from 2 enemies to 1 |
| **reaching any boss** | **working** - four named warps |
| **defeating a boss** | **not at this power level** - 1300 HP, knocked around, 68 max HP, and `stat hp`/`atp`/`dfp`/`evp` are all refused with *"cannot be represented with the current equipment and level"* |

**PSO's own answer to this is levelling**, and the loop is what does it: it keeps launching, arming, warping to fields and fighting. The character is level 5; the Dragon is level 11 content. The
honest path is to let it fight normal enemies until its level and drops close that gap, and the mechanics to do that are now in place and verified.

## A loop detail worth fixing next

`go_to_field()` requires **>60 entities** to count as a field, but a **boss arena has 7** - so when the warp lands in one, the check fails, logs "could not reach a field", and the bot plays there
anyway. The predicate should accept a boss arena (few entities, `Boss` in a class name) as a valid destination instead of treating it as a failed warp.
