# GTA: Vice City (PC) — native character swap (gbox/gta_vc_models.py, gbox/gta_vc_swap.py)

Inbox #220 ("replace Tommy Vercetti in GTA with Ganondorf, or have him replace all the pedestrians") and #113 (the
same wish with Mario, closed on the LCS writer). Branch `gta-vc-pc-writer`, 2026-10-12.

## What the catalog actually owns (checked on 2026-10-12)

| game id | title / platform | launch target | what it is |
|---|---|---|---|
| `1fd42f50b10252e6` | Grand Theft Auto Vice City, windows_native (HyperSpin "PC Games") | `collections/PC Games/roms/Grand Theft Auto Vice City.bat` → `GTA Vice City/Gameface/Binaries/Win64/ViceCity.exe` | **The Definitive Edition** (Unreal Engine 4, project "Gameface"). `Gameface/Content/Paks/gta.pak`: 9,089,889,709 bytes, pak version 11, index unencrypted, compression methods `zlib` + `Oodle`, mount `../../../`, 111,209 entries (45,215 .uasset / 45,266 .uexp / 16,513 .ubulk). Peds are UE4 skeletal meshes: `Gameface/Content/ViceCity/Characters/Peds/SK_player.uasset` + `SK_player_skel`, `SK_cop`, `SK_male01`, `SK_wfypr`, … (610 SK_* / _skel entries under Characters/Peds). The pak also carries `Gameface/Content/OriginalData/ViceCity/data/*.ide/*.ipl/*.dat/main.scm` and `models/coll/*.col` (the original data scripts, no .dff/.txd/.img). `Gameface/Content/Paks/~mods` exists (UE4 loads extra .pak files from it). **No `models/gta3.img`.** |
| `5eacc9f11d9a5956` | Grand Theft Auto: Vice City (USA), windows_native (HyperSpin emulator "Microsoft XBOX") | `collections/Sony Playstation 2/roms/USA/Grand Theft Auto - Vice City (USA).chd` | a **PS2 disc image** (2,203,216,057 bytes, present on the share) filed under the wrong HyperSpin system. Not a PC install; no chdman/7z on this PC to open it. |
| `a2961272cbfaf3a8` | Grand Theft Auto Vice City, ps_modern | a PS4 launcher stub | not a target. |

No classic (RenderWare) Vice City install was found on this PC (Steam/Rockstar folders, D:, the Spark share).

Consequence: the writer below is complete for the **classic RenderWare PC port** (the format the operator's request
and the GTA III writer lineage assume) and is registered on both windows_native ids, but **the owned install cannot
be modded by it**. `characters op=use` detects the Definitive Edition (`gta_vc_models.locate_install`) and answers
with the overlay fallback + a gap report naming the real route (a UE4 cooked-SkeletalMesh writer + a `~mods` .pak)
instead of guessing. The live check waits for a classic install (or for that UE4 writer).

## Formats (classic port)

Sources: RenderWare binary stream sections as documented on gtamods.com (DFF, TXD, Skin PLG, HAnim PLG, Texture Native
Struct, IMG archive), librw (skin.cpp, hanim.cpp, d3d.cpp, d3d8.cpp) and re3/reVC (PedModelInfo). Confidence is per
item; nothing below was read from an owned classic file (none exists here), everything is exercised by synthetic
round trips in `tests/test_gta_vc_models.py` and `tests/test_gta_vc_swap.py`.

- **IMG v1** (`models/gta3.img` + `models/gta3.dir`): DIR = 32-byte entries `{u32 offset (2048-byte sectors), u32 size
  (sectors), char name[24]}`; IMG = the entries' data at those sectors. Same layout `gbox/gta_rw.py` already reads on
  the GTA III PS2 disc. High confidence. `ImgArchive.rebuild` writes a new IMG with replaced entries (original order,
  offsets recomputed, every other entry byte-identical, DIR names kept verbatim).
- **DFF**: RW library id `0x1003FFFF` (3.4.0.3; `gta_rw.rw_version` unpacks packed ids now, so 3.3 PC files keep their
  lighting floats). VC peds are one smooth-skinned atomic: frame list with one frame per bone, **HAnim PLG `0x11E`**
  on each bone frame (`u32 0x100, u32 bone tag, u32 numNodes`; the hierarchy root adds `u32 flags, u32 36` and the
  node table `{tag, index, flags}` in skin-bone order) and **Skin PLG `0x116`** in the geometry extension
  (`u8 numBones, u8 numUsedBones, u8 maxWeights, u8 pad, u8 used[], u8 idx[nv][4], f32 w[nv][4], f32 invBind[numBones][16]
  (RW < 3.4.0.3: `0xDEADDEAD` before each matrix), u32 boneLimit, u32 numMeshes, u32 numRLE`). High confidence on
  both plugins. Geometry is plain RW geometry (positions/normals/UVs in the Struct, Bin Mesh in the extension); the
  writer emits a Bin Mesh **triangle list**, which the D3D8 driver instances like a strip. A D3D8 **native** geometry
  decoder (Native Data PLG `0x510`, platform 8, per-mesh 44-byte header + u16 indices + FVF-laid-out vertex buffer)
  is included for files that carry one; medium confidence (librw's d3d8.cpp layout from memory, self-checked by the
  FVF-derived stride), never written.
