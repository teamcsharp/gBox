# CP10 (P6a): the field proof in Forest 1

Session identity: DeepSeek    Branch: ds-pso-cp10-forest1-20261110    Commits: this branch
Goal: 2

## Round 91: both pre-built Forest 1 object-move mods decoded offline - the before/after positions are known

CP10's steps are "boot `pso_objmove_forest01_l0_r60` with CP4's state and CP5's warp, solve the offset, read the moved
record's entity". The boot is live, but everything the boot has to confirm can be **read out of the two pre-built mod images**
first, and that is what this round did.

Both mods are complete modded ISOs under `D:\gBox\cache\mods\436e0bb84d5337d1\` with a `.gbox-mod.json` manifest naming the
patched file, offset and length. Comparing each modded image's *parsed* set records with the base image's gives exactly one
changed record per mod:

| mod | file | record | change |
|---|---|---|---|
| **`pso_objmove_forest01_r5`** | `map_forest01d.dat` | **5 of 150** | x **-24.71 -> +95.29** (**+120.0**), y and z unchanged |
| **`pso_objmove_forest01_l0_r60`** | `map_forest01_00o.dat` (archive `gsl_set_object.gsl`) | **60 of 109** | x **-16.61 -> +133.39** (**+150.0**), y **24.53 -> 30.53** (**+6.0**) |

**The names cross-check the records:** `l0_r60` moved **record 60** of layout **0**'s set, and `r5` moved **record 5** - the
two names encode exactly what the record diff found. That is an independent confirmation that the mod writer did what the
name says, without booting anything.

**Raw patch view (for the evidence trail):** the manifests patch 12 bytes each - `map_forest01d.dat` at `0x164` and
`gsl_set_object.gsl` at `0x5800` - and both files differ from the base only in those bytes (`identical=False`, same sizes).

**What the live step still has to confirm (and nothing else):**

1. boot `pso_objmove_forest01_l0_r60` with CP4's state and CP5's warp, reach the field area;
2. `pso_offset.solve(<the set's records>, <the live entity list>)` -> the room-local -> world offset for layout 0;
3. read the entity for record 60 and check it sits at the **written** world position (x +150, y +6 from where the base image
   puts it), with the other 108 records unchanged - the "MOVED" verdict of round 49, in a field area.

The evidence file for the live run should be marked **"reached by warp (dev)"** per the guide, and record the session id, the
solved offset and the before/after entity positions.

**Where the rest of CP10's prerequisites stand:** CP4's state and CP5's warp are the blockers (both need the operator-absent
window; CP4 is ready with both input fixes in, and CP5's floor-warp branch exists unmerged at `712f4a7f`/`0442a9fe`).

Tests: none changed (this is a measurement of two existing mod images).
