# The transform question is settled: the world is 117x one room

## The measurement

```
live entities: 125
  x  -425 .. 3125    span 3550
  z -2108 ..  356    span 2464

collision bounds per layout:
  map_cave01_00   359 x 257      map_cave01_03   195 x 147
  map_cave01_01   347 x 276      map_cave01_04   230 x 168
  map_cave01_02   393 x 240      map_cave01_05   347 x 277

mean room footprint:      74,296 sq units
live world extent:     8,747,938 sq units
ratio:                       117.7x one room
```

**No layout's bounds contains more than 8 of the 125 entities.** Every candidate covers roughly six percent of the world.

## What this proves

**A layout is a set of room instances placed far apart, and each collision file is ONE instance's geometry.** The live cave area spans 3,550 by 2,464 units; a room's
collision spans about 360 by 260. So the area holds on the order of a hundred room instances, and **no single collision file can cover it under any offset**.

That is why the entity fit returned 9 of 125 with no lead over its runner-up: **there is no offset to find.** The search was not failing - the model it assumed was wrong.

## The full model, now evidenced by four independent lines

| observation | establishes |
|---|---|
| rooms 50-53 share one `set_id`, identical bounds | a template is instantiated more than once |
| `set_id` differs across layouts for the same id | `set_id` is not a stable template key |
| no door/warp/gate class is placed in caves; 5 `.evt` on the whole disc | connectivity is geometry, not records |
| world is **117x** one room; no bounds contains the entities | an area is many placed instances |

## What this means for path-guiding - and it is not a dead end

**The collision geometry is authoritative for a single room, and that is still useful**: once the bot is inside one room instance, its local walls and doorways are
known to 1.08x routing accuracy.

**What cannot work** is mapping the whole live world onto one collision file. That attempt is now closed with numbers rather than left as a suspicion.

**What remains viable, and needs no transform at all**, is the **live-coordinate grid**: record cells and observed edges in the game's own coordinates, which spans the
world naturally because it is measured in it. That recorder is built and proven (round 7); it needs a drivable session to populate.

## Where the goal actually stands

| clause | state |
|---|---|
| map analysed, scanned, internalised | **51 collision rooms, 17 layouts' room inventories, 998-edge prior graph** |
| map used for path-guiding the bot | **per-room local pathing is ready; world-scale mapping is proven impossible without the instance table** |
| autoplaying | **blocked: input does not reach the game** - session predates the pad fix; the fix itself is verified |
| speedrunning at 10x | **3.6x measured**; ceiling is one saturated CPU core |
| decrypting PSO | **pathing never needed it** - collision parses straight from the disc |

**Every remaining item is blocked on one of two things that are not analysis: the operator relaunching the game, and single-core CPU throughput.**
