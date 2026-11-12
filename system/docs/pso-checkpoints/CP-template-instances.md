# Why no offset exists: rooms are template instances

## The finding

`map_cave01_00` has **23 room numbers**, but they are not 23 distinct rooms:

```
room   50  set_ids [198293]  21 placements  (-149,-221)..(163,229)
room   51  set_ids [198293]  21 placements  (-149,-221)..(163,229)
room   52  set_ids [198293]  21 placements  (-149,-221)..(163,229)
room   53  set_ids [198293]  21 placements  (-149,-221)..(163,229)
```

**Four room numbers, one `set_id`, identical bounds, identical placement count.** They are **one room template instantiated four times**.

So the two id lanes mean different things:

* **`set_id`** (where ≥ 0x1000) is the **room template** - the geometry and placement definition;
* **`amount`** is the **room number** - the slot the template occupies in this layout.

## What this explains

**Why every positional fit failed.** I tried four approaches and each was falsified:

| attempt | result |
|---|---|
| fit the offset from the player's motion | **1 distinct sample** - meaningless |
| match all placements to all entities | **same offset for all six layouts** - a biased fit |
| match room 50's 21 placements only | 6 coincidences, player **outside every room's bounds** |
| pair entities to placements by id | `set_id 0` matched everything; the real ids are **not stored on the objects** |

**A single offset cannot exist because the same placement set is instantiated at several positions.** The transform is per **room-number instance of a template**, not per layout - which is exactly why every global fit produced nonsense with confidence.

## Why this is progress, not just a negative

It **validates the design already in the tree.** `pso_knowledge`'s own docstring says: *"PSO areas are assembled from a finite set of room templates. Once a room's gate is understood … that knowledge is PERSISTED keyed by the room's geometry / landmark fingerprint."*

**That is the correct model, and this round supplies the id that names it.** Room knowledge should be keyed by `set_id` (template), with the room number as the instance - which is what the store's geometry fingerprint already approximates.

It also explains a real hazard the store guards against: the same template at two positions must not be confused, and a different layout reusing a room number must not inherit stale walls.

## Delivered

**`routes/room-inventory.json`** - every cave layout's rooms with their template ids, placement counts, bounds and kind histograms, built straight from the disc with no session and no transform:

```
map_cave01_00   199 placements   23 rooms
map_cave02_02   256 placements   35 rooms
map_cave03_05   143 placements   27 rooms
...
17 cave layouts, saved
```

This is the room-level structure room-to-room pathing needs, and it is the first map artefact keyed the way the knowledge store expects.

## State of the goal's path-guiding clause

* **51 collision grids** decoded and routing at 1.08x of straight line;
* **17 cave layouts' room inventories** with template ids (this round);
* **live grid recorder** built and proven, waiting on a drivable session;
* **the transform problem is now explained, not mysterious** - it is per-instance, so the fix is template-keyed knowledge, which the store already implements.

Still blocked on the same single action: **a relaunch**, so input reaches the game and the bot can act.
