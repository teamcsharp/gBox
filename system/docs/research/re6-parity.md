# RE6 Switch parity with RE5 in MercMode: bot, greybox, enemies, rotation

2026-11-09, branch `wt-re6-parity-20261109` (from `origin/main` at `83ff90c7`). RE6 Switch is title `01002A000CD48000`,
gBox game `115f9cdbba115432`, played on lilspark's Eden with the 1.0.2 update applied. The DeepSeek lane moved off
RE6; the goal here is parity with RE5 Switch in MercMode: library characters as the players and as the enemies, the
blueprint-grid look of the stages, the same bot doctrine, the operator's map goals, and rotation beside RE5.

**Nothing in this note has been booted.** All work is offline: code with tests on synthetic snapshots and fixtures,
overlays built from archives copied read-only from the game host, receipts that say `live_verified: false`. Section 7
says what was measured, what was run and what is inferred.

| part | state | where |
|---|---|---|
| The 17 red tests of `test_re6_switch.py` | green (stale tests, plus three aliases the code had left) | `5a58cd61` |
| Bot: doctrine commands, combo clock, never stand, map goals | in the bot, 22 tests, not live | `828808a1`, `re6_switch.py`, `test_re6_switch_parity.py` |
| Greybox of Mining the Depths (`s1208.arc`) | built + verified, not booted | `re6_stage_greybox.py`, `re6-stage-greybox-v1` (+ `-luma`) |
| Enemies: the classes per stage; library donors on the J'avo | census measured; two pool overlays built, not booted | `re6_switch_enemies.py`, `re6-enemy-pool-keep-v1`, `re6-enemy-pool-v1` |
| Rotation beside RE5 | already configured on lilspark; no RE6 entry in the queue | section 6 |

---

## 1. The 17 red tests

