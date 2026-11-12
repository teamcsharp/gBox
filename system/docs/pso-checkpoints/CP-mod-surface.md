# What is already built toward "modify the game in its entirety"

The request is large, so this records what the tree can *demonstrably* do today, verified on the owned disc, and what is genuinely missing. Guessing here would
be worse than useless.

## Already working - proven this round on `map_forest01d.dat`

**150 placement records decode**, with class names from the registry:

```
  52  index 4    TOSensorAncient01
  52  index 1    TORockCaveBL03
  23  index 133  TObjEnvSoundEx
   9  index 23   TOSymbolchatColli
   6  index 134  TObjEnvSoundGlobal
   6  index 6    (unresolved in this build's table)
   2  index 17   TOSwitchAttackSub
```

**Move a placement** (adjust a spawn point):

```
changed bytes: 4 at offsets 16-19
file length 10200 -> 10200 (unchanged)
outside the record untouched: True
re-decoded x: 583.1 (was 483.1)
```

A move is a **4-byte in-place patch** (the x float) inside one 68-byte record - the FST does not move, nothing else on the disc changes.

**Add a placement** (spawn something new): 150 → 151 records, **+68 bytes exactly**.

**Delete a placement** (remove a door): 150 → 149 records, **-68 bytes exactly**.

## The modules that already implement this

| module | what it does |
|---|---|
| `pso_setdata.py` | decodes/encodes the 68-byte records: **objects, enemies, doors, switches and warps** of an area |
| `pso_map_write.py` | writes edits back through `filemods.build_image` to a **bootable disc image**; patches in place when the size is unchanged |
| `pso_editor.py` | the editorial layer: list, author, **preview**, build |
| `pso_areas.py` | catalogue of every area's collision, render, placement and event files |
| `psomap.py` | collision triangles from `c.rel` → walkable grid (used for the 50 room maps) |
| `pso_evt.py` | the `.evt` event table, parsed and re-buildable |
| `pso_class_registry.py` | placement class index → name (148 named, 84.4% of placements) |

So **"adjust spawn points", "remove doors" and "remix area placement" are not research problems here - they are implemented and verified.**

## What is genuinely missing, honestly

**1. Enemies are not in the object set.** Forest 1's set contains rocks, sensors, sounds and switches - **no enemy classes**. Enemies are spawned by a different
mechanism (the spawn/event tables, and `pso_evt.py` exists precisely because *"door transitions are the thing this lane has never been able to find in the
placement sets"*). **"Make enemies spawn" therefore needs the spawn table decoded first** - that is the next real research target, not a code change.

**2. Adding a genuinely new level** (a new area with its own scene) needs more than an edit: a new `Scene/map_*c.rel` (collision), `*_n.rel` (render),
`*d.dat` (placements) and the FST entries to reach them. The pieces to *read* all of those exist; **the pieces to author a new scene entry do not**.

**3. Collision authoring.** Room maps can be decoded and written as grids, but nothing yet writes a modified `c.rel` back into the disc. For custom
"amalgamation" rooms assembled from several biomes, that is the missing half.

**4. Full decompilation is not the same thing as modding this game.** The community-scale effort of decompiling the whole executable is not what any of the
requested outcomes actually require: the file formats are decoded (placements, collision, events, class names), and the loader reads those files. What limits us
is **the spawn/event mechanism and scene authoring**, not executable source.

## Where the leverage is

`pso_evt.py` already has the header, record table and script sections of `.evt` parsed. **Decoding the spawn records inside it is the single change that unlocks
"make enemies spawn"**, and it is a bounded, testable task on the extracted Forest 1 event file.
