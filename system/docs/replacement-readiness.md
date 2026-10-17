# Replacement readiness

Operator requirement (2026-10-13): every title we extract people from should also set up retargeting and rapid
replacement data, so that mods and replacements work quickly and without problems.

`gbox/replacement_readiness.py` does three things:

- It gives every collected character a stored, versioned readiness record.
- It gives every target game a slot table with that game's budgets.
- It keeps a donor x slot compatibility index, so "who can replace this?" is a lookup. Nothing is extracted again and
  no model file is opened to answer it.

## The shared post-collect step

Every collection path writes its entry through `characters.add()`. That covers the DEDICATED readers, the No Mercy RAM
reader, OoT, capture cut-outs, `op=add` edited models, sprite capture and Blender variants. `add()` now runs
`characters.post_collect()` (which calls `replacement_readiness.post_collect`) before it writes `meta.json`, so a new
reader gets the step automatically.

A stored entry is brought up to date in three places:

- `extract_dedicated` (the `in_collection` path, so every `characters op=collect` run backfills its roster).
- `characters op=readiness`.
- The index, which reads only the stored records.

The step never raises. If it fails, the failure is recorded as `readiness.status = blocked` with the reason.

Readiness is recomputed when any of these changes:

- `READINESS_VERSION`
- the model file (its size and mtime)
- `rig.roles`, for example after a Retarget editor or OoT role guess

No reader needs to run again for this. Every field below is derived from the stored model. `READER_VERSIONS` were not
bumped, because no reader output lacks data that a re-run would supply. The Def Jam GC reader has no rig, but running
it again would not add one.

## The entry standard (`meta["readiness"]`)

| Field | What it holds |
|---|---|
| `model` | `format`, `up` (`+Y` expected; `+Z`/`-Y`/`+X` are flagged), `height` in model units, `unit` (`m` when 0.3-3 tall, else `units`) with `to_metres` (measured, or an estimate that assumes a 1.7 m figure), `bounds` |
| `rig` | `skinned`, `skins`, `joints`, `inverse_bind`, `roles_mapped`, `roles_source` (`reader` / `auto:name` / `auto:tree` / `auto:pose` / `guessed`), `roles_absent` (every one of the 18 `retarget_profile.ROLES` that is not mapped, with the reason: creature, sprite, no clavicle joint, no neck joint, unidentified), `sanity` (role map problems) |
| `bind` | rest `pose` (`T` / `A` / `arms_down`), `arm_drop_deg` per side, `inverse_bind` |
| `proportions` | fractions of figure height: `hip_height`, `head`, `l_arm` / `r_arm`, `l_leg` / `r_leg`, `shoulders`, `arm_span`. Also `height` and `ground` |
| `facing` | facing from the role sides and, separately, from the feet; `mirrored_suspect` when the two disagree |
| `textures` | image list (w, h, mime), `count`, `max_side`, `texels`, `materials`, `textured_materials`, `alpha`, `atlas` (one image) |
| `mesh` | `triangles`, `vertices`, `primitives`, `meshes` |
| `skin` | `max_influences`, `mean_influences`, `histogram`, `skinned_vertices`, `rigid_vertices`, `unweighted_vertices` |
| `kind` | `humanoid` / `creature` / `sprite` / `prop`. `meta.kind` keeps the collection's own kind |
| `hints` | default retarget hints, never applied automatically: `up_fix`, `to_metres`, `facing`, `pose`, `profile.head` for chibi proportions (head over 22 % of height), `rigid`, `decimate_from` |
| `status` | `ready` / `limited` / `blocked` / `n/a`, plus `missing` (what blocks or limits it), `warnings`, and `fixed` (what the step derived and stored) |

What each status means:

- **ready**: a humanoid with all 15 retarget roles mapped (`RETARGET_ROLES`, which is `doa2_swap.REQUIRED_ROLES`), a
  sane role map and `+Y` up; or a sprites sheet.
- **limited**: a creature, missing retarget roles, a role map that fails the sanity check, or a model that is not `+Y`
  up.
- **blocked**: no model file, an unreadable model, no triangles, or a character with no skin.
- **n/a**: vehicles, objects and environments.

### What the step fixes automatically

The step only fills gaps. It never replaces roles that a reader or the operator set.

1. **Role bone case.** A role whose bone matches no joint exactly, but matches exactly one joint when case is ignored,
   is rewritten to the joint's real name (`roles_case_fixed`). Writers look bones up by exact name, so these roles were
   being lost. Example: the GTA III reader stores `smid` for the GLB joint `Smid`.
