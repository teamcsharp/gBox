# Metal Gear Solid: The Twin Snakes (GameCube): characters in and out

Operator request (2026-10-13): put the Sonic characters of the collection (Sonic Adventure 1 / 2 entries) in place of
Snake and the Genome soldiers, from a cast plan or with the pick whip, while the game runs.

Code: `gbox/ts_stage.py` (stage.dat), `gbox/ts_kms.py` (models), `gbox/ts_tex.py` (texture sets),
`gbox/twin_snakes.py` (the reader, characters.DEDICATED `twin_snakes`), `gbox/twin_snakes_swap.py` (the writer,
`characters op=use / live_use`, cast_swap pairs builder), `gbox/twin_snakes_live.py` (the `twin_snakes_live`
session tool). Tests: `tests/test_twin_snakes.py` (synthetic; `TTS_ISO=<disc 1 image>` adds the owned-disc check).

Catalog: `ba32927ecc104b9a`, `b87996662aa2a8f7` (the two ISOs, 1.46 GB each), `79965f951e479d2b` (USA Disc 1, GCZ),
`bf3675da8955e248` (Disc 2, GCZ). Which disc an image is comes from its header byte 6 (0 = disc 1, 1 = disc 2).

## 1. The disc

Both discs are `GGSEA4` ("METAL GEAR SOLID THE TWIN SNAKES"), 1 459 978 240 bytes, 1647 / 1657 FST files.

| File | Size (disc 1) | What |
|---|---|---|
| `stage.dat` | 198.7 MB | every stage: models, textures, motions, scripts, collision (below) |
| `demo.dat` | 494 MB | cut-scene streams (zlib pages, same container family) |
| `shared/face.dat` | 7 MB | codec faces (`f00a`, `f01a` ... directory like stage.dat) |
| `shared/codec.dat`, `vox.dat`, `movie.dat` | 12 / 97 / 95 MB | codec, voice, FMV |
| `shared/mgso.rel` | 5.7 MB | **the game**: a REL module (main.dol is the SDK + loader). Strings: `C:\MGS\mgs2\mgs2x\MGS2GCN\mgso.plf`, `gcn_dgd.c`, `GCN_prim2.c`, `libgv_cnf.c` |
| `audio/*`, `shared/audio/*` | | sound banks (`.spd/.spt`) and streams |
| `shared/stage/preview/data.cnf` | 175 B | a stage file list: `stage.hzx`, `cache.dar`, `scenerio.gcx`, `human_out_cold.tri`, `human_out_cold.kmx`, `motion.mar` ... |

The engine is Konami's **MGS2 engine** ported to the GameCube (the debug strings say `KMS-MODEL`, `CV2-MODEL`,
`data.cnf`; file kinds and the 24-bit name hash are MGS2's), not a Silicon Knights engine.

### stage.dat

* Header: `u32 ?, u32 0x00010001, u16 count, u16 0xcccc, u32 ?`, then `count` x `{char name[8], u32 sector}`
  (sector = 0x800 bytes inside stage.dat). Disc 1: 114 stages, disc 2: 117. Names: `r_cmmn` (common resident),
  `r_sna` (Snake's resident set), `r_tux` (tuxedo playthrough), `area01a` .. `area27b` (gameplay areas; disc 2 adds
  `area17*`, `area18*`, `area21a`, `area22*`, `area24*`, `area27*`), `mrl_*` / `mrd_*` / `nja_*` / `otc_dmo` (scene
  sets), `demo*`, `r_demo*`, `r_dmo*` (cut-scene stages), `boss`, `ending`, `init`, `n_title`, `disk1`, `disk2`.
* A stage: `u32 rows`, then rows `{u32 key, u32 value}` padded to 0x800, then the packed pages:
  `{0x7f000000|page, uncompressed size} {0x7e000000|packed size, data offset} <file rows> {0x7f000000, size}`.
  A page is one zlib stream (`78 9c`, level 6: the stock bytes recompress identically), padded to 0x800.
  A file row is `{type << 24 | strcode(name), offset in the inflated page}`; files are 0x20-aligned.
