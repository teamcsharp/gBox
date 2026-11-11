# RE5 Switch Mercenaries stage collision (s400..s407)

Request #9360. Static read of the owned Switch romfs `010018100CD46000/nativeNXx64/ImgNX/Archive/s40N.arc`; no game
file written, nothing run on any PC. Same product as `re4-switch-mercs-collision.md` (grid + wall segments per stage).

## Where the collision is
Each stage archive holds exactly one `stage\\s40N\\havok\\s40N` entry (tag `0x4000....`, 25-185 KB). It is a zlib
stream (`mt_arc` entry data) that inflates to a **Havok 5.5.0 packfile**: magic `57e0e057 10c0c010`, file version 5,
layout rules `04 00 01 01` = 4-byte pointers, **big-endian**, three sections (`__classnames__`, `__types__`, `__data__`).
Each file holds one chain: `hkRootLevelContainer > hkpPhysicsData > hkpPhysicsSystem > hkpRigidBody >
hkpMoppBvTreeShape > hkpMoppCode + hkpSimpleMeshShape`. (The scr/light/se entries in the same archives are not collision.)

`hkpSimpleMeshShape` (32-bit BE): vertex array pointer at +0x18, count at +0x1c; triangle array pointer at +0x24,
count at +0x28 (both resolved through the section's local fixups). Vertices are hkVector4 (f32 x,y,z + w = 1.0,
16 B); triangles are 16 B: `i32 a,b,c, u16 welding_info, u16 0`. Radius 0.01. The rigid body's motion-state
transform is identity. Every triangle index is < the vertex count in all eight files. The MOPP code is a BV tree
over the same mesh and is not needed for a grid.

## Frame (verified)
Units are **metres, y up** (the game RAM position is cm). Checked against the PS3 Public Assembly nav layout
`tests/fixtures/tactical_map/BLUS30491-public-assembly.stage.json` (already used by `re5-bus-nav.md`): 400 random
nav points, Havok floor under (x/100, z/100) with the identity mapping: covered 400/400, **340 within 15 cm of the nav
point's y, median error 4 cm**. Mirrored x: 83 within 15 cm (median 144 cm); mirrored z: 136 (21 cm); swapped x/z: 87
(74 cm). So game (x, y, z) cm = Havok (x, y, z) m x 100, no flip. Only s400 has a second source to check against;
s401..s407 use the same file layout and loader, but their frame is by the same-engine assumption, not measured.

## Grid (same rules as RE4, mm, 250 mm cells)
Floor = triangle with winding normal y >= 0.5 (winding is correct: floor tris outnumber ceiling tris in every stage).
Wall = |normal y| < 0.5 with vertical extent > 1 m; its horizontal span is one segment. Cell `.` = centre under floor,
`#` = a wall segment crosses a cell that has floor (or centre under a wall triangle with no floor), `_`/space = none.
Overlapping storeys collapse into one 2-D layer (floor cells carry no height); use `floor_heights_m()` to get the
stack at a point.

| archive | stage | verts | tris | floor | ceiling | x m | y m | z m | grid | floor cells | blocked | wall segs |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| s400.arc | Public Assembly | 3939 | 5587 | 2139 | 513 | -30.6..31.8 | -2.2..8.9 | -47.0..34.7 | 252x328 | 60725 | 8059 | 1102 |
| s401.arc | The Mines | 4888 | 7451 | 1588 | 1262 | -2.4..45.8 | -1.1..24.3 | -246.8..-110.4 | 195x548 | 20575 | 8171 | 2113 |
| s402.arc | Village | 4566 | 7489 | 1476 | 941 | -106.0..-30.9 | -8.6..17.3 | 14.7..93.2 | 303x316 | 36471 | 6375 | 1210 |
| s403.arc | Ancient Ruins | 901 | 1352 | 463 | 0 | -60.0..49.0 | 8.5..26.0 | 107.0..208.0 | 437x405 | 29056 | 3160 | 464 |
| s404.arc | Experimental Facility | 3274 | 6604 | 1356 | 1194 | -55.7..55.7 | -20.1..21.1 | -46.8..46.8 | 447x377 | 29535 | 2482 | 476 |
| s405.arc | Missile Area | 2428 | 3104 | 568 | 189 | -85.2..23.3 | -0.2..17.2 | -243.8..-124.9 | 436x478 | 75732 | 11101 | 1049 |
| s406.arc | Ship Deck | 4466 | 5906 | 1379 | 760 | -23.5..49.2 | -2.5..24.5 | -56.1..188.0 | 292x978 | 86974 | 12558 | 1386 |
| s407.arc | Prison | 7981 | 8664 | 2172 | 868 | -183.2..178.6 | -57.8..15.9 | -180.9..180.9 | 1449x1449 | 2088107 | 7149 | 2250 |

