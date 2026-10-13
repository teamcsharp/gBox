# Soul Calibur II (GameCube): fighters in and out, and the random Sonic vs Mario build

Operator request (2026-10-13): "the same package as request #1652, for Soul Calibur 2 on GameCube". #1652 was the
Dead or Alive 2 build where half the cast is Sonic Adventure 2 characters and half Super Mario 64 DS characters,
drawn at random each time a fighter is picked. This is the same for Soul Calibur II (USA, GameCube): a reader for
every fighter (Link included), a writer that puts collection characters on any fighter's costumes, and the mixed
build with a random costume select.

Code: `gbox/sc2_vmg.py` (VMG models, VGT textures: read, write, engine-rule check), `gbox/soulcalibur2.py` (the disc,
OLK archives, the fighter tables, the reader: `characters.DEDICATED` `soulcalibur2`), `gbox/soulcalibur2_swap.py`
(the writer: `characters op=use`, cast_swap pairs builder, the random build). Tests: `tests/test_soulcalibur2.py`
(synthetic; `SC2_IMAGE=<disc>` adds the owned-disc check).

Catalog: `201629ad498aba7b` "Soul Calibur II (USA)" (HyperSpin `collections/Nintendo GameCube/roms`, GCZ, 1.23 GB,
the target), `e08e8a0c1b3c9060` "Soulcalibur II" (`GC ISO/Soulcalibur II (USA).iso`). Both are `GRSEAF`,
"SOULCALIBUR2", 1 459 978 240 bytes unpacked.

## 1. The disc

| File | Size | What |
|---|---|---|
| `main.dol` | 2.8 MB | **the whole game** (no REL modules); Namco "nn" library (`nn_gamecube.cpp`, `nn_malloc.cpp`), CRI ADX/SFD |
| `root.olk` | 587 MB | every model, texture, motion, stage and move list (below); ends exactly at the end of the disc |
| `bgm.afs`, `movie.afs` | 164 / 282 MB | CRI AFS: music, FMV |
| `opening.bnr` | 6.5 KB | banner |

The files sit at the outer edge of the disc (bgm.afs starts at 426 MB); everything before is padding. A writer
cannot grow `root.olk` (it ends at the last byte of the disc), so every change is made in place at the same size.

### OLK archives (`soulcalibur2.olk_table`)

Namco's "olnk" container, **little-endian** even on the GameCube: `u32 count, "olnk", u32, u32`, then
`count + 1` records `{u32 offset, u32 size, u32 timestamp, u32 0}`; record 0 is `{data start, total}` and the
entry offsets are relative to the data start (0x800 aligned). A size of 0 is an empty slot. `root.olk` holds five
nested OLKs, named by main.dol's table at 0x80257b2c (`{dir, name, 0}` triples): `motinfo` (1 empty slot),
`cpudata` (33: CPU move scripts), `cdata` (516: menus, 2D art, select screen textures, "VGT." sets), `stage` (410),
`human` (982: **the fighters**).

### Packages

Most `human.olk` entries are Namco packages: **big-endian** `u32 count, u32 child offsets` (0 = absent child),
children 0x80-aligned. A costume entry has 14 children:

