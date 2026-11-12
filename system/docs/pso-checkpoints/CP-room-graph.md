# The room graph comes from the disc - 998 connections

## The finding that made it possible

The placement record's `link` lane names another room. Room 1 of `map_cave01_00` links to **20, 50, 51, 52, 53, 60 and 120**, and those records sit at positions spread
across the whole layout `(0,-110)`, `(0,-650)`, `(630,-1280)`, `(1170,-1280)`, `(900,-1450)`, `(-350,-880)`, `(-1090,-880)`, `(-1440,-1110)` - they are
**connections**, not decoration.

## Built across every layout

```
layouts analysed:                     50
room slots:                         1527
rooms with at least one connection:  874   (57%)
connections:                         998
```

**998 room-to-room connections decoded from the disc**, with no session, no walking, and no transform. Saved to `routes/room-graph.json`, per layout, with each
layout's room numbers and its edge list.

The most connected room numbers are `1` (363), `2` (272), `5` (206), `3` (128) - consistently hubs across layouts, which fits room 1 being the entry/start room of
an area.

## What this is, and what it is not

**This is the room-to-room structure that room-level path-guiding needs** - the same thing `pso_knowledge.record_edge` stores and `critical_path` walks. It is
derived from the game's own data, so it cannot be wrong about which rooms connect.

**It is not yet in the live knowledge store, and the reason is specific.**

`pso_knowledge.area_fingerprint(episode, floor, geometry_identity)` keys each area on a **hash of live collision memory**:

```python
def _read(ad, address, length): ...          # reads the emulator's RAM
digest = hashlib.sha256(); ...
```

The identity is computed from the **loaded** collision object - its runtime traversal pointers, meshes, spheres and flags - not from the disc file. So a graph keyed
by layout name will not match the key the bot computes live, and just writing it into the store would produce entries nothing ever reads.

## The precise next step

Three options, in order of cleanliness:

1. **Add a disc key to the lookup**: have the bot also consult `area_fingerprint(episode, floor, "disc:<layout>")`, which is deterministic from the floor table
   (`pso_floor_map` already resolves floor → area and layouts). The graph then applies immediately on entering a known layout.
2. **Compute the live identity for a known layout**: read the same memory the identity hashes on a live session and record the mapping from layout to identity once
   per layout, then the disc graph can be re-keyed.
3. **Let the walk build it**: `record_edge` from actual transitions - the original plan, which needs a drivable session.

**Option 1 is the one I would take**: it uses the floor table that already exists, needs no live hash, and makes 998 disc-derived connections available the moment the
bot enters a cave layout.

## State

| item | state |
|---|---|
| collision grids, 51 rooms, routing at 1.08x | done |
| room inventory, 17 cave layouts | done |
| **room graph, 998 connections, 50 layouts** | **done this round** |
| graph in the live store | **needs a disc key in the lookup** |
| live grid recorder | built and proven, waiting on input |