2. **Body roles for an entry without a hip.** The first source is the entry's own reader's role reader
   (`characters.ROLE_BACKFILL`: PSO, SM64). After that come joint names (Mixamo, Biped, Unreal/Unity, `L_`/`R_`,
   `.L`/`.R`, gBox's own `l_upper` ...), then the limb tree (`characters.tree_roles`), then the rest pose
   (`oot_swap.guess_model_roles`). A result is stored only when it passes `sanity()`. It is marked with
   `rig.roles_guessed` and `rig.roles_source`. The whole map is written, including the hierarchy fills below.
3. **Missing retarget roles beside reader roles.** These are filled from the auto map when its hip agrees, and from the
   hierarchy:
   - the chest where the arms meet, or the spine joint above the hip when the arms branch off the hip
   - a lone child joint as the forearm, hand, shin or foot

   Filled roles are recorded in `rig.roles_filled`. Optional roles (the neck, and a clavicle between the chest and the
   upper arm) are not written into a reader-mapped entry, because builds that work today should keep fitting exactly as
   they did. They go to `readiness.suggested_roles` and are named in `roles_absent`.
4. **Missing `stats` and rig joint counts.**

A role that is absent because of the skeleton's structure is explicit and does not limit readiness. Examples: no neck
joint, no clavicle, arms that branch off the hip, a limb that ends at the forearm or shin. A writer that needs such a
role says so in the compatibility row, through its spec's `required`.

## Target slots (`SPECS`, `spec_for`, `slot_table`)

Each writer has a target description in `SPECS`. It covers:

- the skeleton, and the role map from the module's own constant (`ORDER`, `LINK_ROLES`, `LCS_ROLES`, `GTA3_ROLES`,
  `GLITCH_ROLES`, `SNAKE_ROLES`, `PLAYER_ROLES`, `JOINTS`, `LEON_ROLES`, `REQUIRED_ROLES`)
- the required donor roles
- budgets: triangles (`MAX_TRIS`, `BUDGETS[0]`, `PSO_BUDGETS[0]`), vertices (`MAX_VERTS`, `SLOT_VERTEX_CAP`), the
  largest texture side, and influences per vertex
- whether the writer decimates
- donor limits (MGS VR and MGS1 accept only `hucast` today)

A writer module can override its entry with `REPLACEMENT_SPEC = {...}` and can widen its donors with `DONORS = [...]`.

`slot_table()` builds one row per game that has a writer or a collected entry. Each row holds the reader, the writer,
whether `op=use` routes the writer, and the slots. Slots come from `cast_swap.slot_rows`, which drops aggregates.
If a game has no rows, its fixed slots come from `char_coverage.WRITERS`.

## Compatibility index

`compat(donor summary, spec)` returns:

