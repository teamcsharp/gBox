# 007 Agent Under Fire (GameCube) character writer

`gbox/auf_swap.py` (writer, slots, cast plan) and `gbox/auf_gcm.py` (the `.gcm` model encoder and the level
texture edits) put collection characters into 007 Agent Under Fire (USA, GW7E69, gBox game `65b7187589166b26`):
Bond, the mission enemies, the bosses, everyone else, and the multiplayer bots. One build can replace the whole
cast, which is what #1529 asks for ("replace every character with wrestlers from the WWE games ... randomly selects
characters from the list"). Tickets: #1438 (pick-whip program, stage 3 "writer for any entity slot"), #1362 (AUF
readiness, writer stage), #1529.

Status: built and checked offline (encoder round trip on every shipped character model, rebuilt levels read back
by the reader, disc image read back). On 2026-10-13 the two whole-cast builds (section 5, "Builds for #1529 and
#1385") booted in an agent-owned Dolphin on the test PC: the first mission's opening cut scene and multiplayer bot
matches showed the donors textured and animated, with no crash. The other checks in section 7 are still open.

## 1. Where the characters are

Everything was read from the owned disc (GCZ sha256 `00a0ebbd…93faac`) and its `Bond.elf` (sha256
`1a9c0d19…e716f`, symbols kept). See `gbox/auf_ngc.py` for the package, BOA and restable layer and
`docs/auf-entity-analysis.md` for the entity table.

* Each level is one `maps/*.ngc` package (38 of them). Its `restable` chunk is the level's file system, and the
  characters live there: models `models/actors/**.gcm` and entity definitions `models/*.men`.
* The EAGL `.viv` bigfiles are not involved. They belong to `driving.elf` (the driving missions), not to the FPS
  levels.
* A `.men` is a compiled entity script. It starts with a `CS` header; from +0x24 it holds u16 tokens that index the
  level's `script_dictionary`, whose NUL-separated strings start at +0x20, and `0xFFFF` separates tokens.
  `auf_swap.level_cast` decodes them. For example, `mp_player_bondcombat.men` reads
  `setup { path models/actors lod_model { Bond/Bond_Combat_l.o3d } lod_head { ActorHeads/bond_head_l.o3d } } init { server { classname DeathmatchPlayer } } animations mp_player_male`.
  A `lod_model` lists `name near far` triples for each LOD (`_h`/`_m`/`_l`). The `.o3d` names resolve to
  `<path>/<name>.gcm`.
* Classes found: `Player` (Bond in the missions, 20 levels), `actor` (enemies, bosses, allies, hostages, and Bond
  in cut scenes), and `DeathmatchPlayer` (the 16 multiplayer characters that players and bots pick, in the 17
  dm/escort levels). The 38 levels hold 45 distinct body models (`auf_swap.NAMES`). `level_keys()` is a snapshot of
  which body is in which level. The owned-disc test checks the snapshot against dm1, m6_1 and alp2_2.

## 2. Format facts and confidence

**High** means read from Bond.elf code and holding on all shipped data. **Medium** means measured on the data with
no contradicting code. **Low** means inferred.

| Fact | Evidence | Confidence |
|---|---|---|
| `.gcm` = chain of blocks `{u32 type, u24 body size, u8 extra}` + pad + body, 8-aligned; header pointers are block offsets that `C_Object3D::FixupModelData` 0x80183968 / `FixupHeaderOff` 0x80183AF4 relocate to bodies | code; all 127 unique actor models walk exactly | high |
| Header: +0x0C file size, +0x20 bbox centre, +0x30 half extents, +0x40 radius = max \|v-centre\|, +0x50 bones, +0x54 palette records, +0x56 morph targets, +0x58 hit boxes, +0x5A material names, +0x64 vertex count, +0x68 triangle count | code (+0x54 `BuildMatrixList`, +0x5A `LoadMaterials` 0x801773A4); radius exact on shipped bodies | high (counts: medium) |
| Header +0x10 vec3, +0x5C, +0x60, +0x6C: kept from the slot's own model (not read by the draw path) | not referenced by `R_DrawGeomSection` / `BuildMatrixList` | medium |
| Blocks: +0x74 bones `{s32 parent, u32 name hash}`, +0x78 rest pose `{pos, pad, quat}`, +0x7C palette `{s16 a, s16 b (-2 rigid), f32 w}`, +0x80 NGC geometry, +0x84/+0x88 morphs, +0x8C hit boxes (64 bytes per bone box), +0x94 material names (64-byte strings) | code + data | high |
| Section shader id = `HashString(material name i)` (`SHDR_GetIDFromString` 0x801872E8); `LoadMaterials` looks the names up with `SHDR_LookupIDX` (linear, unsorted) | code; 3/3 names of bond_combat_l hash to its section ids | high |
| Palette record = `MtxFromQuat(slerp(q_b, q_a, w), pos_a)` of the animated pose (vertex rotates about bone a's joint) | `BuildMatrixList` 0x8017A674 | high |
| Palette matrices come from a per-frame bump allocator, 0x84 bytes each, **no bounds check** (`ObjCntrl_AllocMatrices` 0x8017A13C) → a rewritten model never uses more records than the slot had (+ those of a head it stubs) | code | high |
| Geometry: sections → groups (≤ 10 palette records loaded into PNMTX0..9 = ids 0,3..27) → GX triangle strips over u16 ent_vtx indices; strip byte 7 = current matrix or 0xFF = per-vertex PNMTXIDX from the u8 list | `R_DrawGeomSection` 0x80179C44 | high |
| The group and strip loops (and each strip's vertex loop) are do-while: every section needs ≥ 1 group, every group ≥ 1 strip, every strip ≥ 3 vertices (the matrix-load loop is a while) | `R_DrawGeomSection` 0x80179D00..0x80179E94; 558/558 unique shipped `.gcm` follow it (`auf_gcm.decode_check`) | high |
| Positions s16 in the palette record's frame, dequantised by the 3x4 matrix at the geometry body start (full ±32767 range used per axis); normals s8 (length 127) in the same frame but transformed by `R_BuildNormalMtx(view·palette)`, i.e. without the dequantisation matrix; UV s16 frac 11 | `BuildViewMatrixList` 0x8017A5A4 + data | high (note: `auf_ngc.mesh` multiplies normals by the dequant matrix, harmless after normalising) |
| Character shaders: 1 group, 1 pass, flags 0x20000, CMPR texture (every actor shader in dm1) | data | medium |
| restxtrs records 0x44 bytes, image offsets chunk-relative (`TexMgr_InitTexture` 0x80185CFC) → a record can point at data appended to the chunk | code | high |
| Texture table: 512 entries at 0x8032AD58, count at +0x180C, `TexMgr_AddTexture` 0x80185E54 does not check → the writer never adds texture records | code | high |
| Bone name hashes are not `HashString` of 3ds Max biped names (no hit); roles come from topology instead | test | high (for the negative) |

Encoder checks: every one of the 127 unique actor models on the disc goes through reader → `encode_gcm` → reader
with the same triangles and winding. The worst vertex error is 0.0003 units, every array tiles, and the output is
about the shipped size. `auto_roles` finds all 18 body roles on all 127.

## 3. Limits the writer keeps

* **Palette**: at most the slot model's own record count, plus the records of a head it turns into a stub
  (`max_palette`). Skin weights are quantised in 0.1 steps, then 0.25, then 0.5, then rigid, until the records
  fit.
* **Matrices**: at most 10 palette records per group. Indices are u16 (65535 strips, list entries and vertices)
  and the palette index is a u8. No section, group or strip is empty, because the draw loops are do-while. A
  section whose faces all collapse is dropped, and a head stub draws one zero-area strip.
* **Triangles**: the donor gets at most 1.2 × the triangles of the slot's own LOD (body plus the head it stubs),
  and at least 300. Quadric-error decimation (`auf_swap.decimate`) brings it under budget. Each LOD gets its own
  budget, so `_h`/`_m`/`_l` stay graded. The whole restable is held in RAM, so the budget keeps memory growth
  small. In dm1 the player build grows the restable by about 6 KB (memory budget: medium confidence).
* **Texture**: no texture record is added and no image grows. The donor's materials are packed into the textures
  that only the replaced models used, and written over those textures' own bytes at their own size, CMPR format
  and mip count (`auf_gcm.write_texture_in_place`). A usable texture belongs to a shader with one group and one
  pass, is not referenced by the BSP, and is not used by any other shader. The texture chunk keeps its length and
  every record stays unchanged, so the level's texture memory does not change. A record's second I8 plane is left
  as it was. A Bond body typically frees 2 to 4 textures (dm1: bond_graysuit_coat 256×128, bond_combat_vest/pant
  and bond_graysuit_pant 128×128, Bond_head 128×128). Every donor needs at least one, otherwise the build stops
  with that message.
* **UV**: |uv| < 16 (s16 frac 11). The atlas uses the 0..1 range, and each triangle's repeats are shifted into its
  tile.
* **Disc**: `filemods.build_image` writes a copy of the image. A rebuilt level goes into its own FST slot when it
  fits, otherwise after the last file, 32 KiB-aligned, with its FST entry rewritten. The disc size is
  1,459,978,240 bytes. The new restable and restxtrs compress better than the shipped ones (dm1 restable 1.82 MB
  vs 1.91 MB), so rebuilt levels usually stay in their slots.

## 4. How a donor goes in

For each level and each body model:

1. **Target.** The body model's skeleton and rest pose, a T-pose with Z up, facing +X, left +Y.
   `auf_gcm.auto_roles` finds the body roles from the topology. The head height comes from the level's head model.
2. **Donor.** A rigged collection character (meta `rig.roles`) goes through `doa2_weighted_retarget` with skin
   weights kept, reduced to the strongest two bones per vertex. An unrigged T-pose mesh, such as the 57 Def Jam
   Vendetta GC wrestlers in the collection (static meshes with no skeleton), goes through `fit_static`. That maps
   heights through (ground, hip, shoulder, head top) and widths through (shoulder, finger tips) onto the slot, then
   skins each vertex to the nearest bone segment of its region (arm, leg by side, or spine/neck/head chain), blended
   with the parent near a joint.
3. **Texture pages.** The donor's materials (texture × colour factor, or a plain colour) are dealt by texel area
   over the textures the slot frees, largest first. Each page is a grid of tiles at that texture's size. Cut-out
   texels are filled because AUF draws characters opaque. Each page becomes one section of the model, named after
   the shader of the texture it was written into.
4. **Encode.** `encode_gcm` uses the slot model as template. Bones, rest pose, hit boxes and header vector are kept,
   so the native `.gca` animations, which bind by bone hash, still drive it. Palette, geometry and material names
   are rewritten, and morphs are dropped.
5. **Heads.** A head model that only replaced bodies wear becomes a stub: one zero-area triangle, skeleton kept,
   and it draws nothing, because the donor's head is part of the body. A head that a body outside the build also
   wears is kept, and the donor's head triangles are left out.
6. **Rebuild.** The level's restable (`auf_ngc_writer.build_restable`: records sorted by `HashString`, 16-aligned
   files, names, 32 padding) and its restxtrs (pages written in place) are re-encoded with the BOA compressor
   (in-place safe) and read back. The checks are the chunk walk, the record sort, every replaced model decoding,
   textures being exactly their mip chains, and the texture records and chunk length being unchanged. Levels are
   rebuilt in parallel worker processes.

## 5. Slots

`characters op=use game_id=65b7187589166b26 slot=...`:

| Slot | Replaces |
|---|---|
| `player` | every Bond body: tux (the mission player, `bond.men`), combat, grey suit, jetpack (cut scenes), multiplayer Bond tux/combat |
| `enemies` | the mission henchmen: henchmen_vest, thug_alpine_inside/outside, thug_carrier, thug_oilrig, thug_orchid, thug_uwb, superthug_body, biosuit (the same bodies in multiplayer stay) |
| `bosses` | Malprave (suit, gown), Bloch (zero, jetpack), Griffin, Jackal, the twins |
| `npcs` | Zoe, Natalya, hostages, the G8 leaders, R (scientist), embassy guards, missile officer, rig diver, the escort VIP |
| `bots` | every `DeathmatchPlayer` body in the 17 multiplayer levels (the 16 characters bots and players pick) |
| `campaign` | everyone in the 20 mission levels |
| `multiplayer` | everyone in the 17 multiplayer maps (the 16 bot characters and the escort VIP) |
| `all` | everyone |
| `model:<body>` | one body everywhere (e.g. `model:thug_orchid`, 21 levels) |
| `campaign:<body>` | one body in the mission levels only (e.g. `campaign:henchmen_vest`: m6_1, m6_2, m6_3) |
| `mp:<body>` (`bot:<body>`) | one body in the multiplayer maps only (e.g. `mp:henchmen_vest`: the henchman bot in all 17 maps) |
| `cast` | `pairs` = `[{target, donor}]`. A target is a body, `model:<body>` or a group. Narrower targets win over groups. Donors without a target are dealt over every body nobody named, using a seeded shuffle (`title` is the seed), so one body gets one donor across all levels and the same request builds the same disc. |

Pick whip (#1438): `auf_swap.slot_for_entity(model)` turns an entity's model string into its slot. The model
string is `Entity+0x28`, read by `gbox.entity_probe` with `profiles/auf-gcn-us.json`, e.g.
`models/mp_player_griffen.men` for a bot. That one gives `model:griffin_body`, so a whipped bot or enemy maps to
the body this writer replaces.

`op=collect` on the game returns these slots (`auf_swap.cast_slots`) and collects the cast itself
(`gbox/auf_chars.py`, reader v2; v1 listed the slots only and extracted nothing):
* All 45 bodies become library characters `auf_<body>`. Each comes from one representative level: the first mission
  level that has it, else the first multiplayer map.
* The entity that wears the body is picked by LOD (`_h` first), then class (Player, actor, then DeathmatchPlayer),
  then script name.
* The body and its head model become one skinned GLB on the body's skeleton. The head's bones are matched by hash,
  and its vertices are moved onto the body's rest pose.
* Each entry has the level's textures (opaque), the 18 `auto_roles` body roles, and the library frame (left +X,
  up +Y, facing +Z).
* Names and aliases come from the `.men` scripts: the script names, `classname`, and the `mp_player_<name>` names
  of the 16 multiplayer characters.
* Meta `auf_slot` = `model:<body>` links each entry back to its writer slot.
* Offline against the owned GCZ, the 45 entries are verified and retargetable and pass the cast-swap donor gate.
  `python -m gbox.auf_chars <gcz> <out dir> [body ...]` writes the GLBs without the library.

`characters op=coverage` lists the writer (`char_coverage.WRITERS`). The mod is named
`auf_<slot>_<plan hash>` and is built on the control plane, where the collection is.

"Replace every character with wrestlers" is one build: `slot=cast pairs=[{donor: sd2_the_rock}, {donor: nm_kane},
… every wrestler …]`, or (better) the whole-cast swap below.

### Whole-cast swap (`characters op=cast_swap`, #1529, #1385)

`cast_slots()` lists three kinds of rows. The groups (`player`, `enemies`, `bosses`, `npcs`, `bots`, `all`, `cast`,
`campaign`, `multiplayer`) and the 45 `model:<body>` rows are marked `aggregate`. Under them are the **57 context
slots** that `gbox.cast_swap` plans: `campaign:<body>` for each of the 40 bodies seen in the missions, and `mp:<body>`
for each of the 17 bodies in the multiplayer maps (16 bots, kind `bot`, and the escort VIP, kind `npc`). Every (level,
body) pair of the 372 belongs to exactly one context slot, so the campaign henchman and the henchman bot can wear
different donors. Each row carries `groups` (for example `mp:henchmen_vest` → `bots, all, multiplayer,
model:henchmen_vest`), its `levels` and its `kind`.

Before this, `cast_swap` treated `gbox.auf_swap` as a one-slot writer, so `slots=all` planned only `player`. The
writer now has a pairs path, `auf_swap.build_cast(ctx, game, [(slot, donor meta)], name)`:

* The level map is read off the disc itself (`disc_level_keys`: `level_cast` on all 37 levels, about 45 s from the GCZ,
  cached in `cache/<game>/auf_level_cast.json`). On the owned disc it equals the `level_keys()` snapshot in all 37
  levels. `cast_slots_live` feeds the cached map to the planner.
* Every slot's (level, body) pairs go into one plan, and each level is rebuilt once with every donor it needs
  (`build_mod`, 6 worker processes).
* A donor that does not load fails only its own slots. A level that cannot be rebuilt (for example too few free
  textures for its donors) stays stock, and its slots report `partial` with the level's reason (`_swap_job`).
* The marker gets the cast rows, `what` ("Replaces N mission characters (…) and M multiplayer characters (bots) with
  K donor characters in L levels") and `where_to_look`, which feed the Mods cards, the Builds rows and Special builds
  (`gbox.build_summary`).

Calls:

```
characters op=cast_swap target_game=65b7187589166b26 source=wrestlers assign=random seed=wrestlers \
    prefer=smackdown2,nomercy mod_name=auf_cast_wrestlers               # all 57 slots, distinct WWF wrestlers
characters op=cast_swap target_game=65b7187589166b26 source=sa2 assign=random seed=sonic \
    slots=campaign,bots mod_name=auf_cast_sonic_random                 # 40 campaign + 16 bot slots, SA2 at random
characters op=cast_swap target_game=65b7187589166b26 source=wrestlers slots=player,bosses,npcs,bots   # 48 slots
```

`slots=` takes groups, kinds and slot names, comma-joined (the union). The cast menu offers the target's own groups
(`slot_sets`: Everyone, Enemies, Bosses, NPCs, Bots, Campaign, Multiplayer, Campaign + multiplayer bots).

### Builds for #1529 and #1385 (2026-10-13)

Both were built on the Windows test PC through the same path as the Spark job (`cast_swap.plan` → `cast_swap.build`
→ `auf_swap.build_cast` → `special_builds.record_call`). The collection and the donor files came from the control
plane's API with GET requests only, and the Play-as target POSTs were not sent. Both builds are installed in the node
cache, `cache/mods/65b7187589166b26/<name>/` (`.gbox-mod.json` next to `007 - Agent Under Fire (USA).iso`).

| Mod | Call | Result |
|---|---|---|
| `auf_cast_wrestlers` (#1529) | `source=wrestlers assign=random seed=wrestlers prefer=smackdown2,nomercy`, all 57 slots | 57/57 built. 57 distinct WWF wrestlers (29 No Mercy, 28 SmackDown! 2; no name twice) on 372 (level, body) pairs; 37 levels, 416 LOD models, 0 level errors; 298 s |
| `auf_cast_sonic_random` (#1385) | `source=sa2 assign=random seed=sonic slots=campaign,bots` | 56/56 built. The 12 SA2 characters dealt at random over 40 campaign and 16 bot slots (each character once per round of 12); 370 pairs, 37 levels; the escort VIP left stock; 293 s |

Read back (`readback_*.json` in `D:\gBox\research\auf\evidence\`): every changed level was re-read from the mod's
image against the stock disc. The checks were the package walk, the restable sort, the build record's sha256, every
planned body's LOD models new and passing `decode_check`, every section textured, and the heads either stubbed (zero
area) or, when worn outside the plan, unchanged. Every other restable file was byte-identical, the texture records and
chunk length were unchanged, the mip chains were exact, and the levels outside the plan were stock. Both builds
passed with 0 problems: the wrestlers build had 37 levels and 416 models, the Sonic build 37 levels and 414 models
(the escort VIP stays stock).

Live (agent-owned Dolphin 2609a with its own User folder, the window off-screen and a private DSU pad; never the
operator's Dolphin):
* **Campaign.** "Trouble in Paradise" loads `maps/orc_1.ngc`. In its opening cut scene, wrestlers: the Orchid guard
  (`campaign:thug_orchid`) is Grand Master Sexay (SmackDown! 2, textured), and the passenger leaving the helicopter
  with the briefcase (`campaign:g8russia_body`) is Rikishi (No Mercy). In Sonic: the guard is Chaos 0, the passenger
  is Metal Sonic, and Bond on the ledge (`campaign:bond_combat`) is Rouge. All of them walk and gesture with the
  native animations, and no Bond or guard head is drawn over them. Gameplay in orc_1 ran without a crash.
* **Multiplayer.** In Combat Training with bots, wrestlers on Dungeon (`dm3`): the Rig Diver bot is Mae Young (No
  Mercy, flat skin tone), the Griffin bot is Cactus Jack and the Bloch bot is Debra. The match ran to 25 points and
  the results screen with no crash. Sonic on Cooling Station (`dm1`): the Jackal bot is Shadow and the Malprave bot
  is Dr. Eggman, both running and aiming.
* **Not checked yet.** Enemies in campaign gameplay (only the cut scenes were captured; the first mission's guards are
  behind the decryptor door), the other mission levels, hit registration on donors, and the escort maps.
* No Mercy donors look like flat skin tone in game, the same as their collection previews (section 6, known cosmetic
  limits). The SmackDown! 2 and SA2 donors are textured.

CLI (offline):

```
python -m gbox.auf_swap plan --slot cast --donor sd2_the_rock --donor player=nm_kane
python -m gbox.auf_swap level maps/dm1.ngc <library> out.ngc --slot player --donor djv_s100a
python -m gbox.auf_swap build <source.gcz|.iso> <library> <cache dir> --slot player --donor djv_s100a
```

## 6. Evidence (offline)

* `tests/test_auf_swap.py`: 25 synthetic tests and 2 owned-disc tests. Three of the synthetic tests cover the
  whole-cast path: the context slots and their groups, a `cast_swap` build of every context slot into one synthetic
  disc (`disc_level_keys` and its cache, per-slot report, marker `what` / `where_to_look`, `build_summary`), and a
  level that fails staying stock while its slots report it.
  * The synthetic tests build a skeleton, a `.gcm`, a whole level package (`.men` scripts, script dictionary,
    textures, shaders, BSP, restable) and a tiny GameCube image.
  * They cover the encoder round trip, palette limits, strips and winding, CMPR, in-place texture pages, the level
    rebuild (chunk, file and texture offsets), static and rigged donors, and disc layout (in place and moved).
  * They also cover a parallel end-to-end `build_mod`, the `characters op=use` path, slots, the cast plan, the
    entity-to-slot link and routing.
  * The owned-disc tests check the dm1/m6_1/alp2_2 cast against the snapshot and run the dm1 player slot with a
    donor.
  * Together with `tests/test_auf_ngc*.py`, 51 tests passed against the owned GCZ. The 337 character-routing tests
    still pass.
* **dm1, `player` ← `sd2_al_snow`** (SmackDown 2, rigged):
  * bond_combat_l has 782 triangles (budget 783) and bond_tux_l has 606. Each uses 16 palette records, against
    limits of 65 and 60.
  * bond_head_l becomes a stub.
  * The restable grows by 9,440 bytes in memory. The texture chunk does not grow at all, because the pages were
    written over Bond's own textures.
* **dm1, `player` ← `djv_s100a`** (Def Jam Vendetta GC, static T-pose):
  * The mesh goes from 2,052 to 782 triangles with 32 palette records. The restable grows by 18,592 bytes.
  * A reader export rendered in T-pose shows the textured wrestler on Bond's skeleton.
* **Full disc, `player` ← `sd2_al_snow`:**
  * All 37 levels with people were rebuilt and every one stayed in its own FST slot (0 moved).
  * The map files shrank by 3.56 MB in total. The image is 1,459,978,240 bytes, game id GW7E69, 351 files, read
    back by `GCDisc`.
  * The build took 1,020 s sequentially.
* **Full disc, whole cast** (`slot=cast seed=wwf`, 9 wrestlers):
  * The donors were 3 Def Jam GC (static), 3 SmackDown 2 and 3 No Mercy. Bond (`player=djv_s100a`) was fixed and
    the other donors were dealt.
  * All 45 bodies were replaced: 372 (level, body) pairs and 416 LOD files. Every one of the 377 head files in
    those levels became a stub.
  * Every level stayed in its slot, and the maps shrank by 6.08 MB in total.
  * The build took 330 s with 6 worker processes, after the do-while fix.
  * Reader exports of henchmen_vest_h (m6_1), g8us_body_h (alp2_2), zoe_body_l (dm1, female skeleton),
    superthug_body_m (uwb_2a), thug_orchid_l (dm1) and bond_graysuit_h (m6_1) render as textured wrestlers on
    those skeletons.
* **Known cosmetic limits:**
  * A donor's own head pose is kept. Some SmackDown 2 wrestlers look slightly up.
  * Decimation keeps each corner's UV, so heavily reduced faces smear a little.
  * The No Mercy entries in the collection are untextured skin tone, as they are in their own previews.

## 7. Live check (test PC, Dolphin) - to do

Run it on the agent test PC (JAYBUILTFINALE), on an agent-owned session only. Never use the operator's session.
Keep audio at 2%.

1. Build Bond → a Def Jam wrestler: `characters op=use character=djv_s100a game_id=65b7187589166b26 slot=player
   launch=false`. Record the mod name and the build report: every level's `replaced`, `stub_heads`, `textures`
   and sha256.
2. Launch the mod in Dolphin on JAYBUILTFINALE (`launch_game mod=<name>`).
   * **Multiplayer first**, where Bond's body is in view: start a dm1 match with bots and pick Bond (combat or
     tux) for a bot. Capture a frame with the wrestler running and animating. Pass if the level loads with no
     crash or hang, the model is drawn textured, the animations play (no T-pose), Bond's head is not drawn over
     the wrestler's, and shots register on the body (hit boxes are the slot's own).
   * **First mission**: m6_1 is the first mission's level by its cast (Bond in the grey suit, R, the shower girl,
     vest henchmen). Capture a cut-scene frame with Bond. In first-person play Bond's body is not on screen.
3. **Enemies**: `slot=enemies` with a wrestler, for example `sd2_the_rock` or `djv_s1xxa`. Load m6_1, then capture a
   frame of a henchman walking and dying (the death animations bind by bone hash). Repeat in one Alpine level for
   the `_h/_m/_l` LOD switch.
4. **Whole cast**: `slot=cast` with pairs `[{donor: …}]` covering a list of wrestlers. Load dm1 with 3 bots, and
   load one mission level.
5. Post the frames and the session/launch job ids on #1529, #1438 and #1362, and record the verified stage in
   the readiness ledger.

Possible failures and where to look:
* A crash or freeze on level load suggests a heap limit. The restable plus texture growth is reported per level;
  lower `BUDGET_FACTOR`.
* A missing or white texture suggests the shader/texture link. Check `report.textures` against `auf_ngc
  --export`.
* Exploding vertices suggest a palette or matrix-slot issue. Compare against `auf_gcm.decode_check`, which mirrors
  `R_DrawGeomSection`.