15 of them expected the d-prefixed D-pad aliases (`dup` / `ddown` / `dleft` / `dright`). The code moved to the plain
`up` / `down` / `left` / `right` on purpose in `8fece3cd` (live 2026-11-09: a burst with `ddown` did not move the PLAY
GAME cursor, a single `down` did; handover section 4.9): **the tests were stale**. Three aliases had been left in the code by
later merges (`_equip_keys`' `legacy='dright'` default and the empty-gun `weapon_cycle` tap, `0c271af4` / `17dec552`):
**the code was stale there**; they are `right` now like the rest of the wheel, and the three tests that pinned them
(`test_re6_empty_weapon_recovery` x2, `test_re6_periodic_quick_attack`'s Continue cursor) follow. The `not in` checks
that had become vacuous with the alias now check the plain key.

The two others were stale after `dfee5214` (the arsenal swap). The list of id pairs is `loadout_plan`'s spread: `SPREAD`
now loads the grenade launcher (`0x112`) after the magnums and before the shotguns, so Chris' seven weapon slots end
`0x108, 0x112, 0x104, 0x105` (the Hydra `0x106` finds no slot). `bot_options` returns the `arsenal` switch too; the test
pins it off and checks that it turns on.

`damage_clusters` labels the plain names as `item (D-pad)` as well. Still red on the base and untouched here (not
key-related): `test_re6_magnum_quick4` x2 (`Controller` has no `ad`), `test_re56_weapon_controls` (sniper 30x),
`test_flashbang_5972` x6.

## 2. The bot (`gbox/mercs/titles/re6_switch.py`)

### 2.1 The doctrine's commands

The universal doctrine's Director (`gbox/mercs/core/doctrine.py`, run by `engine.py:140-147` for every title) issues
`fight` / `hunt` / `score` / `mine` into the live stats; RE6 read only the operator's `explore` / `next_area` (the PiP's
wall). `_operator_command` (`:3285`) now reads one command a tick through `doctrine.Reader` (the operator's first):

| command | RE5 Switch | RE6 Switch now |
|---|---|---|
| `fight` | nobody on his level: the nearest anywhere | no detour (bonus run, bonus shots, taunt) while one is on his floor; with nobody there the pursuit (already the default) |
| `hunt` | beyond `HUNT_R` (12 m), gun down: close in on the nearest | the same: `_pursue` by the stage mesh, at once |
| `score` | the nearest is the target | the quickest kill: the one his gun is on while in reach, else the nearest open one |
| `mine` | the mine controller due now | the remote bomb due for `MINE_DUE_S` (12 s): `BOMB_GAP_S` and the 3-coming crowd waived (at most every `MINE_CMD_GAP_S` 10 s), placed with nobody on his floor too; with one within `BOMB_ROOM_R` (4 m) dropped at his feet and walked out of its reach (the bomb-drop path) |
| `mine_trail` | due again after each plant | the same |
| `explore` / `next_area` | the wall | unchanged (read by the same reader now) |

A command presses nothing itself; the hold, the heal, the prompts and the bomb's own safety rules (never set off
inside the learned reach) still decide. `rush` is not taken (RE6's flash is the native intervention endpoint).

### 2.2 The combo clock

Only fields the driver already reads: `sGameMan +0x4094` the combo and `+0x409C` its window's seconds left
(`re6-switch-ram.md`: "about 15 s left after a kill"). The full window is the reading on the tick a kill raises the
combo (`stats combo_window_full`); `COMBO_WINDOW_S = 15` stands in until one is seen. `KILL_PACE_S` (the doctrine's
3 s) after a kill the next is owed (`combo_pace`): the quickest kill is the target unless a close one (6 m) is on him,
and no time-bonus run starts while any enemy is alive and the clock is above 120 s (`_bonus_wait`; RE5's rule).
`COMBO_LOW_S` (3 s left) keeps its own urgent rules (nearest open one, a bomb out goes off with one on it, the green
bonus). New stats: `combo_left_s`, `combo_since_kill_s`, `combo_pace_s`, `combo_pace_picks`, `bonus_waits`.

### 2.3 Never stand

`_never_stand` (`:3496`), applied after the wall guard: unmoved 80 cm for 3 s outside a hold, a tablet, a reload, a
prompt, a quick turn / shot, a throw, a melee, an aimed shot (ZL), a tap or the walk off his own bomb, he steps
1.2 s along open floor - the stage mesh 2.5 m ahead (`NavMesh.locate` + `clear`), toward the route's next point when
he has one, else the camera's way. `stats stand_breaks`. RE5's constants.

### 2.4 The operator's map goals

`map_goal_plan` / `receive_map_goal` / `_operator_goal` (`:3342-3460`) with `gbox.mercs.map_goals.Goals` itself - the
title-agnostic goals RE5 uses, including the rule that an enemy with no health reading is alive (only a reading at or
below zero, or an empty slot, for `ENEMY_GONE_S` closes the mark). The tactical publisher already hands a click to any
bot that has `receive_map_goal` (`tactical.py:663`) and takes `goal_round` / `goal_capabilities` from
`map_goal_plan` (`tactical.py:227-238`); RE6 now advertises `["enemy", "point"]`.

- A marked enemy: by the mesh (`_nav_heading`, A* over the stage's triangles) until he is within 15 m on his floor
  with open floor between them, then `_decide` on him alone (no bonus or taunt detours, the pursuit after him only);
  anyone within 6 m on his floor or 2 m on any floor is fought on the way.
- A marked spot: by the mesh until he is within `map_goals.ARRIVE` (2 m); the floor height under it from the mesh.
- No mesh route for 3 s: the mark closes `unavailable` (`map_goals_no_route`), his own play goes on.
- First: a hold, the dying, a critical tablet, the walk out of his own bomb's reach, a throw already in hand.
- Every mark and what he does with it goes to `gbox-data/mercs/map-goals.log` (RE5's file; each line titled
  `re6_switch`), the newest in `stats map_goal_trace`. A replayed round forgets the marks.

### 2.5 Locating by the mesh, and what does not port

`_pursue` already walked the stage's own nav mesh to the best enemy anywhere (his floor first); it now reports RE5's
`locates` / `locate_m` / `locate_dy_cm`. **Ladders and drops (RE5's `MESH_LINKS`) do not port**: RE6's decoded
`rNavigationMesh` carries triangle adjacency only - on `s1218` all 9,722 links are symmetric and share an edge - so a
route never crosses floors. The B prompts' spots are logged per stage (`re6_prompt_spots.json`) as the candidate climb
links; a route across them is not built. RE5's mine controller (`re5_switch_mines`), learned occupancy grid and wall
governor have no RE6 counterpart beyond what was there (the remote bomb, `re6_switch_wall`).

## 3. The greybox (`gbox/re6_stage_greybox.py`)

> **Correction, 2026-11-10 (branch `re6-greybox-stages`).** `s1208` is **Creature Workshop** (stage 9), not Mining the
> Depths: the learned stage books' bonus positions (`s121N.json`) equal, exactly, the bonuses the bot recorded in the
> round maps filed under each stage name, and each pair agrees with the set's enemy census. Mining the Depths is
> `s1203` (stage 2). The full table is `re6_stage_greybox.STAGE_NAMES` / `SELECT_ORDER` (select order:
> s1202, s1206, s1203, s1200, s1204, s1205, s1201, s1209, s1207, s1208). The NavMesh note "s1218 / Mining the Depths"
> in `re6_switch.py` carries the same mislabel. The writer now covers all ten archives (`build_all`), five more
> vertex formats and the suffixed base maps (`_BM-…`, `_BM_NN`, `_BM_HQ`); every boot instruction below that says
> "Mining the Depths (stage 2)" for `s1208` means stage 9.

### 3.1 Which archives are the Mercenaries stages (measured on the host's RomFS)

`nativeNXx64/arc/NX/s1200.arc` .. `s1209.arc` are the ten stages' geometry. Each has two per-mode sets:
`s120NSoft.arc` (THE MERCENARIES: `Attack_Control_*` up to 150 kills) and `s121NSoft.arc` (NO MERCY: up to 300). Both
sets of a stage carry the same `NAV` (identical sizes), the enemy layouts `s12xN_emNN`, items, cameras and the FSM; the
geometry is shared. The stage names are not in these archives. **One is measured**: the live nav mesh `s1218`
(2,005 vertices, 3,434 triangles, `re6_switch.py`'s NavMesh note "s1218 / Mining the Depths") equals the host's learned
stage book for `s1218`, so `s1208.arc` is **Mining the Depths** - and its content agrees (an undersea facility: the dome
is `kaityuu` / `kaimennaka`, "undersea" / "the sea surface from below", with sharks, a manta and fish schools). The
others by the campaign stages their entries name:

| geometry | MB | campaign refs in its entries | No Mercy set | its classes (No Mercy, placements) |
|---|---|---|---|---|
| `s1200` | 41.5 | `s0101` x63, `s0204` | `s1210` | uEm1000 506, uEm3200 6, uEm4300 2 |
| `s1201` | 58.0 | `s0302` x65, `s0300` | `s1211` | uEm1200 298, uEm1000 130, uEm5210 6, uEm4800 3, uEm3300 1 |
| `s1202` | 62.7 | `s0023`, `s0500`, `s0511`, `s0508` | `s1212` | uEm5200 100, uEm5181 68, uEm5191 46, uEm5210 44, uEm5700 40, uEm5050 34, uEm5600 11, uEm3200 3 |
| `s1203` | 46.3 | `s0402` x68 | `s1213` | uEm5000 159, uEm5060 54, uEm5700 52, uEm5191 38, uEm5500 7, uEm3000 3 |
| `s1204` | 50.0 | `s0802`, `s0800` | `s1214` | uEm1000 461, uEm3200 4, uEm3300 1 |
| `s1205` | 34.5 | `s0204` x14 | `s1215` | uEm5400 307, uEm5600 4, uEm4100 3, uEm3000 2 |
| `s1206` | 48.4 | `s0301` x43, `s0300` | `s1216` | uEm1200 286, uEm1000 140, uEm3200 20, uEm3300 1 |
| `s1207` | 29.1 | `s0702`, `s0773`, `s0102`, `s0703` | `s1217` | uEm5200 112, uEm5050 72, uEm5000 46, uEm5191 46, uEm5700 18, uEm5600 14, uEm3200 6, uEm4300 5 |
| **`s1208`** Mining the Depths | 31.2 | `s0972` x32, `s0902` x12 | `s1218` | uEm1400 284, uEm1000 160, uEm5210 19, uEm3200 5, uEm4300 1 |
| `s1209` | 28.8 | `s0905` x52, `s0902` | `s1219` | uEm1400 321, uEm1000 160, uEm3100 6, uEm3200 4, uEm1370 3, uEm4700 3 |

The stage select's order (`re6_switch.STAGES`, MercMode's catalog: Urban Chaos 0 ... Creature Workshop 9) is **not**
the code order: Mining the Depths is select index 2 and code `s1208`. A first boot of each stage with `snapshot()`'s
`navmesh.name` read beside the pick's stage name would complete the table (`_stage_book` already writes the code; the
coverage file the name - one log line with both settles it).

### 3.2 What `s1208.arc` holds (measured)

372 entries, ARC v7, every one a level-6 zlib stream that recompresses byte-identically, every tag `0x40000000 |
length`, `mt_arc.build(parse(x)) == x`. 70 TEX (all `a1 20 00 20`): 38 `_BM` `0x2B` (35 of them under
`data\stage\s1208\scr\`, 3 effect sheets), 11 `_NM` BC5, 11 `_MM` + 3 `_AM` BC4, 5 `_NUKI` `0x14` (cut-out albedos: the
manta, fish, a pipe, a stand), 1 `_LM` `0x23` light map, 1 non-power-of-two `light\s1208_ip00_BM_NOMIP`. 21 MOD (v `0xD3`
rev 0, bone-less) with an MRL v36 of the same name: 18 scene pieces under `scr00` / `scr01`, 3 effects.

Every one of the 117 stage materials is found in its MRL by name hash, and 116 bind an albedo through
`re6_switch_tex.texture_set_materials` (`tAlbedoMap`) - the same with the shader package's names and with the built-in
ones; the one exception, `XfB_W_0__m00_167` (two meshes, in `cap` and `tuuro`), carries the `tAlbedoMap` command with
texture index 0 (unbound: the engine's default) and stays as it is. All 117 sample the primary UV (`FUVAlbedoMap ->
FUVPrimary`). `mtf_mrl.inspect_bindings` refuses these MRLs (RE5's 64-bit shader word).

Vertex formats, measured on all 548 meshes of the 21 MODs (418 of them in the scene pieces; float32 position at +0
everywhere; a signed-byte normal tested at every
4-byte slot for unit length and agreement with the geometric face normal; half2 UVs for range and spread):

| format | stride | meshes | normal | albedo UV | other |
|---|---|---|---|---|---|
| `0x37607D20` | 24 | 248 | none (+12 is not an s8 normal: 28 % unit length) | +16 | RGBA8 colour +20 |
| `0x2ED06F92` | 32 | 123 | +12 (face agreement 99.97 %) | +20 | tangent +16, uv2 +24, colour +28 |
| `0x29F0B449` | 28 | 72 | +12 (99.98 %) | +20 | tangent +16, colour +24 |
| `0x36D0D7A7` | 20 | 65 | none | +16 | |
| `0x33C09993` | 32 | 16 | +12 (100 %) | +20 | tangent +16, colour +28 |
| `0x2C207F5E` | 28 | 16 | +12 (100 %) | +20 | tangent +16, uv2 +24 |
| `0x341068B6` | 36 | 3 | +12 (99.99 %) | +20 | light-map uv +24, colour +28 |
| `0x2AE06DB8` | 32 | 1 | +12 (100 %) | +20 | light-map uv +24 |
| `0x3C004EA1`, `0x3870A4D1` | 28, 24 | 3 + 1 | not measured (44 and 590 vertices) | | skipped (`0x3870A4D1`'s one mesh) |

For the two formats without a normal the geometric face normal decides up / side / down, with the winding the
measured formats agree on (on them the face normal points along the vertex normal on 99.97-100 % of triangles).

### 3.3 The writer

`re6_stage_greybox.build(archive, stage='s1208')` is RE5's method on RE6's containers: it charges every triangle of
every scene mesh to the albedo its material binds (RE5's `_charge`: area shares up / side / down, the UV-to-world
Jacobian's tile span), classifies with RE5's order (the sky dome by its scene piece `sky*`, then the geometry where it
is clear - 0.6 up / side / down - then the name: RE5's words plus `tuuro`, `kowareasiba`, `hasira`, `madowaku`), and
draws RE5's grid (`re5_stage_greybox.grid_image`: one cell per metre of the tile span, floors blue with the pixel width
and a metre tag, walls grey with the metre span, the checker on everything else, a flat tone on the sky) into each
`0x2B` albedo through `re6_switch_tex.replace_albedo` - native dimensions, mip count, TEX header and size, and the
native **opacity** (the colour block's green). Every other entry is byte-identical: MODs, MRLs, normal / mask maps, the
light map, the `_NUKI` cut-outs (no writer encodes `0x14`), the light and effect entries, layouts and sounds.

The grid's colour goes through the Y'CbCr model (handover section 0.1), which no boot has confirmed. The luma - every line and
label - does not depend on it: `build --luma` writes the grids with the native neutral colour block (greyscale), the
fallback that is right whatever the chroma model turns out to be.

### 3.4 The overlays (built, verified, not booted)

Under `C:\_tools\gBox\.scratch-merc-recovery\assets\re6\`, each `romfs\nativeNXx64\arc\NX\s1208.arc` + `receipt.json`.

| overlay | `s1208.arc` SHA-256 | bytes | changes |
|---|---|---|---|
| `re6-stage-greybox-v1` | `cdf4d97068f2b9cff064172b3b817248987d412ca7002ee8f6c568cda7575b99` | 16,442,696 | 35 albedos (13 other, 12 wall, 7 floor, 3 sky); 337 entries byte-identical; source `c2e423db…` (31,212,274: grids compress far better, every uncompressed size and tag unchanged) |
| `re6-stage-greybox-v1-luma` | `179e3e8971b29349e6652a7fc13853dc04c8b6ab21ef8644f238a67261677d5f` | 16,421,374 | the same 35, greyscale |

`verify` re-run from a fresh process on v1: 35 changed, 337 unchanged, the hash above. Previews (CPU renders of the
bytes through the Y'CbCr decode, flat shade, no light maps or alpha test, not the game): `textures.png` (every written
albedo), `stage-native.png` / `stage-view.png` (the facility from above, native and greybox) and `stage-close.png`.

What a live frame must show: Mining the Depths drawn in grey and blue grid tiles with metre labels under the native
lighting (the light map is native), the floors blue with `1024` / `512` and a metre tag, the walls grey with their metre
spans, pipes, rails and clutter checkered, the undersea dome a flat pale tone, the sharks, the manta and the fish (the
`_NUKI` cut-outs) in their own textures, enemies and player unchanged. Failure signs: a hang or black screen at load
(bisect by variant with `--override`), the grids right but in odd colours (boot the `-luma` build), a photograph left
on a surface (an albedo bound from outside `scr` or a `_NUKI`), holes (opacity lost), the native stage everywhere (the
overlay did not load - or the 1.0.2 update replaces `s1208.arc`: section 6, risk 2).

## 4. The enemies (`gbox/re6_switch_enemies.py`)

### 4.1 Which classes (measured)

`stage_census` counts the `mUnitClass` rows of a set's enemy layouts (`soft\stage\s12xN\s12xN_emNN`, XFS `15302ef4`;
the FSM files are not counted); the class is the archive (`uEm1400` -> `uEm1400.arc`). The table in 3.1 is the No
Mercy sets; the Mercenaries sets place the same classes at about half the counts. Mining the Depths: `uEm1400` and
`uEm1000` (J'avo) make 444 of its 469 No Mercy placements.

### 4.2 Can the RE6 writers take an enemy body? Yes, for the J'avo

Measured on `uEm1000.arc` (`d53f6efb…`, 18.3 MB) and `uEm1400.arc` (`0c8cf05a…`, 11.3 MB): each holds one skinned MOD
(`data\chara\em\em1000\model\em1000`, 27 bones; `em1400`, 35 bones; one root each) beside bone-less effect models;
both carry **all 18 role ids** the player writer anchors on (RE6's global bone ids hip 1 ... left foot 22); the position
transform is a uniform scale (266.6 / 268.5); the bind is a T-pose (173 cm wide at the hands, 181-182 cm tall); the
body meshes include the player's four-weight format `0x2000D414`. So `re6_switch_models.build_body` runs on them
unchanged (`keep` up to 20 degrees of rest-pose deviation, `pose` above). What differs is chosen and recorded, not
assumed:

- the material: the J'avo's own `em1000_ID2_Body`, vetted through the archive's own MRL (opaque `BSSolid`, plain
  `FTransparency`, no displacement);
- the template mesh record: the lowest-group LOD-0 mesh on that material (four-weight first). Both bodies draw their
  body material in **group 3** at every LOD; `em1000` also in groups 100 and 403-463 - sections the game can sever or
  mutate, so a donor cloned from one could vanish with it (`uEm1400` has no four-weight mesh on the body material: its
  template is the `0x23305964` record in group 3; the authored vertices are four-weight either way);
- `uEm1000Base.arc` is not a second body: it holds the family's motions (`motsoft` LMT), hit shapes and effects.

The donor replaces every mesh of the MOD (the J'avo's damage pieces `Dbody` / `Bugbody` / `Death` are not drawn);
mutations spawned from other archives are untouched. Textures stay native (geometry-only: the donor samples the J'avo
body albedo through its own UVs) - `build_enemy(textures=True)` writes the donor atlas onto that material's albedo in
the same archive, not built here.

### 4.3 The overlays (built, not booted)

| overlay | class | donor (game) | bind | rest deviation | fitted height | archive SHA-256 |
|---|---|---|---|---|---|---|
| `re6-enemy-pool-keep-v1` | `uEm1400` | Yunsung (Soul Calibur II) | keep | 0.0 deg | 182.2 cm | `d08fc3eb70d746c074a9b8ba70cabea619e9ca3a901d3bc4466cf24417f7211b` |
| | `uEm1000` | Toni Cipriani (GTA LCS) | keep | 9.9 deg | 180.7 cm | `35a1722523eaaf15836cee3d08d2b6006d96abe44448ddae6a8b7206e5cc86be` |
| `re6-enemy-pool-v1` (seed 20261109, `plan_pool`) | `uEm1400` | Mario (Render96 HD) | **pose** | 76.6 deg | 182.2 cm | `6d918d5a00d034e3ed54947de9e68d63c3968ca8dbbef04e1cbdbb0a340ad7ed` |
| | `uEm1000` | Marth (Melee) | keep | 6.6 deg | 180.7 cm | `f6711bc4a07d7076983b564a569545085f10620e5b72ab2caff720aba340089b` |

In each archive only the body MOD entry changed (checked by `build_enemy`); the skeleton bytes are the native ones
(test). The donors come from the 34-entry library copy the earlier RE6 offline work took from the host
(`.scratch-merc-recovery\re6\inputs\characters`, 30 of them in the `full` tier); the host library has 519 such donors
(`re6_switch_cast.pool_report`). Previews: `uEm1000.png` / `uEm1400.png` in each folder (offline renders of the bytes).

What a live frame must show at Mining the Depths: the J'avo as the listed donors, at J'avo height, moving with the J'avo
motions (walk, attack, stagger, death), in the J'avo's textures mapped through the donor's UVs; player, stage and other
classes native. Failure signs: native J'avo (the overlay did not load); a donor vanishing when shot (the template
group is hidden on a damage state); a hang at load (one class at a time); stretched limbs (the rest pose).

**Not covered and why.** The zombie classes (`uEm5000`-`uEm5700`, the other six stages' bulk) and the special B.O.W.s
(`uEm3000`-`uEm4800`) were not copied or measured; `body_check` says in one call whether a class takes the writer.
One donor per class archive is the variety limit: every J'avo of a class is that one donor (RE5 used several body
carriers per class; RE6's J'avo class has one body MOD).

### 4.4 Update 2026-11-10: every humanoid class, group-aware (`re6_enemy_cast`, branch `re6-enemy-cast`)

Superseded: the one-mesh `build_enemy` above put the donor in one group (3) and dropped the rest of the table. The
class bodies are many groups (measured on lilspark's RomFS: `em1000` 298 records in 95 groups - torso skin, arms, legs,
two heads, gas masks, 15 outfit pieces, `Dbody` / `Bugbody` / `Death` bodies, 5 `Shadow` meshes, body sections; the
zombies 37-136 groups) and no table in the class archives says which a spawn shows (no `MTG` resource as RE5 has: the
layouts carry `mModelType` / `mMontageNo` and the choice is in code). `re6_switch_enemies.build_class` now follows the
RE5 writer: `re5_enemy_writer.graft_pieces` (given RE6's template record - RE6 records are mesh type 0xFDF7 / 0x1020,
never RE5's 0xFFFF) keeps every native record with its index words collapsed and adds the keep-bind donor once per
**carrier group**: each non-shadow group with 100+ LOD-0 vertices covering half of the chest band (0.62-0.75 of the
height). The donor material is one of the class's own (opaque or alpha-clip / damage-map transparency, a plain,
neutral or blood-overlay colour mask, diffuse >= 0.75, a `0x2B` albedo >= 256x256); its atlas goes in as Y'CbCr.
MT keeps one resource per path and the zombie classes share their `em5000_*` albedos (uEm5000 and uEm5200 load
together on Rooftop Mission), so a shared path is used only when every archive that can load beside it is dressed too,
and each copy gets the same atlas (`re6_enemy_cast.Paths`, `share_atlases`, `consistency`).

The census of all 20 sets, the gate per class and the fit report per donor are in the probe build's receipt
(`recovery-re6-enemy-cast-01-20261110`, `.gbox-enemy-cast.json` in the build folder on lilspark): 13 classes dressed
(J'avo 1000 / 1200 / 1400, zombies 5000 / 5050 / 5060 / 5181 / 5191 / 5200 / 5210 / 5400, Shrieker 5500, Ubistvo
4300), 82-99 % of each No Mercy stage's placements; left native: the dogs (5700), Napad (3200), Whopper (5600, no
usable material), Lepotitsa (4100, displaced body), Strelats, Mesets, Gnezdo, Chrysalid, Rasklapanje, Ogroman.
Offline-verified only (`verify_class` from a fresh process, archive and MOD byte round trips); never booted. The
branch's final code (`family_subs`) also counts a family's lettered sub-archives as loadable, so it leaves Ubistvo
native (its only usable albedo is also in `uEm4301Pipe`); rebuilt with it, 11 of the 13 archives come out
byte-identical and the Shrieker takes the donor Ubistvo had (the receipt's `reproduction`).

## 5. Boot order, and what each boot must show

One change per boot, cheapest information first; every build goes to lilspark with `switch_mods op=write` (paths
`romfs/nativeNXx64/arc/NX/<archive>`); separate files compose by being in one build.

1. **The bot, no build.** An RE6 entry `{"title": "re6", "mode": "no_mercy", "character": "Chris", "stage": 2}`. Must
   show in the stats: `directive_active` set by the doctrine (`hunt` when nobody is in sight), `combo_window_full` about
   15, `combo_pace_s` rising during combos, `stand_breaks` only when he is stuck, `locates`. A click on an enemy on the
   tactical map must take (`map_goals_taken`, `map_goal_status`, a `re6_switch` line in `map-goals.log`) and the bot
   must run to it and down it; a double-click on a spot must walk him there and close `completed`. Failure: the map
   refusing marks means the frame has no `goal_round` (a worker without this code).
2. **`re6-enemy-pool-keep-v1`** at Mining the Depths (stage 2). The live-proven `keep` mode only.
3. **`re6-stage-greybox-v1`** at Mining the Depths; on odd colours, `re6-stage-greybox-v1-luma`.
4. **`re6-enemy-pool-v1`** (Mario reposed: the first `pose` body ever loaded).
5. Greybox + a pool together; then the stage rotation in the queue.

## 6. MercMode: RE6 beside RE5 on lilspark

Read live (GET `/api/mercmode`, 2026-11-09 ~23:40 UTC): lilspark `enabled: true`, `titles ['re5', 're6', 're4']`,
`preferred_editions` pinning RE5 / RE6 / RE4 Switch, `rounds_per_title 1`, `keep_warm 0`, `repeat_queue true`, the queue
full (20: 19 RE5 on `recovery-greybox-s400-pool-test-20261109`, 1 RE4).

| # | what | code | state / what to do |
|---|---|---|---|
| 1 | The edition | `re_switch.py:51-53` `EDITIONS['re6']`, `:56-66` `normalize_preferences`, `:69-83` `preferred_spec` | live: `preferred_editions.re6 = {"platform": "switch", "mode": "no_mercy", "title_id": "01002A000CD48000"}`; without it RE6 is the Xbox 360 disc (`mercmode.py:122-132`) |
| 2 | In the rotation | `mercmode.py:21` `DEFAULT['titles']` | live: `re6` is in `titles` |
| 3 | A queue entry | `mercmode.py:194-200` `catalog()` (RE6: `no_mercy` x Leon ... Agent, the ten stages in select order), `:203-230` `queue_entry`, `QUEUE_MAX = 20` (`:88`) | `{"title": "re6", "mode": "no_mercy", "character": "Chris", "stage": 2, "mod": "<build>"}`; `stage` is the **select index** (Mining the Depths = 2 = `s1208`); the queue is full: replace RE5 entries to add RE6 ones (`job_mercmode op=configure`) |
| 4 | The pick reaches the menus | `mercs_bot.py:555-563` -> `re6_switch.request` (`:130`) | the character and stage go to the selects; the costume is random every round |
| 5 | The build loads at boot | `screensaver.py:1529-1540` `mod_rotate` | a queued `mod` for the running title loads at the next boot; the same build as the running one is no restart. RE5 and RE6 are both Switch on the one Eden: every title change is a park and cold launch |
| 6 | Round boundaries | `engine.py:353-366` (`publish_boundary` through the tactical sink at results or death), `tools.py:3484-3491` (`tactical` passed to `mercs_bot.play`), `mercmode.py:1087-1091` (`ROUND_MIN_S 75`, `accept_boundary`), `screensaver.py:1485-1514` | RE6 Switch posts native boundaries (engine-level, title-agnostic; the driver's `result_ready` gates the results tally); `rounds_per_title 1` then rotates. A death answers NO (`REPLAY_ON_DEATH False`, `re6_switch.py:267`): saving, the selects, a new pick; a death under 75 s counts as a retry |
| 7 | A stuck turn | `screensaver.py:57` `NO_PROGRESS_S 600`, `:1125-1165` `_no_progress` | ended after 600 s without a boundary or kills / score progress (RE6 reads both) |
| 8 | The idle demo | `mercmode.py:322-334` `replaced_editions` | the Xbox 360 RE6 ids are out of the idle demo while the pin is set |

Risks before RE6 rounds rotate unattended:

1. **The save** (handover section 4.8): a scripted press through "Now saving" corrupted it once and every stage load crashed. The
   bot returns no key on saving / loading screens; moving the save aside was approved by the operator.
2. **The update's RomFS.** The host's RomFS (`~/gBox_alt/switch/romfs/01002A000CD48000`, extracted 2026-11-05) is the
   base game's; the 1.0.2 update's BKTR RomFS is not extracted (the DeepSeek lane's round 5). If the update replaces
   `s1208.arc` or a `uEm` archive, a LayeredFS overlay built from the base file would undo the update for that file -
   a mismatch the boot would show as a crash or the native look. The live-proven Sonic build was made from this RomFS
   and played, which says nothing about the stage files. Extracting the BKTR RomFS (or its file list) settles it.
3. **One emulator.** RE5 and RE6 share lilspark's Eden; a `mod` entry for the other title is always a cold boot.

## 7. What was run, what was measured, what is inferred

Run: the test suites below; the read-only copies (`s1208.arc`, the 20 `s12xxSoft.arc`, `Merce.arc`, `uEm1000.arc`,
`uEm1000Base.arc`, `uEm1400.arc`; the first 256 KB of each `s120N.arc` for its table of contents - about 125 MB in all,
SHA-256 of `s1208.arc` checked against the host's); read-only `ssh spark` listings and the learned stage books;
GET `/api/mercmode`; the greybox, luma and both enemy builds; `verify` from a fresh process; the previews.

Measured: every table above (formats, offsets and agreements, bindings, censuses, bone ids, transforms, groups, hashes).

Inferred, with the reason: `s1208` = Mining the Depths (the live nav-mesh note and the stage book's identical counts;
the undersea content agrees); the up / side / down of the two normal-less formats (the face winding the other formats
agree on); that group 3 is the J'avo's always-drawn body group (it is the one group both bodies share at every LOD);
that `_KNOWN_OBJECTS`' names suffice for the stage MRLs (measured, not inferred: the same 116 albedos and the one
unbound command resolve with the shader package's names).

Tests: `test_re6_switch.py` + `test_re6_fast_menus.py` 236 passed (17 were red); `test_re6_switch_parity.py` 22,
`test_re6_stage_greybox.py` 8, `test_re6_switch_enemies.py` 6 (2 read the local J'avo inputs, skip without them); the
RE6 / mercs / tactical suites 782 passed with the 9 failures already red on the base.

## 8. Reproduce

```powershell
$py = 'C:\_tools\gBox\.venv-session-audit\Scripts\python.exe'
cd C:\_tools\gBox-wt-re6-parity\system
$in = 'C:\_tools\gBox\.scratch-merc-recovery\re6\inputs'
$out = 'C:\_tools\gBox\.scratch-merc-recovery\assets\re6'
& $py -m gbox.re6_stage_greybox survey $in\stage\s1208.arc --stage s1208 > survey.json
& $py -m gbox.re6_stage_greybox build  $in\stage\s1208.arc --stage s1208 --out $out\re6-stage-greybox-v1
& $py -m gbox.re6_stage_greybox build  $in\stage\s1208.arc --stage s1208 --luma --no-preview --out $out\re6-stage-greybox-v1-luma
& $py -m gbox.re6_stage_greybox verify --original $in\stage\s1208.arc --candidate $out\re6-stage-greybox-v1\romfs\nativeNXx64\arc\NX\s1208.arc --receipt $out\re6-stage-greybox-v1\receipt.json
# enemies: re6_switch_enemies.stage_census(soft), body_check(arc), plan_pool(classes, re6_switch_cast.donor_pool(lib)),
# build_pool({stem: path}, lib, assignment, out_dir, name=...)
```
