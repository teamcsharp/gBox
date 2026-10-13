# 007 Agent Under Fire (GameCube) character writer

`gbox/auf_swap.py` (writer, slots, cast plan) and `gbox/auf_gcm.py` (the `.gcm` model encoder and the level
texture edits) put collection characters into 007 Agent Under Fire (USA, GW7E69, gBox game `65b7187589166b26`):
Bond, the mission enemies, the bosses, everyone else, and the multiplayer bots. One build can replace the whole
cast, which is what #1529 asks for ("replace every character with wrestlers from the WWE games ... randomly selects
characters from the list"). Tickets: #1438 (pick-whip program, stage 3 "writer for any entity slot"), #1362 (AUF
readiness, writer stage), #1529.

Status: built and checked offline (encoder round trip on every shipped character model, rebuilt levels read back
by the reader, disc image read back). **Not yet run in Dolphin**; the live check is in section 7.

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
  and the palette index is a u8.
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
| `all` | everyone |
| `model:<body>` | one body everywhere (e.g. `model:thug_orchid`, 21 levels) |
| `cast` | `pairs` = `[{target, donor}]`. A target is a body, `model:<body>` or a group. Narrower targets win over groups. Donors without a target are dealt over every body nobody named, using a seeded shuffle (`title` is the seed), so one body gets one donor across all levels and the same request builds the same disc. |

`op=collect` on the game lists these slots (`auf_swap.cast_slots`, kind `slot`, nothing extracted).
`characters op=coverage` lists the writer (`char_coverage.WRITERS`). The mod is named
`auf_<slot>_<plan hash>` and is built on the control plane, where the collection is.

"Replace every character with wrestlers" is one build: `slot=cast pairs=[{donor: sd2_the_rock}, {donor: nm_kane},
… every wrestler …]`.

CLI (offline):

```
python -m gbox.auf_swap plan --slot cast --donor sd2_the_rock --donor player=nm_kane
python -m gbox.auf_swap level maps/dm1.ngc <library> out.ngc --slot player --donor djv_s100a
python -m gbox.auf_swap build <source.gcz|.iso> <library> <cache dir> --slot player --donor djv_s100a
```

## 6. Evidence (offline)

* `tests/test_auf_swap.py`: 18 synthetic tests and 2 owned-disc tests. The synthetic tests build a skeleton, a
  `.gcm`, a whole level package (`.men` scripts, script dictionary, textures, shaders, BSP, restable) and a tiny
  GameCube image. They cover the encoder round trip, palette limits, strips and winding, CMPR, the level rebuild
  with chunk/file/texture offsets, a static donor, disc layout (in place and moved) and an end-to-end
  `build_mod`, plus slots, the cast plan and routing. The owned-disc tests cover the dm1/m6_1/alp2_2 cast against
  the snapshot and the dm1 player slot with a donor. With `tests/test_auf_ngc*.py` that is 46 passed against the
  owned GCZ.
* dm1, `player` ← `sd2_al_snow` (SmackDown 2, rigged): bond_combat_l 783 triangles (budget 783), bond_tux_l 606,
  palette 16 of 63/60, bond_head_l stubbed. The atlas went into `bond_graysuit_coat` (texture 30440a52, 256×128 →
  256×256). The level went from 6,682,688 to 6,610,400 bytes and took 21 s.
* dm1, `player` ← `djv_s100a` (Def Jam Vendetta GC, static): 2,052 → 782 triangles, palette 32. A reader export
  rendered in T-pose shows the textured wrestler on Bond's skeleton.

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
