# Enter the Matrix / The Matrix: Path of Neo: cast replacement (`gbox/etm_*.py`, `gbox/pon_inventory.py`)

Operator request (2026-10-13): "I want to be able to do cast / character replacement in Enter the Matrix / Path of
Neo." Branch `matrix-pipeline`.

## What the catalog owns (checked 2026-10-13)

| game id | catalog entry | what it is |
|---|---|---|
| `3f43b79a68a60b41` | Enter the Matrix (USA), windows_native, HyperSpin system "Microsoft XBOX" | **the PS2 disc** `collections/Sony Playstation 2/roms/USA/Enter the Matrix (USA).chd` (3,080,628,426 B, CHD v5 cdlz/cdzl/cdfl, one MODE1 track of 1,921,376 sectors, sha1 `0d5fb095...`): SLUS-20454, `SLUS_204.54` v2.00 |
| `b9ab2dd68f48dade` | The Matrix: Path of Neo (USA), windows_native, "Microsoft XBOX" | **the PS2 disc** `.../Matrix, The - Path of Neo (USA).chd` (2,646,887,296 B, CHD v5, 2,293,712 sectors, sha1 `217d206d...`): SLUS-21273, `SLUS_212.73` v1.00 |
| `d7d5279bbfde1b5d`, `a42804600e792cbc` | Enter the Matrix (USA) Disc 1 / 2, gamecube (favourite) | GCZ images; not read yet |

There is **no PC install** of either game: the two "windows_native" entries are HyperSpin attract entries that point
at PS2 CHDs (the same mis-filing as Vice City `5eacc9f11d9a5956`), and a search of C:, D:, E:, P:, V:, Y:, the Steam
libraries and the HyperSpin `PC Games` collection found none. So "start with the PC versions" became "start with the
PS2 discs those entries point at": a mod is a patched copy of the disc image (the loose-file / mirrored-install route
of a PC game does not apply). The CHDs are v5, which `gbox.psxdisc` (v4) can't open and no node has chdman for, so
`gbox/chd.py` reads them in pure Python (Huffman map, cdlz = raw LZMA1, cdzl = deflate, cdfl = FLAC, self refs).

## Use it

* `characters op=collect game_id=3f43b79a68a60b41`: the DEDICATED `etm` reader puts the 70-model roster
  (`etm_models.roster()`: Niobe x5 + phase, Ghost x5 + gi + phase, Agents Smith / Jackson / Johnson / Thompson and the
  three-agent model, Trinity, Morpheus, Neo, Seraph, Keymaker, Merovingian, the Twins, Vlad, Cujo, Abel, Cain, Bane,
  Axel, Ballard, Binary, Malachi, Corrupt, Vector, Wurm, Soren, Ice, Sparks, SWAT x7, police x2, security, vampires,
  workers, civilians ...) into the collection as rigged, textured GLBs with body roles. One model:
  `characters op=extract game_id=3f43b79a68a60b41 what="Agent Smith"`.
* `characters op=use character=<slug> game_id=3f43b79a68a60b41 slot=<slot>`: slots `player` (Niobe + Ghost, every
  costume), `niobe`, `ghost`, `agent_smith`, `agent_jackson`, `agent_johnson`, `agent_thompson`, `agents`, `trinity`,
  `morpheus`, `neo`, `seraph`, `keymaker`, `merovingian`, `twins`, `vlad`, `cujo`, `abel`, `cain`, `bane`, `axel`,
  `ballard`, `binary`, `malachi`, `corrupt`, `vector`, `wurm`, `soren`, `ice`, `sparks`, `swat`, `police`,
  `security`, `vampires`, `prisoners`, `workers`, `civilians` (also a display name or one model file, e.g.
  `Niobe_Costume03`). `op=match pairs=[{character, slot}, ...]` puts several donors in one image.
* Whole cast: `characters op=cast_swap target_game=3f43b79a68a60b41 source=<group|game>` (or the library menu
  "Replace entire cast with..."): 37 slots (the aggregate `player` is dropped; Niobe and Ghost are the lead slots),
  built in one image by `etm_swap.build_cast` (pairs strategy), a failing donor fails only its slot.