| Child | What |
|---|---|
| 0 | the **VMG** body model (below) |
| 1 | hit spheres per bone (radius, offset, bone index) |
| 2, 12 | "mmg" motion banks (12 is the fighter's move set; costumes share it) |
| 3 | per-costume face / expression data (packed) |
| 4 | "lpb" move list (little-endian, Shift-JIS move names) |
| 5 | "vtb" table; 6 a little-endian offset table |
| 7-11 | empty |
| 13 | the default **weapon** package (3 children: VMG, its "mmg" motion, hit spheres) |

### Where each fighter lives (main.dol tables; `soulcalibur2.fighter_table`)

Fighter ids are 1-based (7-10, 14, 16, 28, 29 are unused on the GameCube disc). Three tables decide the entries:

* `0x80277a58` s16 per fighter id: the base entry in `human.olk`.
* `0x80275a60 + id * 0xf8`, `+0x8a` s16: the number of costumes (`FUN_800aa518`).
* `0x80277a9c` u8 per fighter id: 1 = the costumes are duplicated at base + 8 for the Extra modes.

Per fighter: `base + c` costume c, `base + 8 + c` its Extra-mode copy (same model, other move set), `base + 16 + w`
weapon w (Weapon Master / weapon select), then motion banks and tables up to base + 38.

| id | Fighter | Base | Costumes | Extra copies | | id | Fighter | Base | Costumes | Extra copies |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Mitsurugi | 46 | 3 | yes | | 19 | Inferno | 748 | 1 | no |
| 2 | Seung Mina | 85 | 3 | yes | | 20 | Cervantes | 514 | 2 | yes |
| 3 | Taki | 124 | 3 | yes | | 21 | Raphael | 553 | 3 | yes |
| 4 | Maxi | 163 | 2 | yes | | 22 | Talim | 592 | 3 | yes |
| 5 | Voldo | 202 | 3 | no | | 23 | Cassandra | 631 | 3 | yes |
| 6 | Sophitia | 241 | 3 | yes | | 24 | Charade | 787 | 2 | no |
| 11 | Ivy | 280 | 3 | yes | | 25 | Necrid | 670 | 2 | no |
| 12 | Kilik | 319 | 2 | yes | | 26 | Yunsung | 709 | 2 | yes |
| 13 | Xianghua | 358 | 3 | yes | | 27 | **Link** | 943 | 4 | no |
| 15 | Yoshimitsu | 397 | 2 | yes | | 30 | Lizardman | 826 | 6 | no |
| 17 | Nightmare | 436 | 3 | yes | | 31 | Assassin | 865 | 6 | no |
| 18 | Astaroth | 475 | 3 | yes | | 32 | Berserker | 904 | 6 | no |

73 costume slots, 116 costume packages (with the Extra copies). Inferno and Charade carry no default weapon
(they borrow the opponent's / a random fighter's). Link's weapon package holds the Master Sword, the Hylian shield and
his props (bombs, bow, boomerang ...) as separate weapon roots.

### How a fighter is loaded (Ghidra on main.dol)

`main.dol` -> ELF with `gcdisc.dol_to_elf` (text sections run through `gcdisc.depair` so stock Ghidra decodes the
paired-single code), `analyzeHeadless ... -postScript DecompileAll.java out.c reg:r13:80468260 reg:r2:80469240`
(SDA bases from `__init_registers` at 0x8000332c). Functions:

* `0x800a1e4c` the per-player load state machine. **Case 7 loads the body**: `lha r26, 0x62(r31)` (fighter id),
  `lha r27, 0x64(r31)` (the costume chosen at character select), `bl 0x800aa518` (costume count),
  `costume = min(costume, count)`, `+8` in the Extra modes (`0x80277a9c`), `+ base` (`0x80277a58`), then
  `FUN_800091b4(..., 5 = human.olk, entry, ...)` streams the package. At 0x800a2138..0x800a2150.
* The weapon is loaded right after (`base + 0x10 + FUN_80111750(id, costume, ...)`).
* The start of the function: when both players have the same fighter and costume, the second one is moved to another
  costume (`FUN_800aa478`); the 2P colour images in every texture record cover the rest.
* `0x801237f0` VMG loader (relocation; "VmgHandler::invalid VMG mark", "data version is %d != %d"),
  `0x8002d1e4` VGT loader, `0x801270cc` model draw, `0x801269d4` CPU skinning, `0x80125c30` sorted-translucent
  meshes, `0x80126684` node matrices, `0x801260a4` texture-stage animation.

### VMG model (`gbox.sc2_vmg`)

Big-endian; offsets from the start of the VMG; the loader adds the base to every pointer.

* Header: `"VMG."`, `u8 3` (version), `u8 0x10` (pointer block at +0x18), `u8 13` pointers, `u8` relocated;
  u16 counts at +0x08: `1`, nodes, meshes in draw lists 0 / 1 / 2 (opaque, second, depth-sorted), bones, materials,
  skin groups; pointers: VGT set, materials, texture stages, nodes, colour block, the three mesh lists, skin groups,
  (optional), bones, bone names, tail.
* **Bone** (0x40): unit quaternion (identity on body bones; swing / helper bones keep other parameters there),
  translation, `1.0`, Euler angles in **turns** (R = Rz Ry Rx), name pointer, scale, `u8 0, u8 parent (0xff root),
  u8 index, u8 kind` (0 body, 2 finger, 3 face, 11 swing). Bones point along their own +X. Bind world =
  `G . chain + root`, G = 90 degrees about +Y (the engine's skeleton frame to model space: +Y up, facing +Z, left
  +X), root = the hip height (Mitsurugi 1.15 m), measured from the skin itself (`skin_root`). The 21 body bones are
  the same names on every fighter: MUNE1 / MUNE2 (chest), KUBI (neck), ATAMA (head), SAKOTSU / KATA / UDE / TE
  (clavicle, upper arm, forearm, hand), KOSHI (hip), MOMO / HIZA / ASHI / TSUMASAKI (thigh, shin, foot, toe), _R / _L;
  then fingers (OYA, HITO, NAKA, KUSU, KO), face (EYE, MABUTA, KUCHI, AGO ...), and swing / constraint bones
  (`himo..__swing`, `kosiarm..__swing`, `..__slerp_..`). 86 (Inferno) to 203 (Cassandra) bones.
* **Mesh** (0x38): `u8 flags` (2 = depth-sorted, a sort header 0x20 bytes before the display list), three
  `{u8 stride, u8 GX component type, u8 fraction}` (position, normal, uv), four index types (position, normal,
  colour, uv: GX_INDEX8 2 / GX_INDEX16 3), `u16` display-list size / 32, then node, material, positions,
  positions (2nd buffer), normals, normals (2nd), colours, uvs, display list, extra.
  * **Skinned** meshes (`16, F32, 0` positions and normals; index16) index the shared world-space buffers the CPU
    skinning writes every frame (double-buffered); their node is the identity node.
  * **Rigid** meshes (`12, F32, 0` positions, `3, S8, 6` normals, index8) carry their own arrays in the space of
    their node; node kind 2 rides bone `node[1]` (armour plates on swing bones, eyes, Inferno and Charade entirely).
  * UVs `S16 / 2048`; colours RGBA8; display lists GX triangle strips (0x98) / lists (0x90), front faces clockwise.
* **Skin group** (0x24): u32 counts of 1-, 2-, 3-influence vertices and of 4+-influence vertices, then pointers:
  records, positions x 2, normals x 2. A record is 16 bytes: `s16 x, y, z` (bone space, pre-weighted, /8192),
  `s16 weight` (8192 = 1), `s16 normal xyz` (pre-weighted, /16384), `u8 count delta, u8 bone`. 4+-influence vertices
  start at 4 records and grow by the delta of each vertex's last record; a record with weight -1 ends the group.
  World vertex = sum over records of `bone world . (x, y, z, w) / 8192`. Every stock costume model (116) passes
  `sc2_vmg.engine_check` with these rules (header counts, terminator, alignment, indices).
* **Material** (0x50): `u32 mode, u32 flags, texture record ptr x 2, -, texture stage ptr x 2, -, colours`.
* **Node** (0x150): `u8 kind, u8 bone`, a pointer (constraint data on a few fighters), a static 4x4 matrix at +0x10,
  then the matrices the engine fills each frame.
* **VGT** texture set: `"VGT."`, `u8 4`, u32 textures, u32 palettes, table offsets; a texture record (0x44) =
  palette record pointer + **two GXTexObj** (the 1P image and the **2P colour** image, used when both players pick
  the same costume; record flag 2); a palette record (0x18) = two GXTlutObj. Images are CMPR (all body textures
  read), some C4 / C8 with palettes, with mip chains where the texture object asks for them.

## 2. Reader (`characters op=collect`, DEDICATED `soulcalibur2`, reader v1)

Per fighter: costume 1's body (both skinned and rigid meshes) on the full skeleton with up to four weights per
vertex, every texture (1P colour), the default weapon's main roots on the hands (BUKI_1 -> TE_R, BUKI_2 -> TE_L,
with their child bones; the game drives weapon roots with the weapon's own motion, so the grip angle in the GLB is
the root's rest frame), metres, +Y up, facing +Z, left +X, the **18 body roles** by bone name. Meta `sc2_reader`,
`sc2_fighter`, `sc2_entry`, `sc2_costume`, `sc2_slot` (`fighter:<key>`), `attachments` (the weapon). Slugs
`sc2_<key>`. Offline: `python -m gbox.soulcalibur2 <disc .gcz|.iso> <out> [key ...] [--costume N]`.

All 24 fighters decode with 18 roles (2026-10-13, owned GCZ): 5 463 (Inferno) to 7 965 (Charade) triangles,
86-203 bones, weapon 166-824 triangles. Render sheet: `D:\gBox\research\soulcalibur2\reader\sheet_all.png`.
Known: the armour plates on swing bones (Mitsurugi's shoulders, Cervantes' coat tails) use the bones' rest frames
(the swing parameters live in the quaternion field), so they can sit at an angle in the bind-pose GLB.

## 3. Writer (`characters op=use`, `gbox.soulcalibur2_swap`)

Slots: `fighter:<key>` (every costume, Extra copies included) | `fighter:<key>:<n>` (one costume) | `player` (=
Mitsurugi, the box-art lead) | `all` / `cast` (pairs `[{target, donor}]`, the rest dealt in roster order) | `random`
(pairs give the donors; their source games form the pools, below). cast_swap uses the pairs path
(`build_cast`, one disc image).

Per costume:

1. **Retarget** with the shared rigid retarget (`sm64_swap.load_rig` + `retarget`, the Retarget editor profile
   applies) onto the costume's own bind skeleton (T-pose), JMAP role -> bone by name. Chibi donors' shoes are taller
   than an SC2 ankle: each foot is shrunk about its ankle (factor 0.5-1) until the sole stands on the floor
   (`ground_feet`). Fit events: scale / retarget / proportion (shared retarget), weights, decimate, encode, write.
2. **Atlas**: the donor's materials packed into one CMPR image (256 x 256, smaller when the room is tight); the 2P
   image is the same atlas 15 % darker.
3. **Encode** (`sc2_vmg.encode`): a new VMG on the template's skeleton: bones, names, nodes (constraint pointers
   cleared; an identity node added for Inferno / Charade, which had none), texture stages and tail kept; one
   skinned mesh (every vertex on one bone, weight 1; 4+-group empty with its terminator), one material (a copy of
   the template's single-texture material), one VGT texture record with both GXTexObj. The fighter's motions, hit
   spheres, move list, face data and weapon all still address the same bones.
4. **Budget**: the costume's VMG bytes (package child 0); decimated (quadric collapse) until it fits. Stock VMGs
   are 170 KB - 1.18 MB; the SA2 / SM64DS donors encode to 109-248 KB (266-1 648 triangles) without decimation.
5. **Disc**: every package of the slot (normal and Extra copies) rewritten in place in a copy of the image (GCZ ->
   ISO), same size, zero padded: no OLK record, package offset or FST entry moves. Read back (`verify_image`:
   package hashes, VMG parse + decode, 18 roles, `engine_check`).
6. **Weapons** are untouched: the weapon packages keep their model and motion, and the weapon roots move with the
   fighter's moves around TE_R / TE_L, which the donor's hands now ride.

## 4. The random Sonic vs Mario build (`slot=random`, `sc2_sonic_vs_mario_random`)

* **Pools**: the collection's Sonic Adventure 2 entries (12: Sonic, Shadow, Knuckles, Tails, Amy, Rouge, Eggman,
  Tikal, Metal Sonic, Super Sonic, Super Shadow, Chaos 0) and Super Mario 64 DS entries (the 8 full-body humanoids
  with hands and feet: Mario, Luigi, Wario, Yoshi, Metal Wario, Peach, Bowser, Koopa Troopa; `pool_slugs` leaves out
  the creatures readiness rates `limited` and Ukiki, which has no hand roles).