* The type byte is `extension letter - 'a'` (mgso.rel 0x806c0470 builds lookup keys as `hash | (ext - 0x61) << 24`):
  `0x02` c = `.cv2`, `0x05` f = font stub, `0x06` g = `.gcx` script (`scenerio`), `0x07` h = `.hzx` collision,
  `0x0a` k = **`.kms` model**, `0x0c` m = `.mar` motion archive ("aRAM"), `0x0e` o, `0x11` r, `0x12` s, `0x13` t =
  **`.tri` texture set**, `0x15` v. Loaders are registered by letter at 0x806c0524 (`k` -> 0x806b66b4, `t` ->
  0x806ae300, `c` -> 0x806b6700 ...).
* `strcode(name)`: `h = ((h >> 19) | (h << 5)) & 0xffffff; h = (h + c) & 0xffffff` per byte. `snake_def` = 0xf7a622,
  `sna_def` = 0x413aa8, `out_cold` = 0x26e012.
* Stages are packed back to back: at level 6 every stage has 0 bytes of slack; recompressing a whole stage at level
  9 frees 10-18 KB. A writer keeps every stage in its own sector span (`ts_stage.rebuild_stage`, `StageTooBig`), so
  no other stage, file or FST entry moves.

### .kms model (type 0x0a)

Big-endian. "G" = the mesh-group header, whose file offset is at +0x5c (0x5a0 on characters: 0x60 + 21 x 0x40);
every other offset is G-relative (the loader 0x806b6be8 / 0x806b6860 turns them into pointers).

* Header 0x60: `u32 flags` (0 characters, 0x01b253a3 props), `u32 bones`, `u32 meshes`, `u32 texture set strcode`,
  `u32 own strcode`, `u32 3`, `f32 min[3] max[3]`, `u16 envelopes`, `u16 meshes`, `u16 1`, `u16 positions`,
  `u16 normals`, `u16 uvs`, `u16 bones`, `u16 0xfffe`, G offsets of envelopes / positions / normals / uvs, G.
* Bones (0x40 each from 0x60; props have none): `u32 flags, i32 parent, f32 local[3], f32 world[3]` (bind pose,
  model space, mm), `f32 min[4] max[4]`. **Every character uses the same 21-bone MGS2 skeleton**: parents
  `-1,0,1,2,3,4,5,2,7,8,9,2,11,0,13,14,15,0,17,18,19` = hip, spine, chest, r shoulder / upper / fore / hand,
  l shoulder / upper / fore / hand, neck, head, r thigh / shin / foot / toe, l thigh / shin / foot / toe. The model
  faces +Z, its left is +X, Y up (the library frame), arms hanging (not a T pose). Cut-scene models (`*_dmo`) have
  53 bones (fingers, face) and are not collected.