* CLI: `python -m gbox.etm_inventory <chd|iso>`, `python -m gbox.etm_models <chd|iso> <out_dir> [stems]`,
  `python -m gbox.etm_swap <chd|iso> <out.iso> slot=donor.glb ...` (roles from the donor's collection `meta.json`),
  `python -m gbox.pon_inventory <chd|iso>`.
* Launch: the mod is `cache/mods/3f43b79a68a60b41/<mod>/Enter the Matrix (USA).iso`. Run it in PCSX2. The catalog
  entry starts the original disc through RocketLauncher (attract entry, no mod argument), so `use()` reports the image
  path instead of launching.

## Formats (recovered from the owned discs and executables; no community documentation covers them)

Confidence: **verified** = every owned file parses to its last byte / the hash finds the names / the reader and the
game's own tables agree; **inferred** = consistent with all data but not confirmed by running the game.

* **WAD1.DFU** (`gbox/shiny_dfu.py`, both games, verified): `u32 count, u32 22313, u32 2067, u32 674, u32 2112,
  u32 flags`, then `count` x `{u32 name hash, u32 packed, u32 offset, u32 size}` sorted by hash; data at
  `(0x18 + 16 count + 0x7ff) & ~0x7ff` + offset, WAD1 and WAD1_B one address space; `packed != size` = zlib
  (zlib 1.1.4 in the ELF). Hash (ETM lookup `0x1d8390`): lower case, `/` = `\`, `h += a*c; a += b + ((c & 0x30)
  >> 4); b += 674 + (c & 15)` from `a, b = 22313, 2067`. Path of Neo (lookup `0x1f5860`) adds `c << 8 * (i & 3)` and
  hashes `ps2\` + every name without `common`. ETM: 9,690 rows (964 packed, 7 duplicate hashes); PoN: 3,080 rows,
  none packed, WAD1_B empty.
* **ETM name tables** (verified): `Actors\ActorHeadersV4.Bin` 404 x 0x60 (`u32 flags, char name[16]`, `+0x14 model
  index`, `+0x1c class`: 10 hero / 11 NPC / 12 story NPC, 13+ props, weapons, vehicles) and
  `Actors\ModelHeadersV4.Bin` 288 x `char path[80]` (`actors\<name>.dcn|dci|dc2`; 275 `.dcn` present).
* **ETM `.dcn` DC patch model** (`gbox/etm_models.py`; loader `0x167da0`; all 275 files parse, verified): 0x48 header
  (`u32 skeleton checksum`, name, joint / material / texture / config / mesh counts), mesh pointer slots, joint offsets
  + rest positions (89 joints, one shared skeleton `0x002e5ea3` for every human, weapon and prop; the actor init at
  `0x14e850` refuses a model whose checksum differs from the animation set's), meshes of three packet blocks:
  **A** bicubic Bezier quad patches (4 corner-UV header qw + 16 control points row-major), **B** cubic Bezier
  triangle patches (3 + 10: corners 0/3/6, edges in loop order, centre 9), **C** plain triangles (UV per vertex; the
  LOD configs and low-poly models such as `Morpheus.dcn` and `Cop_LP.dcn` are only C), each vertex `{x, y, z, joint *
  4}, {normal, n extra qw}` + `{joint * 4, w, joint * 4, w}` x n; textures (4/8-bit CLUT, linear, alpha 0..255; 16-bit
  A1B5G5R5 in Cop_LP), materials (`texture, -, environment texture`), configs (meshes shown + slot -> material
  map; config 0 = full model). Model space is left handed: +Y up, the character faces -Z, its right hand at -X,
  centimetres (Niobe 1.60 m, Smith 1.91 m). Bezier interpretation and control-point order: inferred from which control
  points neighbouring patches share (boundary points always, interior never) and from the previews; corner-UV order
  from the fewest UV conflicts at shared corners.
* **ETM skeleton** (verified on all humans): the joint tree is fixed (`etm_models.SHARED_PARENTS`: pelvis 0, thighs
  1/3, spine 2/6/7, knees 8/9, ankles 10/13, clavicles 11/14, neck 12, head 15, shoulders 17/19, elbows 22/23, wrists
  26/27 (twist joints between), hand joints 28/29 with 15 finger joints each, 29 face joints under the head); body
  roles `ROLE_JOINTS`, checked against the rest pose per model.
* **Animations** `animation\*.asb` (`_default.asb` 7.9 MB; the skeleton checksum lives there): not decoded; the
  writer keeps the game's skeleton and every animation.
* **Path of Neo** (`gbox/pon_inventory.py`, verified): `common\misc\ActorHeadersV11.Bin` 444 x 0x140 (three model
  paths: LOD 0/1/2, name at 0xc4); characters are **not** archive files: the 57 level packages
  `levels\<level>.lvl_3` (`u32 data start, u32 chunks, ...author[32], level[32]`, rows `{u32 id, u32 offset, u32 size,
  u32 type}` at 0x80) each carry their own copies as type-3 chunks `<model>.dcn_11` (124 distinct models: neo,
  neo_theone, agentsmith, smithrouge, trinity_m1, morpheus2..6, niobe, seraph, swat, police, the Merovingian's
  henchmen ...), a tagged successor of the ETM format (`_HEADER_`, `PATCHOBJ` sections). Type 9 = animation sets
  (CORE, SHOOTING, STANCE_*), 4 = level geometry, 10 = Louie UI scripts (`SHINYBIN`). Chunk ids come from a CRC
  (`0x1f51b0`, table `0x3f8088`) whose input names were not found.

## Reader (DEDICATED `etm`)

`extract_run`: the catalog CHD (or an ISO) -> identity check (exact SLUS_204.54 ELF sha256 `3b076e25...`, WAD sizes)
-> `WAD1.DFU:actors\<model>.dcn` -> config 0 tessellated (3 x 3 per quad patch, 9 triangles per triangle patch;
weights = the patch basis applied to the control points' weights, 4 strongest kept) -> mirrored to glTF (+Z front,
left = +X, metres) -> one GLB: 89 joints (rest-pose translations, inverse binds), one primitive and PNG per material,
body roles. Verified = parsed to the last byte, the shared skeleton checksum, roles found, 0.5-3 m tall.

## Writer (`gbox/etm_swap.py`)

1. The donor (collection GLB + `rig.roles`) is retargeted onto the slot's first model's skeleton
   (`sm64_swap.retarget` with `ROLE_JOINTS`: rigid per limb, one joint per vertex, into the game's A-pose); a chibi
   head (Sonic) is shrunk to ~1.3 x the cast's head height.
2. Encoded as a new .dcn with the original header (checksum, name), skeleton arrays and config count: one mesh of
   plain C triangles (render flags 64, the game's own winding), up to four 256 x 256 8-bit pages (`pack_atlases`,
   median-cut palette), one material per page, every config showing the mesh. It is read back with the reader
   (positions, joints, UVs per corner).
3. Budget per model file: packed (zlib 9) <= the original slot, file <= the original size (the game's model memory);
   otherwise fewer pages, then vertex clustering per joint (0.4 % .. 5 % of the height). Each costume / variant file
   of the slot is fitted on its own; a file that can't fit fails alone (slot `partial`).
4. Disc: the vanilla ISO is unpacked from the CHD once per game (`cache/modbase/<game>/`, ~3.4 min), copied into the
   mod folder, the entries' bytes and table rows rewritten in place, every replaced entry read back from the image.

## Tests

* `tests/test_chd.py` (5): synthetic CHD v5 (cdzl, cdlz, self and uncompressed hunks, Huffman map) round trip to the
  ISO, the RLE Huffman tree, cdfl FLAC frames, bounds / header errors; owned CHD identity (skips without the share).
* `tests/test_shiny_dfu.py` (6): both hashes against rows of the owned tables, packed and split entries, in-place
  replacement plans, table checks, an ISO9660 image.
* `tests/test_etm_models.py` (15): layout walk, 6 bounds errors, flat-patch tessellation and corner UVs, triangle
  patch basis, 4/8/16-bit textures, the rigged GLB with roles read by `sm64_swap.load_rig`, refused skeletons,
  roster + DEDICATED registration; owned: identity + tables, five cast models extract verified (Niobe, Ghost, Smith,
  Morpheus low poly, Cop_LP).
* `tests/test_etm_swap.py` (8): slots, fit -> encode -> read back (winding, configs, pages), slot budget, clustering,
  a synthetic disc build (only the slot's entries change, a no-roles donor fails alone, the source is untouched), the
  cast builder's per-slot report and mod record, WRITERS / cast_swap / characters_tool routing; owned: every slot's
  files exist and a donor fits Niobe's slot.
* `tests/test_pon_inventory.py` (3): package parse + bounds, levels confirmed by the hash, actor table; owned:
  identity, tables, b5_lobby's models.

## Live check (2026-10-13, this Windows PC, read-only on the catalog; no game launched)

* Both CHDs opened in place over the HyperSpin share; identities exact; inventories: ETM 9,690 archive rows, 404
  actors, 288 models; PoN 3,080 rows, 433 named actors, 57 level packages, 124 distinct character models.
* Reader: all 275 `.dcn` parse; Niobe (17,316 triangles at 3 x 3), Agent Smith (9,702), Morpheus (512, low poly)
  previews look like the characters (textures, faces upright, facing the camera).
* Writer, from the unpacked base ISO (3,934,978,048 B): donors fetched read-only from the live collection
  (`melee_ganondorf`, `sonic`) -> `etm_cast_live.iso` with slots niobe <- Ganondorf (7 files: 4,834 / 2,797 / 3,451 /
  6,326 / 1,303 triangles by slot size, packed 120-203 KB in 235-600 KB slots), ghost <- Sonic, agent_smith <-
  Ganondorf, swat <- Sonic: **4 slots, 22 model files (7 + 7 + 1 + 7), all built and read back** (Ghost / SWAT
  files 1,369 triangles at 4 pages, 115-116 KB packed; Agent Smith 1,942 after clustering to fit its 659 KB file).
  Re-opened as an ISO with the reader: identity still exact (ELF untouched), exactly 22 of 9,690 table rows changed
  (those files), 100 sampled untouched entries byte-identical, every replaced model parses with roles. Previews of the
  read-back models show Ganondorf on Niobe (1.45 m: his collection roles put chest / neck / head on one joint, so the
  fit uses that joint as the head) and Sonic on Ghost / SWAT (head shrunk, 2.0-2.2 m with the spikes).
* Not done (needs the operator): boot the image in PCSX2 and look at Niobe / Ghost in the first level (Post
  Office) and an Agent / SWAT fight: the in-game check of the plain-triangle mesh (the C block the game itself draws
  for its LOD and low-poly models) with the render flags 64, and of the memory budget.

## Path of Neo reader, geometry stage (`gbox/pon_models.py`, #1559)

* `.dcn_11` (verified on the owned disc): `u32 sections end - 0x40, u32, u32, u32 texture start` + 0x30 bytes, then
  tagged sections `char tag[8], u32 size, u32 version`: `_HEADER_`, `PATCHOBJ` (name char[16] at +0x14, part count
  at +0x58, part record offsets at +0x60, 0x40-byte records named `head` / `handL` / `handR` / `legs` / `Jacket_l`
  ...), `SKINMESH`, `A_DMAPAK`, `REFS____`; offsets are relative to 0x40.
* `A_DMAPAK` = PS2 DMA chains of `ref` tags whose VIF code is `UNPACK V4-32` of the same size. A vertex batch is a
  header qw `{n, 3, 0, GIF NLOOP | EOP}` + n x 2 qw: A = `s32 x, y, z` 16.16 fixed point (+Y up, feet at 0, the
  cast ~2,900 units tall) + `f32 matrix address * 4096`; B = `f32 u, v, weight0, weight1` whose low 16 bits are VU
  addresses: u -> output strip slot (12 + 3 k), v -> a second slot (0 = none), weights -> joint matrices. Output is
  one triangle strip of NLOOP vertices; triangles touching an unwritten slot or repeating a vertex are skipped.
* Survey (`python -m gbox.pon_models <chd> <out>`, all 57 levels): **233 distinct models, 0 failures**, 421,088
  triangles; 189 human-sized (Neo 3,525 triangles in 106 batches, Agent Smith LP 649 in 22). Flat-shaded renders of
  Neo, Trinity, Smith, Morpheus, Niobe, Seraph and the Merovingian read as complete A-pose figures (head, hands,
  feet); coat hems / lower legs show overlapping layers, consistent with patch-drawn parts not decoded yet.
* Tests: `tests/test_pon_models.py` (12 synthetic + 1 owned: the b1_lobby_dream cast decodes; Neo / Smith LP counts).
* Not yet: skeleton, joint indices, textures, collection registration and the writer (no PoN `op=use` yet).

## Open items

* In game (PCSX2): the replaced models' drawing, lighting and the per-file memory; record `runtime` with a capture.
* GameCube discs (favourite): open the GCZ, check whether the same WAD1.DFU / .dcn (big endian?) apply.
* Path of Neo: the skeleton (PATCHOBJ / SKINMESH part records, joint matrices), skin weights -> joint indices and
  the textures after the sections; then a DEDICATED reader with roles, and a writer that rewrites every level
  package carrying the model (in place per chunk), with the same cast slots as ETM.
* `.asb` animations / skeleton (would allow importing the game's poses into the GLB).
