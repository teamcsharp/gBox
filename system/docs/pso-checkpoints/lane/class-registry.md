# Lane-log text of `ds-pso-class-registry-20261110` (moved here by CP0 from the shared lane log)

Tip before the rewrite: `a18da08e`.

----

## Round 48 (2026-11-10, later session) — A3 solved: the object-class registry at `PsoV3.dol+0x805D3138`

Working locally on the i9; no lilspark, no live session, no service touched.

`docs/research/pso-gc-executable.md` §7.3 called this "the single highest-value decompile left for the editor": 315
`TObj*` names exist, and the table that maps a placement's class index (the low byte of its `kind`) to one of them was
not located. It is now located, pinned and verified.

**The table.** A flat array of class-name pointers in `.data` at **`0x805D3138`**, 4 bytes per slot, 240 slots, **148
named** in this build (the rest zero, plus one `0xFFFFFFFF` sentinel slot). `class_name(index)` is a plain
`cstr(table[index])`.

**How it was pinned.** The four room-10 door entities were walked live in rounds 22/29 and their kinds measured
(`0x46` Shop, `0x47` Guild, `0x48` Warp, `0x49` Med - `pso-gc-pioneer2-rooms.md`). Searching every 4-byte alignment
in the .data name-pointer sections for the one where those four indices land on exactly those four names gives this
base and stride **4/4**, and no other alignment in the search exceeds 1/4. That measurement is what makes the table
the registry rather than a coincidence.

**Coverage on the owned disc** (141 object-set files, 18,927 placements, 60 distinct class ids): it labels **44 ids,
15,975 placements (84.4%)** - `TORockCaveBL03` 7,438, `TOSensorAncient01` 4,436, `TOSymbolchatColli` 1,408,
`TObjAreaWarpForest` 308, the five city doors, the switches, the traps, the VS2 wrecks, the season objects - which is
what the editor's markers need ("door", "warp", "switch", "obstacle" rather than a number).

**The 16 holes** are real empty slots in this build: `0x05`, `0x06`, `0x08`, `0x0a`, `0x0c`, `0x0e`, `0x13`, `0x1e`,
`0x22`, `0x4b`, `0x61`, `0x67`, `0x74`, `0xc4`, `0xc5`, `0xc8` (`0x06` alone is 2,032 Ruins placements). The classes
exist - the sets spawn them - but their name slot is zero, so `label()` reports `class_0xNN` instead of inventing a
name. That is the honest half of A3: 84.4% labelled, the rest named by kind.

**Checked in:** `gbox/pso_class_registry.py` (the pinned table plus `name` / `label` / `class_index` / `index_of` /
`derive` / `verify`), `tools/verify_pso_classes.py <PsoV3.dol>` (**PASS** on the owned disc: 240 slots, all pinned
names match, doors correct), and `tests/test_pso_class_registry.py` (7): the four walked doors, the classes the editor
needs, holes reported not invented, the low-byte flag masking, a synthetic DOL in the executable's own layout, a
changed table reported instead of trusted, and an unmapped address raising instead of crashing. Registry + setdata +
areas + ram + editor suites: **45 passed**.

**For the editor / survey:** a placement can now be labelled offline from the disc alone:
`label(kind)` -> `TObjCityDoor_Guild`, `TOSwitchAttack`, `class_0x06`. The next natural step is the page (P6b's UI)
and the area survey's class histogram, both of which now have names.