- `ok`
- `fit`: `fits`, `decimate` (with `ratio`), or `over` (when the writer can't decimate)
- `missing_roles`: target roles the donor lacks
- `blocking`: for example a sprite into a 3D slot, a 3D model into a sprite slot, no hip or other required roles, a
  model that is not `+Y` up, a donor the writer doesn't accept yet, or a blocked entry
- `notes`: influences reduced to N (rigid), textures downsized, entry limited, arms-down pose
- `score`

Roles that the operator saved in a Retarget editor profile for that game also count.

`index(root)` keeps one summary per donor plus a row per writer. It lives in memory and in
`<library>/.replacement/index.json`. The folder has no `meta.json`, so it is never a collection entry. A stored index is
reused only by code with the same `code_digest()`.

How the index stays current:

- `characters.put_meta()` calls `invalidate(root, slug)`.
- Every look after the 30 s quiet window compares each donor's summary with its stored meta. This is cheap and reads no
  files, and it also catches writes made by another process.
- Only the donors that changed have their rows recomputed.

## API

These routes are registered by `server.py` and can be used by the pick whip, cast swap and Special builds:

- `GET /api/replacement/candidates?game_id=&slot=[&all=1][&limit=N][&kind=humanoid]`: who can replace the slot,
  ranked. Each candidate has fit, ratio, missing roles and notes. `all=1` also lists the donors that don't fit, with
  the reason.
- `GET /api/replacement/donor/{slug}`: every game with a writer, and whether this donor fits it, with the reason.
- `GET /api/replacement/slots[?game_id=]`: the slot table and the target spec.
- `GET /api/replacement/report[?game_id=][&format=md]`: the per-game report below.
- `POST /api/replacement/refresh`: rebuild the index from the stored metas.

`characters op=readiness [game_id] [character] [rebuild=true]` runs the backfill where the library lives (the control
plane). It computes or refreshes stale entries, rebuilds and saves the index, and returns the report. On any other
node it returns the control plane's report.

## Snapshot (scratch copy of the Spark library, 2026-10-13)

The pass ran on a read-only copy of the Spark library (653 folders: `meta.json` plus each entry's model) with
`replacement_readiness.backfill`. It took 20 s on this PC for 652 entries and wrote only to the scratch copy. No catalog
was available, so platforms were guessed from the titles.

### Fixed automatically (18 entries)

- **8 PSO classes** (HUmar, HUnewearl, RAmar, RAcast, RAcaseal, FOmarl, FOnewm, FOnewearl) got their body roles from
  the reader's own role reader (`characters.ROLE_BACKFILL["pso"]`, which reads `manifest.json`). They had been stored
  without roles, so the cast swap gate refused them.
- **GTA III `gta3_claude_x`**: every role named a lowercase bone (`smid`, from `GTA3_ROLES`), but the GLB's joints are
  `Smid` ..., so writers found none. The names were matched to the joints. The reader still writes lowercase names; the
  post-collect step corrects every new collect.
- **FF7 Cloud x 4**: chest filled from the spine. The arms branch off the hip, and `j02` is the spine joint below the
  head.
- **PE Aya**: chest filled (pose guess).
- **FF7 Yuffie (field)** and **MGS VR Snake (`mgs_vr_snake_f55555ee6513391b`)**: they had no roles, so the full map was
  derived (pose guess).
- **RE4 remake Ashley / Leon**: they had no roles, so the full map was taken from Biped-style joint names.

Optional roles that a reader left out (neck, clavicles) are not written into `rig.roles` of a reader-mapped entry,
because builds that work today should keep fitting exactly as they do. They are stored as
`readiness.suggested_roles` and named in `roles_absent`. 108 entries carry suggestions:
SmackDown! 2 (66), JGR (16), SA2 (12), SA1 (8), Metal Arms (2), SM64 (2), PSO HUcast and one Def Jam PS2 wrestler.

### Not ready (gaps per game)

| Game | Gap | Who fixes it |
|---|---|---|
| Def Jam: Vendetta (GameCube) | all 57 entries are blocked: static `.gpl` meshes with no skin ("rig not decoded yet") | the reader (`defjam_vendetta`) must decode the rig; until then the PS2 reader's 58 wrestlers are the Def Jam donors |
| GTA Liberty City Stories | 1 of 18 entries has no skin | the reader |
| Resident Evil 6 (`re6_helena`) | the roles name `b001` (hip), the arms and legs, but those bones are not in the model's skin, so writers lose them | re-export from the RE6 tool with the full skin |
| Super Smash Bros. Melee | Jigglypuff: both thigh roles are one point. Yoshi: rotated (+Z up), feet above the hip. Kirby: a creature (no humanoid roles) | reader role maps; Kirby needs a Retarget editor role map |
| FF7 | Red XIII: the reader's humanoid map puts a foot above the hip (quadruped). Cait Sith (field): creature | Retarget editor role map when one is used as a donor |
| FF7 Tifa | `r_hand` unidentified (the forearm has several children) | reader role map |
| Metal Arms (`ma_zobby`) | model is +Z up (head-hip axis); left/right suspect | reader export orientation |
| No writer yet | Def Jam GC, RE4 (2023), Shenmue, Sonic Adventure, Melee, Tetris DS (entries are donors only) | writers (`characters op=coverage` already files the gaps) |
| No DEDICATED reader | Metal Gear Solid (disc 1/2: the writer exists, HUcast only), Resident Evil 6, RE4 Wii | readers |
| Writer limits | MGS VR / MGS1 accept only the `hucast` donor today (spec `donors`; a writer module can widen it with `DONORS`) | MGS writers |
| Budgets | DOA++ (395-vertex slot cap) needs decimation for every donor. PE2 (1024 vertices), SM64 (1600 triangles) and OoT (1500) fit 203 / 379 / 364 of 513 donors without decimation | writers decimate automatically |
| Slots read at build time | WCW Revenge and World Tour list only `player`: their rosters come off the ROM (`aki_wcw`) | fine for op=match; the cast menu shows them after a ROM read |

READER_VERSIONS: nothing was bumped. Every gap above is either derived without re-extraction (fixed by the step) or
needs reader work that a re-run of the current reader would not supply.

### Report

Entries: 652 (585 ready, 7 limited, 58 blocked, 0 unchecked, 2 not characters; 18 fixed automatically). Writers: 40 (40 with routed slots and compatible donors).

| Game | Reader | Entries (ready / limited / blocked / unchecked) | Main reasons | Writer | Slots | Compatible donors (no decimation) | Writer gaps |
|---|---|---|---|---|---|---|---|
| 007 - Agent Under Fire (USA) | auf v2 | 37: 37 / 0 / 0 / 0 | - | gbox.auf_swap | 49 | 513 (513) | - |
| Clay Fighter: Sculptor's Cut (USA) | clayfighter | 0: 0 / 0 / 0 / 0 | - | gbox.clayfighter_swap | 17 | 76 (76) | - |
| Crazy Taxi (USA) | crazy_taxi | 1: 0 / 0 / 0 / 0 (+1 not characters) | - | gbox.crazy_taxi_swap | 54 | 513 (513) | - |
| Dead Or Alive ++ (Japan) | doapp | 0: 0 / 0 / 0 / 0 | - | gbox.doapp_swap | 12 | 513 (0) | - |
| Dead or Alive 2 - Limited Edition (Japan) | doa2 | 15: 15 / 0 / 0 / 0 | - | gbox.doa2_swap | 14 | 510 (510) | - |
| Def Jam - Vendetta (USA) | defjam_vendetta_ps2 | 58: 58 / 0 / 0 / 0 | - | gbox.defjam_writer | 44 | 513 (396) | - |
| Enter the Matrix (USA) - the PS2 disc SLUS-20454 (HyperSpin CHD filed as windows_native) | etm | 0: 0 / 0 / 0 / 0 | - | gbox.etm_swap | 36 | 513 (513) | - |
| Final Fantasy VII (USA) (Disc 1) | ff7 | 14: 12 / 2 / 0 / 0 | creature: no humanoid body roles; humanoid slots need a role map (Retarget editor) (1); role map: r_foot is above the hip (1) | gbox.ff7_swap | 1 | 513 (513) | - |
| Final Fantasy VII (USA) (Disc 2) | ff7 | 0: 0 / 0 / 0 / 0 | - | gbox.ff7_swap | 1 | 513 (513) | - |
| Final Fantasy VII (USA) (Disc 3) | ff7 | 0: 0 / 0 / 0 / 0 | - | gbox.ff7_swap | 1 | 513 (513) | - |
| Grand Theft Auto - Liberty City Stories (USA) | gta_lcs | 18: 17 / 0 / 1 / 0 | no skeleton (skin): the reader must export a rig before it can be retargeted (1) | gbox.gta_stories_models | 1 | 513 (513) | - |
| Grand Theft Auto III (USA, Canada) | gta3 | 3: 3 / 0 / 0 / 0 | - | gbox.gta3_swap | 1 | 513 (513) | - |
| Grand Theft Auto Vice City | gta_vc_pc | 0: 0 / 0 / 0 / 0 | - | gbox.gta_vc_swap | 1 | 513 (498) | - |
| Grand Theft Auto: Vice City (USA) | gta_vc_pc | 0: 0 / 0 / 0 / 0 | - | gbox.gta_vc_swap | 1 | 513 (498) | - |
| Jet Grind Radio (USA) | jgr v2 | 16: 16 / 0 / 0 / 0 | - | gbox.jgr_swap | 16 | 513 (513) | - |
| Legend of Zelda, The - Ocarina of Time - Master Quest (Europe) (GameCube Edition) | oot | 2: 2 / 0 / 0 / 0 | - | gbox.oot_swap | 89 | 513 (364) | - |
| Legend of Zelda, The: Ocarina of Time (USA) | oot | 5: 5 / 0 / 0 / 0 | - | gbox.oot_swap | 89 | 513 (364) | - |
| Metal Arms - Glitch in the System (USA) | metal_arms | 8: 7 / 1 / 0 / 0 | model is +Z up: re-export it +Y up (1) | gbox.metal_arms | 2 | 513 (459) | - |
| Metal Gear Solid (USA) (Disc 1) | - | 0: 0 / 0 / 0 / 0 | - | gbox.mgs1_swap | 1 | 1 (1) | - |
| Metal Gear Solid (USA) (Disc 2) | - | 0: 0 / 0 / 0 / 0 | - | gbox.mgs1_swap | 1 | 1 (1) | - |
| Metal Gear Solid - VR Missions | mgs_vr | 1: 1 / 0 / 0 / 0 | - | gbox.mgs_vr_swap | 1 | 1 (1) | - |
| Metal Gear Solid - VR Missions (USA) | mgs_vr | 1: 1 / 0 / 0 / 0 | - | gbox.mgs_vr_swap | 1 | 1 (1) | - |
| Parasite Eve (USA) (Disc 1) | parasite_eve | 5: 5 / 0 / 0 / 0 | - | gbox.pe_swap | 1 | 513 (513) | - |
| Parasite Eve (USA) (Disc 2) | parasite_eve | 0: 0 / 0 / 0 / 0 | - | gbox.pe_swap | 1 | 513 (513) | - |
| Parasite Eve II (USA) (Disc 1) | pe2 | 0: 0 / 0 / 0 / 0 | - | gbox.pe2_swap | 1 | 513 (203) | - |
| Parasite Eve II (USA) (Disc 2) | pe2 | 0: 0 / 0 / 0 / 0 | - | gbox.pe2_swap | 1 | 513 (203) | - |
| Phantasy Star Online Ver. 2 (USA) | pso | 9: 9 / 0 / 0 / 0 | - | gbox.pso_player | 20 | 513 (255) | - |
| Resident Evil 4 (USA) (Disc 1) | re4gc | 1: 1 / 0 / 0 / 0 | - | gbox.characters.build_re4 (+ re4wii) | 1 | 513 (513) | - |
| Resident Evil 4 (USA) (Disc 2) | re4gc | 0: 0 / 0 / 0 / 0 | - | gbox.characters.build_re4 (+ re4wii) | 1 | 513 (513) | - |
| Resident Evil 4: Wii Edition (USA) | - | 0: 0 / 0 / 0 / 0 | - | gbox.characters.build_re4 (+ re4wii) | 1 | 513 (513) | - |
| Resident Evil 6 | - | 2: 1 / 1 / 0 / 0 | roles unmapped (1); role map: roles name joints the model lacks: hip, l_foot, l_fore, l_hand, l_shin, l_thigh; (1) | gbox.re6_tool | 1 | 513 (513) | - |
| Sonic Adventure 2 (USA) | sa2 | 13: 12 / 0 / 0 / 0 (+1 not characters) | - | gbox.sa2_chars | 1 | 513 (345) | - |
| Super Mario 64 (Europe) (En,Fr,De) | sm64 | 1: 1 / 0 / 0 / 0 | - | gbox.sm64_swap | 1 | 513 (379) | - |
| Super Mario 64 (USA) | sm64 | 1: 1 / 0 / 0 / 0 | - | gbox.sm64_swap | 1 | 513 (379) | - |
| WCW vs. nWo: World Tour (USA) | worldtour | 45: 45 / 0 / 0 / 0 | - | gbox.aki_wrestling | 1 | 513 (513) | - |
| WCW-nWo Revenge (Europe) | revenge | 0: 0 / 0 / 0 / 0 | - | gbox.aki_wrestling | 1 | 513 (513) | - |
| WCW-nWo Revenge (USA) | revenge | 92: 92 / 0 / 0 / 0 | - | gbox.aki_wrestling | 1 | 513 (513) | - |
| WWF No Mercy (Europe) (Rev A) | nomercy | 0: 0 / 0 / 0 / 0 | - | gbox.aki_wrestling | 64 | 513 (513) | - |
| WWF No Mercy (USA) | nomercy | 64: 64 / 0 / 0 / 0 | - | gbox.aki_wrestling | 64 | 513 (513) | - |
| WWF SmackDown! 2 - Know Your Role (USA) | smackdown2 | 66: 66 / 0 / 0 / 0 | - | gbox.yukes_sd | 66 | 513 (513) | - |
| Def Jam - Vendetta (USA) | defjam_vendetta | 57: 0 / 0 / 57 / 0 | no skeleton (skin): the reader must export a rig before it can be retargeted (57) | - | - | - | no writer |
| Resident Evil 4 | re4r | 2: 2 / 0 / 0 / 0 | - | - | - | - | no writer |
| Shenmue (USA) (Disc 1) | shenmue | 1: 1 / 0 / 0 / 0 | - | - | - | - | no writer |
| Sonic Adventure (USA) | sa1 | 8: 8 / 0 / 0 / 0 | - | - | - | - | no writer |
| Super Smash Bros. Melee (USA) | melee | 30: 27 / 3 / 0 / 0 | role map: l_thigh and r_thigh are the same point (1); creature: no humanoid body roles; humanoid slots need a role map (Retarget editor) (1); role map: l_foot is above the hip; r_foot is above the hip (1) | - | - | - | no writer |
| Tetris DS (USA) | tetris_ds | 76: 76 / 0 / 0 / 0 | - | - | - | - | no writer |

