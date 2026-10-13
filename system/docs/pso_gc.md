# Phantasy Star Online Episode I & II (Plus), GameCube: reader and writer

Inbox: #1545 (models, `90b38d788ba840f2`) and #1546 (observation, `0a514c2431d04990`).

| | |
|---|---|
| Catalog | `436e0bb84d5337d1` "Phantasy Star Online Episode I & II Plus (USA)" (HyperSpin GCZ). The same reader matches `6b55435e3c565370` (Ep I&II USA), `7a3692dc0cbc9b82` (Plus) and `5b5792e27be59f59` (Return To Ragol). |
| Build | GPOE8P disc 0 rev 2 "PHANTASY STAR ONLINE EPISODE I&II". GCZ: 1,178,288,344 bytes, block 16384, image 1,459,978,240 bytes. The executable is `PsoV3.dol`. `main.dol` is only the AppSwitcher. |
| Reader | `gbox/pso_gc.py`. `characters.DEDICATED` row `pso_gc`, `READER_VERSION` 1, recorded in meta as `pso_gc_reader`. |
| Writer | `gbox/pso_gc_swap.py`. `characters op=use` slots `class:<humar..fomar>` (`player` = HUmar), `enemy:<key>`. |
| Tests | `tests/test_pso_gc_reader.py`, `tests/test_pso_gc_swap.py` (synthetic data), and `tests/test_pso_gc.py` (disc checks, skipped without the image). |
| Evidence | `D:\gBox\research\pso_gc\evidence\` (offline renders, see the end of this doc). |

Fingerprint: `assimilate op=fingerprint` names the engine as Sega Ninja SDK (1.00) with CRI AFS. The nearest titles
are `pso_gc` and `pso_dc`, and it suggests starting from `gbox.pso_player`. The knowledge-base entry `pso_gc` now
also lists the GSL archives and the DOL texture tables.

## Formats (all offsets from the owned disc)

### Disc

The disc uses the GameCube FST and holds 3510 files. `GCDisc` now reads `.gcz` in place (`gbox/gcdisc.py`).

The image is full: the last file ends on byte 1,459,978,240. The only room is unused junk-filled stretches between
files, the largest being 46 MB after `CUBE_OPENING.adx`. When a grown file does not fit after the last file,
`gbox.romexport.gc_put_file` now places it in the first such gap (`gc_find_gap`).

### GSL area archives

Files are named `gsl_<area>.gsl`; 51 are on the disc. Each is a table of 0x30-byte entries:

- `char name[0x20]`
- `u32 BE offset` in 0x800 units
- `u32 BE size`
- 8 zero bytes

The files follow, 0x800-aligned. `gsl_build` reproduces all 51 archives byte for byte.

Enemy packs live only here; the loose `bm_ene_*` copies are a few leftovers. The area that loads a pack identifies the
enemy. For example `gsl_forest01` carries `bm_ene_re8_b_beast.bml`, which is the Booma family (on the Dreamcast,
gbox.pso_enemy guessed `BM1_SHARK` for Booma; on the GC, `bm1_shark` is loaded only in the caves).

### BML packs

The layout is the Dreamcast one (`pso_player.bml_files`) with big-endian header fields. Two details:

- The header is `0x40 + 0x40 * n`, rounded up to 0x800.
- Entries are aligned to 0x20 in enemy packs and to 0x800 in the player packs `pl<X>nj.bml` (`bml_align` detects which).

298 of the 299 loose BMLs rebuild byte-identically. The exception, `fe_obj_hira_kage.bml`, is a little-endian DC
leftover.

### Ninja models (NJTL / POF0 / NJCM / POF0)

Chunk sizes (`NJCM`, `NJTL`, `POF0`) stay little-endian. The payload is big-endian, with two swap units:

| data | swapped as | read as |
|---|---|---|
| node (0x34) and model (0x18) structs | u32 | |
| vertex chunks | u32 | head word `size << 16 \| flags << 8 \| type`; second word `count << 16 \| base`; floats; NF32 weight word |
| polygon chunks (tiny, material, strip) | u16 | |

The old `ninja.NJ` read `base, count` as two u16s. That is correct on the Dreamcast but scrambled every GC vertex
chunk (HUmar went from 734 bogus to 269 real vertices). It now reads one u32 word, which gives the same values on the
Dreamcast. `cnk_model_lists` writes the word the same way.

### Textures

A GVR is an optional GBIX followed by a GVRT chunk: `u32 LE size`, then byte 0x0A = `palette format << 4 | data
flags`, byte 0x0B = GX format, then `u16 BE width, height`, then the GX texel blocks. Decoding goes through
`gbox.melee_models.decode_texture`.

A GVM is `GVMH`, a `u32 LE` header size, `u16 BE` flags and count, the entries, then the GVRs in order.

The player banks `pl<X>tex.afs` are AFS archives (little-endian table) of GBIX+GVRT entries. HUmar has 137 entries;
HUcast has 286 (CMPR 128/64/32 and RGB5A3).

### Texture names and lists in PsoV3.dol

These were found from the strings, not from fixed addresses (`pso_gc.class_tables`):

- For each class, a 16-byte record `{u32 id, u32 count, char *"PL<X>TEX.AFS", char **names}` names every AFS entry.
  For example `pxtAb_01z_w_huku1` is the HUmar body, costume 1, part 1. Other parts: `f` face, `h` hair, `t` hands
  (te), `Zc` section-ID core.
- For each class, a 0x2C-byte descriptor holds:
  - `u32 x4` counts (e.g. 0x12 costumes, 5 faces, 10 hair styles)
  - pointers to the hair file, cap file and head file arrays
  - `char *body` (`pl<X>bdy00.nj`)
  - pointers to the hair, head and body NJS_TEXLIST
- The NJS_TEXLISTs use the default variant names. The reader's textures are exactly the game's own defaults.

HUmar's body texlist, for example, is `[pxtZc_01g_t_core, pxtAb_01z_w_huku1, huku2, huku3, pxtAt_01z_w_te1]` for
texture ids 0..4. Hair style i's list is shared by `pl<X>hai<i>.nj` and `pl<X>cap<i>.nj`.

## Player classes (12)

The letters A..L are HUmar, HUnewearl, HUcast, RAmar, RAcast, RAcaseal, FOmarl, FOnewm, FOnewearl, HUcaseal,
RAmarl and FOmar. M..Z are placeholder slots.

- **Skeleton.** Every `pl<X>bdy00.nj` has the Dreamcast 64-node tree (`pso_player.PLAYER_PARENTS`, checked for all 12
  classes) with weighted NF32 vertices (types 0x29 and 0x2C).
- **Head, hair and cap.** These are separate one-node models drawn in the frame of node 59, the hidden child of the
  head mesh node 56. They are weighted to node 56. Androids have five head models; humans have one head plus ten hair
  and cap styles.
- **18 body roles** (`pso_gc.class_roles`, checked per class by `pso_player.check_roles` plus tree checks):

  | role | node | role | node | role | node |
  |---|---|---|---|---|---|
  | hip | 2 | chest | 25 | neck | 55 |
  | head | 56 | l_clav | 26 | r_clav | 39 |
  | l_upper | 28 | l_fore | 29 | l_hand | 34 |
  | r_upper | 41 | r_fore | 42 | r_hand | 47 |
  | l_thigh | 4 | l_shin | 5 | l_foot | 8 |
  | r_thigh | 13 | r_shin | 14 | r_foot | 17 |

- **Extraction.** Each class is extracted as body + head 0 + hair 0 (+ cap 0) with the default costume, face and hair
  textures. There are no missing texture names in any class.

## Enemies (50 bodies)

`pso_gc.ENEMIES` maps a key to a pack, a body entry and a name, for example `booma`, `gobooma`, `gigobooma`,
`rag_rappy`, `savage_wolf`, `evil_shark`, `chaos_sorcerer`, `merillia` and `ill_gill`. The source data has these
properties:

- Each body sits on its own tree, so its `.njm` motions in the same pack still drive it.
- A body without its own GVM or NJTL (Barbarous Wolf) uses the textures and texture list of a pack mate.

Roles come from one of two sources:

- **Fixed map.** The Booma family uses the Dreamcast Booma map, checked against the GC tree.
- **Inferred map.** All other enemies use `pso_enemy.infer_roles`, with duplicate nodes removed. Non-humanoid enemies
  report fewer roles; the rest are left explicitly absent.

Names marked "(probable)" in the table are inferred from pack and area names and have not been confirmed in game.

## Writer (`gbox.pso_gc_swap`)

Both slots go through `ninja_swap.fit`, which does the following and reports every stage to `gbox.fit_events`:

1. Retarget the donor onto the native bind pose with the role map (`sm64_swap.retarget`).
2. Decimate in Blender to the PSO budgets of 900, 750, 600, 480 and 400 triangles.
3. Cut the result into rigid per-node geometry.
4. Pack the textures into one 256 atlas.

**`class:<name>`** writes these files:

- `pl<X>bdy00.nj`, both the loose file and the copy inside `pl<X>nj.bml`. Every node keeps its original weighted
  vertex chunks (the engine needs them; this is the SA2 rule). The donor's rigid vertices come from a free,
  16-aligned cache slot, with new strips on texture 1.
- Every head, hair and cap model, loose and in the BML, replaced by an invisible speck.
- The atlas, written into all textures of `pl<X>tex.afs` in each texture's own size and GX format, so any costume
  shows the donor.

On the Dreamcast the same layout failed on the 11-sector file limit. On the GC, files can move.

**`enemy:<key>`** rebuilds the body in its pack (PRS, BE header) and the GVM with the atlas. The pack is then written
into every GSL archive that carries it, and into the loose copy if one exists.

**Safety:**

- Every texture keeps its GVRT header (format, size, flags) and exactly its texel bytes. Mipmapped and palette textures
  are left as they are.
- `validate()` re-reads every written GSL, BML, NJ, GVM and AFS with the reader before the disc is built.
- `build_mod` writes a disc copy (`filemods.build_image`, GCZ to ISO) under `cache/mods/<game>/psogc_<slug>_as_<slot>`.
  The source image is never written.

**Offline proof (2026-10-13):**

| build | result |
|---|---|
| Sonic as HUmar, then as HUcast | 900 triangles, every texture of the bank rewritten (137 of 137 for HUmar). The full `build_mod` placed `plCbdy00.nj` in the gap, and the reader decoded the class back from the new ISO. |
| Knuckles as Booma | 899 triangles. `gsl_forest01.gsl` and `gsl_forest02.gsl` were rewritten and read back from the built ISO. |

**Not verified in game.** This PC is JAYBUILTFINALE, the operator's play PC, and the operator's Dolphin was running.
The operator's rule (2026-10-13) limits agent test sessions to i9-NUC and the Spark. So no Dolphin boot of a built mod
was made. Next step: boot `psogc_<slug>_as_humar` on i9-NUC (offline mode, any HUmar save), and Forest 1 for
`enemy:booma`. Check that the body draws (the weighted-chunk rule) and that the GSL / gap placement loads.

## Usage

```
python -m gbox.pso_gc <image.gcz|.iso> <out> [A..L | enemy key ...] --preview
python -m gbox.pso_gc_swap <image> <collection entry dir> <out> --slot class:humar|enemy:booma
characters op=collect game_id=436e0bb84d5337d1
characters op=use character=<slug> game_id=436e0bb84d5337d1 slot=class:hucast|enemy:booma
```

## Evidence (`D:\gBox\research\pso_gc\evidence\`)

All images are offline renders from `characters.render_preview`. None is an in-game frame.

| file | shows |
|---|---|
| `player_classes_12.png` | All 12 classes as the reader exports them: body, head and hair, default textures. |
| `enemies_50.png` | All 50 enemy bodies, textured. |
| `humar_before_after_sonic.png` | Stock HUmar next to Sonic written as HUmar, decoded back from the written files. |
| `booma_before_after_knuckles.png` | Stock Booma next to Knuckles written as Booma, decoded back from the new GSLs. |
| `hucast_after_sonic_read_from_built_disc.png` | Read from the ISO that `build_mod` produced. |
| `booma_after_knuckles_read_from_built_disc.png` | Read from the ISO that `build_mod` produced. |