* G (0x14): `s16 bounding sphere x, y, z, radius` (Snake 0, -172, 21, 926: the actor shadow / light code reads it), `u16 meshes, u16 parts`, `u32 LOD sub-groups` (0 on characters), `u32 mesh records` (0x14).
* Mesh record (0x48): `u32 0, 0, f32 min[3] max[3]` (relative to the mesh's bind position), `local[3], world[3]`,
  `u16 parts, i16 parent`, `u32 0x00abcdef` (props: a strcode), `u16 positions used, u16 ?`, `u32 parts`. Each
  mesh has its own matrix (the model object allocates 0x144 bytes per mesh, 0x806a77bc); mesh i < 21 is bone i,
  later meshes (hair, bandana knot, gear, eyes) ride their parent mesh.
* Part (0x24): `u32 flags` (0x1f8 bump-mapped), `u32 texture[3]` strcodes (bump, colour, specular; with only the
  first set it is the colour), `u16 strips, u16 positions used, u32 uv list, u32 uv list 2 (0 = same), u32 layers
  (3), u32 strips`.
* Strip (0x20): `u32 stream[7], u16 n, u16 m`. A GX triangle strip (0x98) drawn by 0x806a2a6c: vertex k sends
  matrix `envelope s5[s6[k]]` (m <= 10, the GX matrix palette), position `s0[k]`, normal `s2[k]` (bump mode adds
  binormal `s3[k]`, tangent `s4[k]`), colour `s0[k]` when the object has colours, and two texture coordinates
  `uvlist[s1[k]]`, `uvlist2[s1[k]]`. Empty streams default: s1, s2 = s0, s3 = s2, s4 = s3. Front faces are
  clockwise in strip order.
* Arrays: positions `s16 x3` (mm, model space, bind pose), normals `s8 x3` (64 = 1.0; N, B, T consecutive),
  uvs `s16 x2` (4096 = 1.0, origin top left), envelopes 8 bytes `{u16 w0, u16 w1 (Q15), u8 bone[4] (0xff none)}`:
  the last listed bone gets `1 - w0 - w1`; bone numbers are mesh numbers.

### .tri texture set (type 0x13)

`+0x10 u32 count, +0x14 flags, +0x18 offset of an embedded standard TPL` (magic 0x0020AF30), then 0x80-byte entries
(`+0x10 strcode`, `+0x1c TPL image index`, the rest is GX register state the loader fills: 0x806ae21c / 0x806aeb94).
Images are C4 / C8 with IA8 palettes (bump and specular masks), CMPR (colour), RGBA8 (small gear / eyes) at their own
odd sizes (Snake's body atlas `92b726`: CMPR 439 x 350; his bump map `0d46e2` C8, specular `f02eae` C4). Lookup is
by strcode, the model's own set first, then every loaded set (0x806ae880). `0x9576ef` is a shared 2 x 2 null.

### The cast (both discs; `twin_snakes.CAST`, names verified by strcode)

| Key | Who | Stage read (disc 1 / 2) | Low-detail twin |
|---|---|---|---|
| `snake_def` | Solid Snake (21 bones, 23 meshes, 3028 tris, 130 KB) | r_sna / r_sna (also r_tux) | `55ab65` (unnamed, 21 meshes, 48 KB, r_sna + cut scenes) |
| `out_cold` | Genome Soldier, arctic (2058 tris) | area01a / area01a (+ area02a, 08a/b, 23a) | `out_cold_sh` |
| `out_cold2` | Genome Soldier, arctic hood | area02a / area08a | `out_cold2_sh` |
| `in_door` | Genome Soldier, indoor (1878 tris) | area04a / area17a (+ 06a, 07a, 10a, 16a; disc 2 17a, 18b, 21a, 23b, 24a) | `in_door_sh` |
| `in_gus` | Genome Soldier, gas mask | area09a / - | `in_gus_sh` (demo only) |
| `in_gus_blue_def` | gas mask, blue | demo09a / area17e | |
| `hev_grd` | Genome heavy guard (2032 tris) | area04a / area21a | `hev_grd_sh` |
| `mrl_def`, `mrl_dis_def` | Meryl, Meryl in a soldier's uniform | mrl_def, mrl_dis | `mrl_dis_sh` |
| `otc_def` | Otacon | area11a / area27a | |
| `rev_coat_def` | Revolver Ocelot | area06b | |
| `psy_def` | Psycho Mantis | area13a | |
| `snp_def`, `snp_cold_def` | Sniper Wolf | area15a, area20a | |
| `vul_def` | Vulcan Raven | area08a | |
| `liq_coat_def`, `liq_def` | Liquid Snake | disc 2 only: area24a, area27b | |
| `joh_def` | Johnny Sasaki (no uniform) | jhJ_dmo | |
| `#65729f` | Cyborg Ninja (name not recovered) | nja_def | |

Other first-person / item models (`543505` Snake's first-person arms, set `b13aa8`) and the per-soldier props
(eyes `out_cold_blink_*`, slings `*_sling`, the bandana tails `sna_mugen_bdn*` / `26523a` / `265239`) are separate
`.kms` props with no bone table.

### Reproducing the code analysis

The game code is `shared/mgso.rel`; `gcdisc.dol_rel_to_elf(main.dol, mgso.rel)` links the REL at 0x80300000 against
main.dol (relocations applied, sections laid out as OSLink does) and, with `gekko=True`, rewrites the paired-single
instructions so stock Ghidra PowerPC decodes every function (`psq_l` -> `lfs` ...). Then
`analyzeHeadless <proj> tts -import tts.elf -postScript DecompileAll.java out.c reg:r13:80285dc0 reg:r2:802864a0`
(SDA bases from main.dol's `__init_registers`). Functions used above: loaders 0x806b66b4 / 0x806b6be8 / 0x806b6860
(kms), 0x806ae21c / 0x806aeb94 (tri), texture lookup 0x806ae880, model object 0x806a77bc / 0x806a7860, draw loop
0x806a2a6c, resource key 0x806c0470, loader registration 0x806c0524, Snake's actor init 0x80364d78 (model
`snake_def` through 0x8033a72c), the soldier actor's model switch near 0x803df590 (`out_cold`, `in_door`,
`in_gus`, `out_cold2`, `in_gus_blue_def` by strcode).

## 2. Reader (`characters op=collect`, DEDICATED `twin_snakes`, reader v1)

Per roster entry: the model from its stage, every part's colour texture from the stage's sets (own set first), the
skeleton (21 bones + one joint per extra mesh) with up to three weights per vertex, metres, +Y up, facing +Z,
left +X, 18 body roles (hip, chest, neck, head, clavicles, arms, legs). Meta `tts_reader`, `tts_model`,
`tts_stage`, `tts_disc`, `tts_slot` (`player` or `model:<key>`); the roster is filtered to the disc being read
(`characters.dedicated_entries`). Offline: `python -m gbox.twin_snakes <iso> <out dir> [key ...]` writes GLBs and
previews; all 17 disc-1 entries and the disc-2-only Liquids decode with textures (render sheet checked by eye on
2026-10-13). Known: `liq_coat_def`'s coat-tail meshes render without their colour (its second texture layer).

## 3. Writer (`characters op=use`, `gbox.twin_snakes_swap`)

Slots: `player` (snake_def + 55ab65) | `model:<key>` | `enemies` / `soldiers` (out_cold, out_cold2, in_door,
in_gus, in_gus_blue_def, hev_grd + their `_sh` twins) | `bosses` | `npcs` | `all` | `cast` (`pairs` [{target,
donor}], named targets first, the rest dealt in CAST order). `cast_slots()` feeds the cast menu; cast_swap uses
the pairs path (`build_cast`: one stage.dat rebuild for the whole plan).

Per slot and model:

1. **Retarget**: `sm64_swap.load_rig` + `sm64_swap.retarget` (the shared rigid retarget) onto the model's own bind
   skeleton: target = bone world positions, ground and head height from the stock model, `JMAP` role -> bone
   (hip 0, chest 2, head 12, arms 4-6 / 8-10, legs 13-15 / 17-19). The Retarget editor profile (`rig.scale`) applies;
   fit events: scale / retarget / proportion (from the shared retarget), weights, decimate, encode, write.
2. **Atlas**: `auf_swap.donor_materials` + `build_pages` pack the donor's textures into one image the size of the
   model's body colour image; `atlas_uvs` maps every corner.
3. **Encode** (`ts_kms.encode`): header, bones, mesh records and each bone mesh's first part record (flags, texture
   layer) are kept; one part per bone mesh, faces stripified (`auf_gcm.stripify`, split so a strip uses <= 10 bones),
   single-bone envelopes, deduplicated arrays, bounding sphere recomputed; the extra meshes (gear, hair) draw nothing.
   Budget: the stock model's byte size; `auf_swap.decimate` (quadric collapse) until it fits.
4. **Stages**: every gameplay stage holding the model (cut-scene stages `demo*`, `r_demo*`, `r_dmo*`, `r_dmT*`,
   `r_brif`, `r_open` are left stock) gets the model, its twin, the texture set with the donor atlas written over
   the body colour image in its own format and size (the bump image flattened to one palette entry, the specular
   mask to its darkest one; 2 x 2 shared stand-ins never touched), and hides (part counts 0) the other models that
   draw with a changed image or belong to the replaced character's texture set (bandana tails, eyes, slings).
5. **Fit**: each stage is recompressed (level 9) into its own sector span; if one does not fit, every budget shrinks
   by 0.85 and the build retries (6 tries).
6. **Disc**: stage.dat rewritten in place (same size, same offset) in a copy of the image (`filemods.build_image`),
   read back; marker `.gbox-mod.json` with `writer`, `disc`, `cast`, per-stage report. Mod name
   `tts_<slot>_<plan digest>`.

Offline evidence (2026-10-13, owned disc 1, donors made with gBox's own SA2 reader from the operator's SA2 disc):

* Sonic (`sonic`, SA2) as Snake: `snake_def` 1369 tris / 62 KB and `55ab65` 759 tris in r_sna and r_tux,
  6 / 4 Snake accessories hidden; read back from the rebuilt stage.dat and rendered (front and back) on Snake's
  skeleton with the Sonic atlas. Full disc image build: 62 s.
* Shadow (`sa2_shadow`) as `enemies`: 12 gameplay stages rebuilt (area01a, 02a, 04a-10a, 16a, 08b, 23a), all within
  their spans at budget x1.0; hidden props = the soldiers' eyes and slings; `in_gus_blue_def` reported failed
  (only in a cut-scene stage on disc 1).
* Cyborg Ninja (TTS's own) as Snake: built and read back.
* Not verified in Dolphin: no game was started from this work.

## 4. Pick whip and on the fly

* `characters op=live_use` (the desktop pick whip's "Try live replacement (OoT NPCs, Twin Snakes)", which now also
  sends the identified `target` words) and `op=use` with `x, y` and no slot resolve the slot with
  `twin_snakes_swap.resolve_slot`: words first (Snake / player -> `player`; a cast name -> `model:<key>`; soldier /
  guard / genome / gas mask -> the loaded soldier model, several -> `enemies`), then the models the running stage
  has in RAM (`twin_snakes_live op=loaded`: a paused MEM1 scan for relocated `.kms` headers with a cast strcode),
  then the point (`pick_slot`: the camera follows Snake, so an unidentified pick in the middle of the picture is
  Snake; elsewhere the loaded soldiers or the only other cast member). `slot_for_model` maps any model strcode /
  name (twins included) to its slot.
* `live_use` then: builds the mod (control plane), launches it on the session's node through the server's
  **session swap** (save state -> mod on the same worker -> load state -> old copy closed: the moment is kept), and
  writes the swap into the running stage with `twin_snakes_live op=apply`: the new model relocated over each loaded
  copy (pointers made absolute like the engine's loader; texture-entry pointers kept from the loaded copy; same
  mesh-group header and records, never more parts per mesh), the changed texels into the loaded `.tri` set (only
  where the set's TPL headers match), the hidden props' part counts set to 0. All writes happen paused, are read
  back, and everything is restored if any step fails. Without the live write the new body shows from the next area
  load (stages load from the modded disc).
* `op=use launch=true session_id=...` (cast menu, chat) builds and launches through the same session swap.

## 5. Live check (operator, on the Windows PC)

1. Make the Sonic donors exist on the control plane: `characters op=collect` on the SA2 (or SA1) game.
2. Collect the Twin Snakes cast once (optional, for previews): `characters op=collect game_id=79965f951e479d2b`.
3. Start Twin Snakes disc 1 in gBox, play to the Dock (area01a) with a soldier in view.
4. Alt-drag Sonic's card onto Snake -> **Try live replacement**. Expected: toast "Sonic replaces Solid Snake in the
   running game now ..."; Snake drawn as Sonic, the bandana tails gone. Go through the elevator door: still Sonic.
5. Alt-drag Shadow onto a soldier -> **Identify selected character** (should say soldier) -> **Try live
   replacement**. Expected: every arctic soldier in the area as Shadow (eyes and sling props hidden).
6. Whole cast: right-click the game -> Replace entire cast with... -> Sonic group -> plan -> Build.
7. Report back: the frame, `characters` job result (`live` block: written addresses or the error), any Dolphin
   crash. Things to look at: Snake / soldiers animating with their own motions (arms, legs, head), texture
   correctness, missing parts at joints (rigid skin), the first-person view (Snake's FP arms are a separate model
   and stay Snake's), cut scenes (unchanged by design).

## 6. Limits / not done

* Rigid single-bone skinning (as every gBox rigid retarget): joints can show seams in extreme poses.
* Cut-scene stages and `demo.dat` are not rewritten (cut scenes show the original cast); first-person arms stay.
* The live write is unverified on a running game: the loaded-copy layout comes from the decompiled loader / draw
  loop, not from a RAM dump; Dolphin may keep a texture in its cache until the texels' hash is re-checked.
* The 53-bone cut-scene models, `.cv2` models and `face.dat` codec faces are not read.
* Disc 2 builds use the same code; checked offline only through the reader (Liquid, disc-2 soldiers).