* **Plan** (`plan_random`): fighter i's costume c takes pool (i + c) mod 2, so every fighter with two or more
  costumes shows both franchises and half the roster leads with each; donors are dealt round robin per pool
  (shuffled by the seed, `sc2-1652`), never twice on one fighter while the pool has others.
* **Random select** (`RANDOM_PATCH`, main.dol 0x800a213c, 24 bytes): the body load's
  `lha r27, 0x64(r31) ... cmpw / bgt / mr r3, r27` becomes `mftb r27 ... divwu r0, r27, r3 / mullw r0, r0, r3 /
  subf r3, r0, r27`: the costume index is the time base modulo the fighter's costume count, drawn each time a
  fighter's body is loaded for a match (so a rematch / Continue draws again). The selected costume still picks the
  weapon and the 2P colour. The bytes are checked before patching (`random_patch_site` refuses an unknown DOL).
  DOA2 (#1652) has no shared random-select code on origin yet (`docs/doa2_mixed_random.md` is not pushed); this
  patch is SC2-specific.
* Built 2026-10-13 on the Windows PC from the owned GCZ and the local collection mirror
  (`D:\gBox\cache\characters_mirror`): 73 / 73 costume slots built, 116 packages rewritten, read back OK
  (hashes, decode, 18 roles, engine_check), random select present; about 4 minutes.
  `python -m gbox.soulcalibur2_swap random <gcz> D:\gBox\cache\characters_mirror <out> --pool sa2 --pool sm64ds
  --seed sc2-1652 --image-name "Soul Calibur II (USA).iso"`.
* Installed at `D:\gBox\cache\mods\201629ad498aba7b\sc2_sonic_vs_mario_random\` (`Soul Calibur II (USA).iso` +
  `.gbox-mod.json`, built in `D:\gBox\cache\characters_build\sc2\` and moved after verification).
* Evidence: `D:\gBox\research\soulcalibur2\evidence\sc2_<fighter>_before_after.png` (stock costumes over the built
  ones, every costume, weapon on the hands).

## 5. Live check (operator)

1. Launch `sc2_sonic_vs_mario_random` for Soul Calibur II (USA) in gBox (Dolphin).
2. Arcade or VS: pick Mitsurugi -> expected one of Shadow / Luigi / Tails with Mitsurugi's katana, moves and
   voice; go back and pick him again a few times: the body should change between picks.
3. Pick Link and Astaroth (big frames), Voldo (his unusual stance), Inferno / Charade (rigid-only originals, now
   skinned), Lizardman / Assassin / Berserker (6 costumes).
4. Report: crashes or hangs at the loading screen (the new VMG layout), missing or black textures (VGT records),
   the body not following the moves (bone mapping), the weapon away from the hands, the same body on every pick
   (the patch not reached), and any mode where the body stays stock (another load path).

## 6. Limits / not done

* Rigid single-bone skinning (as every gBox rigid retarget): joints can stretch in extreme poses; the donor's
  fingers, face and swing bones are not used (the stock model's cloth / hair swing goes away).
* The select screen's portraits and names, the 2D art in `cdata.olk` and the profile / ending screens are stock.
* Weapons stay the fighters' own (by design); Inferno / Charade still borrow theirs.
* The random draw happens at the body load, not on the select screen, so the select screen does not preview it.
* Not verified in Dolphin: no game was started from this work.
