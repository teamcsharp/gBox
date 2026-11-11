# Round 274: the disc's file table cracked - every Cave collision map extracted without the job channel

The blocker for two rounds was that Cave 1-3 had no collision maps, and the only known extractor was the plane's `mods` extract operation, which is a
**job** - and jobs are the one thing an operator-owned session never dispatches. The disc is just a file, though, so the maps were read directly.

## Getting a readable image

The disc is stored as `Phantasy Star Online Episode I & II Plus (USA).gcz`, and `DolphinTool` could not open it in place ("the input file could not
be opened") because the running emulator holds it. Copying it first and converting the copy to ISO fixed that:

```
copy   gcz -> disc\pso.gcz   1,178,288,344 bytes
convert -> disc\pso.iso      1,392 MB
```

## Cracking the file table, by probing rather than assuming

Three wrong readings preceded the right one, each caught by inspecting the result instead of trusting it:

1. reading the FST offset from 0x424 as a pair `(offset, size)` gave a nonsense offset;
2. deriving the entry count from the root entry's **offset** field gave zero, and garbage names;
3. the root's **size** field is the count.

The correct facts for this disc (`GPOE8P`):

| fact | value |
|---|---|
| FST offset | u32 at **0x424** = `0x52400` |
| entry count | root entry's **size** field = **3556** |
| string table | `fst + count * 12` |

With those, names resolve exactly:

```
1: abeniji_fe_obj001_niji.bml   off 211401796  size 4064
3: AdDrawLineTask.prs           off 211409892  size 3765
4: AdEnding.rel                 off 211413660  size 8128
```

**3555 entries, 3510 files, 649 `.rel` files, 501 map files.** The game's entire asset table is now readable in about a second.

## What that unlocked

All **17 Cave collision maps** were extracted:

```
map_cave01_00c .. 05c      6 layouts of Cave 1
map_cave02_00c .. 04c      5 layouts of Cave 2
map_cave03_00c .. 05c      6 layouts of Cave 3
```

That matches the operator's "maybe three different layouts of each level" - and the plane's resolver says six for Cave 1, so the layouts are now local
files rather than a job away.

## Why this matters beyond the Caves

The same reader reaches **every** map in the game: Forest 3, the Mines, the Ruins, the boss arenas, the city. The minimap, the room database, the
height tables and the path planner are all functions of a collision map, so this removes the single blocker that stood between the bot and
navigating any area it can reach.

## Next

Identify which of the six Cave 1 layouts is currently loaded - by checking which one's free cells contain the live player and door positions - then
build its room mesh and heights, which is the same pipeline already proven on Forest 1 and 2.
