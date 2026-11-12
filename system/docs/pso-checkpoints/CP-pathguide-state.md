# Path-guiding: what binds, and what genuinely blocks

This round set out to wire the internalised map into the bot. It produced **three verified facts, two falsified hypotheses, and one precise blocker**.

## Verified

**1. The live session binds to a decoded area through the game's own table.**

```
live floor id: 3
area: map_cave01
layouts: map_cave01_00 .. map_cave01_05
```

`pso_floor_map` pins this from the executable's table at `0x804C8FC0` (`FUN_80207E88`), so no live load is needed. Floor 3 = Cave 1, six layouts, all six already
decoded (walls 2581-11795 per layout).

**2. The owned disc reads directly, and cave set data decodes.**

```
disc: Phantasy Star Online Episode I & II Plus (USA).gcz (1.1 GB, 3510 files)
map_cave01_00ad.dat: 13532 bytes, 199 placements
```

**3. The placement record's third lane is the room id.**

`pso_setdata` names it `amount`, but its 23 distinct values for one cave layout are `[1, 10, 11, 12, 20, 30, 31, 32, 33, 34, 40, 50, 51, 52, 60, 110...]` -
room numbers, and the player's `room` is **50**.

**4. Room 50 is a shared room.** Its **21 placements are byte-identical in all five layouts that contain it** (layout 03 does not have it at all).

## Falsified - and this matters more than the guesses

**Hypothesis A: "fit the offset from the player's motion."** Rejected: the player was stationary - **1 distinct sample out of 40** - and one point can be placed in
open space under any offset. The script printed a confident-looking "verdict"; it was meaningless, and I am not treating it as evidence.

**Hypothesis B: "match live entities to a layout's placements to find the offset."** Rejected twice:

* matching **all** placements gave **the same offset (792, -1296) for all six layouts** - a common answer for every candidate is the signature of a biased fit;
* matching **only room 50's 21 placements** (the correct, specific evidence) gave 6 coincidences and put the player at room-local (-332, -665), which is
  **outside every cave layout's bounds** (-182..319 x, -200..225 z).

**Conclusion: a single global offset cannot exist.** Each room in a layout is placed at its own position, so the collision file's coordinates are per-room-local and
the layout's **room instance transforms** are required. That table is not in the set data or the placement coordinates; it belongs to the scene/layout file.

## The blocker, named

**The room instance table is not decoded.** Until it is, disc-derived collision cannot be mapped onto live positions, and the `1.08x` route proved in round 2
stays a demonstration rather than a live guide.

## What already works without it

**Live-coordinate navigation does not need the transform at all**, and the pieces exist:

* `operator-walk-summary.json`: **2316 samples, cell size 8.0, 1163 cells, 1221 edges, one connected component**, 21,350 units walked;
* `pso_coop_nav.RoomMap.observe` learns blocked edges from failed moves, in whatever coordinates the game uses;
* `pso_knowledge.KnowledgeStore` persists room templates keyed by **geometry identity** - not coordinates - plus an area **room-adjacency graph** and
  critical path.

**But the knowledge store is empty:**

```
stores found on disk: 0 PSO stores
fresh store: rooms 0 | areas 0
```

So the internalisation that survives restarts has **not been populated**. Geometry maps: 51 rooms on disk. Room knowledge and adjacency: **none**.

## The next concrete step

**Populate `KnowledgeStore` by walking, keyed by geometry identity**, which sidesteps the room-offset problem entirely: record edges as rooms are left, record
the critical path, and recall it on re-entry. That is `record_edge` / `record_path` / `remember`, called from the bot that is already driving the character - no
new file format, no RE.