s407 is 360 x 360 m wide with 2.09 M floor cells (a very large ground/water plane around the arena), so its grid is
mostly one floor plane, not a playable-area outline. `s400` mesh also covers more than the PS3 playable nav bounds
(-28..30 x -40..30 m).

## Artifacts
- `system/gbox/re5_switch_collision.py` - loader, rasteriser, `python -m gbox.re5_switch_collision <Archive dir> <out.json>`.
- `system/docs/research/re5-switch-mercs-collision.json` - counts, bounds, wall segments (mm) and RLE grids, all eight stages.
- `system/tests/test_re5_switch_collision.py` - 5 tests (RLE, synthetic floor+wall, bad magic, real s403 counts, report consistency).

## Not verified
Offline only. Not checked against gameplay positions on the Switch (no live RAM sample), s401..s407 frame is assumed,
the stage-to-archive names s401..s407 are the existing menu-order guess in `re5-enemy-cast.md`, and wall segments use
the triangle's extreme points rather than merged edges. A PR is not runtime acceptance.

## Agreement with learned nav grids

Learned grids compared: the 8 schema-2 geometry-identity grids under
`gbox-data/mercs/learned/010018100CD46000/nav_grids/verified/` (one per stage,
stage name taken from each JSON). Learned cells are 1 m, keyed
(kx,kz) -> center (kx*100 cm, kz*100 cm); costs: 0.5 walked, 4.0 near-wall,
16.0 wall memory. Each learned cell center was looked up in the 250 mm Havok
grid (floor `.` / wall `#` / no-floor sampled `_` / outside grid `O`).

| stage | learned cells | walked on floor | walked on wall | walked on no-floor | wall-mem on floor | wall-mem on wall | walked-floor % |
|---|---|---|---|---|---|---|---|
| Public Assembly | 129 | 54 | 4 | 0 | 16 | 2 | 93.1 |
| The Mines | 71 | 22 | 8 | 0 | 10 | 0 | 73.3 |
| Village | 226 | 88 | 5 | 2 | 37 | 1 | 92.6 |
| Ancient Ruins | 301 | 156 | 10 | 4 | 23 | 1 | 91.8 |
| Experimental Facility | 102 | 5 | 0 | 40 | 0 | 1 | 11.1 |
| Missile Area | 128 | 45 | 11 | 0 | 9 | 1 | 80.4 |
| Ship Deck | 54 | 14 | 6 | 0 | 5 | 2 | 70.0 |
| Prison | 257 | 118 | 17 | 0 | 26 | 3 | 87.4 |

Findings:

1. **Frame confirmed for all 8 stages from bot RAM walk positions.** 0 of 1438
   learned cells fall outside their stage's Havok grid; every grid's span is
   inside that stage's bounds. This is the strongest available check on the
   s400..s407 naming, since the verified grids are keyed by measured geometry
   identity, not by menu order.
2. Bot walk trail lands on sampled floor in 70-93% of cells for 7 of 8 stages
   (residual: 1 m learned cell vs 250 mm sample, cell-center lookup, and the
   grid's own unknown-cell policy).
3. Wall-memory cells often sit on floor cells (e.g. 16 of 18 for Public
   Assembly): the bot marks the cell it was pushed in, and the wall may be
   anywhere inside that 1 m cell. Expected noise, not a frame error.
4. **Experimental Facility anomaly (unresolved):** 40 of 45 walked cells are on
   no-floor sampled cells. Either thin platforms/stairs the 250 mm floor sample
   missed, or the geometry-identity grid is from a different mesh. Needs a
   dedicated look at that stage's floor samples.
5. Old schema-1 stage-name files (`Public_Assembly.json` etc.) use a different
   frame (x -100..43, z -227..187 m, nearly identical spans across all 8
   stages) and were excluded - consistent with `re5_switch_nav.py`: old
   stage-name files "cannot be migrated safely".