- **Role map**: the game binds ped nodes by HAnim **bone tag** (reVC `CPedModelInfo::ConvertPedNode2BoneTag`):
  pelvis 1, spine 2, spine1 3, neck 4, head 5, L clavicle/upperarm/forearm/hand/finger 21–25, R 31–35, L thigh/calf/
  foot/toe 41–44, R 51–54. `gta_vc_models.BONE_ROLES` maps those to gBox roles (`pelvis, hip=spine, chest=spine1,
  neck, head, l_/r_clav, l_/r_upper, l_/r_fore, l_/r_hand, l_/r_thigh, l_/r_shin, l_/r_foot`); frames without a tag
  fall back to the Biped frame names (`Pelvis, Spine, Spine1, Neck, Head, Bip01 L Clavicle, L UpperArm, L Forearm,
  L Hand, L Finger, …, L Thigh, L Calf, L Foot, L Toe0`, case/prefix-insensitive). The map is **read from the file at
  build time** (`role_map` raises, listing the frames, when a required role is missing); the name table is expected,
  not yet verified on an owned player.dff. `Clump.stats()["role_source"]` records which rule produced each role.
- **TXD**: Texture Native platform 8 (D3D8), one Struct: `u32 8, u32 filter/addressing, char name[32], char mask[32],
  u32 rasterFormat, u32 hasAlpha, u16 w, u16 h, u8 depth, u8 levels, u8 type (4), u8 dxt (0/1/3/5), [palette 256×RGBA
  for PAL8], per level {u32 size, pixels}`. Decoded: PAL8, 8888 (BGRA bytes), 888, 565, 1555, 4444, LUM8, DXT1/3/5.
  High confidence on the layout and DXT; medium on the palette byte order (RGBA, as librw stores it). Platform 9
  (D3D9, SA) reads too. The writer always emits **8888 with a mip chain when the original had one** — the format
  every VC PC TXD may declare, so no DXT encoder is needed.

## The swap

`characters op=use character=<slug> game=<Vice City> slot=player | ped:<dff> | peds:all | all`

1. `locate_install` resolves the HyperSpin `.bat` (`set "GAMENAME=…"`, `set "GAMEPATH=…"`) to the exe and looks for
   `models/gta3.img` beside it (classic) or `Gameface/Content/Paks/gta.pak` (Definitive Edition).
2. Per target DFF (`player`, one ped, or `ped_family`: every ped whose HAnim tag set equals the player's, from
   `data/default.ide`'s `peds` section or an archive scan): `Clump` reads frames/HAnim/skin and the role map;
   `re4gc_enemies.retarget` fits the donor (rigid per limb, one bone per vertex, 1.50–1.95 m); the triangles become
   one welded geometry in the atomic's frame space with a new Skin PLG on the **original inverse bind matrices**;
   `pack_atlases` builds one atlas (≥256²) that replaces the raster material 0 draws with (8888).
3. `ImgArchive.rebuild` writes the new gta3.img/gta3.dir into `cache/characters_build/<mod>/`, read back and hashed;
   `filemods.build` makes the mod dir (`cache/mods/<game_id>/gtavc_<slug>[_<slot>]`): a hard-link copy of the install
   with the two files replaced, `.gbox-mod.json` listing entries, slot, source/new sha256, exe. The install is never
   written.
4. Launch: HyperSpin "attract" entries start through RocketLauncher, which takes no mod, so `use()` returns the mod's
   exe path to run; a windows_native entry with a direct `launch.path` gets the usual `@launch` job with `mod=`.

Tests: `tests/test_gta_vc_models.py` (15 synthetic + 2 owned-install: one identifies the install, one extracts and skips
without a classic port), `tests/test_gta_vc_swap.py` (8 synthetic incl. a filemods build on a synthetic install and the
Definitive-Edition gap route, 1 owned-install, and `test_swap_files_with_ganondorf`, which retargets the real
`melee_ganondorf` glTF when it is on the node: 6,326 triangles / 4,033 vertices, 343 KB DFF, hands/feet/calves/arms on
their bones). Note for that donor: the collection's `rig.roles` map `chest`, `neck` and `head` all to `j017_BustN`, so
the torso rides the Head bone (3,039 triangles there); giving `chest` its own joint in the meta fixes the fit for every
writer, not only this one.

## Live check (not done; needs a classic install)

1. Add the classic port to the catalog (any windows_native entry whose launch resolves to `gta-vc.exe` with `models/gta3.img`).
2. `characters op=use character=melee_ganondorf game=<that id> slot=player launch=false` → mod `gtavc_melee_ganondorf`.
3. On the agent test PC run `<cache>/mods/<id>/gtavc_melee_ganondorf/gta-vc.exe`, start a new game, skip the intro;
   frame-capture Tommy in the first street (Ocean View hotel): Ganondorf's body on Tommy's walk/run/jump, get into a car.
4. `slot=peds:all` the same way: every street ped is Ganondorf (the IMG grows by ~110 × ~0.4 MB of 8888 atlases).
5. Record `runtime` with the capture; `writer` once 2–3 succeeds.

For the owned Definitive Edition the equivalent is a different writer: read `SK_player.uasset/.uexp` (UE 4.26 cooked
SkeletalMesh, Oodle-compressed pak entries, `oo2core` DLL ships in the install), retarget onto its reference skeleton,
write a cooked SkeletalMesh and pack a `~mods/*.pak`. The pak index facts above are its inventory.

## Readiness ledger

`record_game_work` writes through the gBox API (hermes_work_queue.checkpoint needs the game's favorite queue item
and its request id), which this run was not allowed to call. Suggested record: stage `inventory`, status `partial`,
note = the "What the catalog actually owns" table; stage `writer`, status `partial` (synthetic verification only),
next step = "install the classic RenderWare port or write the UE4 SkeletalMesh writer".
