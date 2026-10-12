# Character model swaps: feasibility and pipelines

Status: **research only.** Web research done 2026-10-06. Nothing was downloaded, installed or run.
Licensing: every source model here (Nintendo, SEGA, Capcom, Rockstar) is copyrighted. Use them for personal, local modding only. gBox must never redistribute extracted assets or built mods. It should only use the ROMs and installs the operator already has, and build the mod output locally.

## TL;DR

| Request | Target | Feasibility | Best route |
|---|---|---|---|
| "Replace Link with Ganondorf, fully playable" | OoT, Ship of Harkinian (SoH) | **Easy** (a ready-made mod exists) | Drop the existing "Playable Ganondorf" `.otr/.o2r` into `SoH/mods` |
| Same, on the N64 ROM / ModLoader64 | OoT 1.0 (Online) / ROM | **Easy-Medium** | ModLoader64 cosmetic `.zobj` (zzplayas). Ganondorf models are already listed there. |
| Any collection character as Link / an NPC, swaps, statues | OoT N64 ROM | **Done in gBox** | `characters op=use / swap / place` (gbox/oot_swap.py, section 1) |
| Mario 64 Mario as Link | SoH | **Easy** (ready-made) | GameBanana "SM64 Mario As Child & Adult" |
| Ganondorf as an MK64 driver | SpaghettiKart (MK64 PC port) | **Medium** | Rig the model to the Kart Setup `.blend`, render sprites, pack as `.o2r`. Can be scripted headless. |
| Ganondorf as an MK64 obstacle | MK64 decomp / SpaghettiKart | **Hard** | Needs C code (a new actor) in the decomp or port. No data-only route. |
| Mario/Sonic/Ryo as Tommy/Claude | GTA III / VC (PC) | **Easy** (ready-made skins exist) | Replace `player.dff/.txd` in `models/gta3.img` |
| Ganondorf as Tommy, or "replace all peds" | GTA III / VC (PC) | **Medium** | DragonFF (Blender) export to `.dff`, then rename it over each ped entry in `gta3.img` |
| Any library character as Toni | LCS PS2 | **Done in gBox** | `characters op=use` builds `lcs_<character>`: every Toni outfit replaced (gbox/gta_stories_models.py, section 3). VCS/PSP not yet. |
| Any library character as Glitch, or as a bot picked on screen | Metal Arms GameCube | **Done in gBox** | `characters op=use` builds `ma_<character>` (Glitch, play + cutscenes) or, with `slot=npc` + a screen point, `ma_<character>_<bot>` (gbox/metal_arms.py, section 8). Glitch is in the collection with body roles. |
| Any library character as a wrestler (one or several per ROM) | WWF No Mercy (N64, USA Rev A) | **Done in gBox** | `characters op=use` / `op=match` builds `nomercy_<character>_as_<wrestler>` (gbox/aki_wrestling.py, section 9). World Tour USA and Revenge USA also have native readers and writers in `gbox.aki_wcw`; SmackDown! 2 USA uses `gbox.yukes_sd`. |
| Any library character as Aya (all 5 outfits, field + battle) | Parasite Eve (PS1) | **Done in gBox** | `characters op=use` builds `pe_<character>` (gbox/pe_swap.py, section 10). Mario checked on the Spark. |
| Any library character as Cloud (field + battle models) | Final Fantasy VII (PS1) | **Done in gBox** | `characters op=use` builds `ff7_<character>` (gbox/ff7_swap.py, section 11). Mario checked on the Spark. |
| Which games can rip / reimport, and the fallback | every studied game | **Done in gBox** | `characters op=coverage` (section 12). No writer: overlay + a gap report. |
| Leon/Mario/Sonic as player | RE4 2005 UHD (PC) | **Medium** | JADERLINK BIN/TPL tools: SMD/OBJ in, `.bin/.tpl` back into `pl*.udas`. Leon-replacement mods exist. |
| Mario/Sonic as Chris/Jill/Leon/Claire | RE1/2/3 classic PC | **Hard** | RE2MV/RE3MV with OBJ per body part. Very low-poly rigid segments, mostly manual. |
| OoT characters as PSO Boomas (keeping Booma animations) | PSO BB (PC) | **Hard** | pso-blender (jtuu) `.xj` export into the Booma `.bml` via PSOBMLExtract. The model must match the Booma bone hierarchy. |
| Same, on DC v2 / GC | PSO DC / GC | **Hard / Not practical** | `.nj` export is immature. GC `.bml/.gsl` can be repacked but there's no reliable skinned `.nj` exporter. |

**Recommended first demo: the SoH Playable Ganondorf.** It's a single file copy: put the `.otr/.o2r` in `mods/`, launch SoH and enable it in the mods/alt-assets menu. It fully answers "replace Link with Ganondorf, fully playable" without any authoring. The **second demo** (the first real gBox pipeline) is a **GTA VC player skin swap** using an existing skin, for example Mario: replace two files in an IMG and launch. The **first authored pipeline** to build is **SpaghettiKart Ganondorf driver**: Blender headless renders the sprites, then a zip makes the `.o2r`.

---

## 1. Zelda: Ocarina of Time

### Existing mods
- **Playable Ganondorf** for SoH, category "Adult Player Model - Unaltered Skeleton": https://gamebanana.com/mods/468244
- Melee Overhaul (Link, Sheik, Zelda & Ganondorf): https://gamebanana.com/mods/445818
- Ganondorf's Dream (Halloween mod): https://gamebanana.com/mods/545674
- SM64 Mario As Child & Adult (SoH): https://gamebanana.com/mods/648609
- Other play-as examples (Malon, Linkle, MM Link): https://gamebanana.com/mods/468571, https://gamebanana.com/mods/460431, https://gamebanana.com/mods/442908
- ModLoader64 cosmetic model list, which includes a Ganondorf-compatible model by Zalfur: https://modloader64.com/models.html

### How it loads
- **SoH (PC port)**: custom assets are `.otr` (older) or `.o2r` (newer, a renamed zip) archives in `mods/`. They override the Link player-model resources. GameBanana categorises these as "Unaltered Skeleton" (they use Link's skeleton and animations as-is) or "Altered Skeleton". Tutorials: https://gamebanana.com/tuts/16969 and https://gamebanana.com/tuts/17975. Fast64 is the Blender authoring/export addon: https://github.com/Fast-64/fast64. SoH source: https://github.com/HarbourMasters/Shipwright
- **ModLoader64 / OoT Online**: a play-as `.zobj` built with **zzplayas** from a Blender export plus a per-ROM/per-character **manifest**. Pipeline guide: https://github.com/hylian-modding/Z64-CustomPlayerModels/blob/master/guide/README.md. Tool: https://old.z64.me/tools/z64playas
- **Raw ROM**: zzplayas can also inject straight into a ROM (decompressed OoT 1.0 is the usual target). Use the play-as manifests that match the ROM version. Check whether a manifest exists for **v1.2**, because 1.0 is better supported.

### What a custom player model needs
- The model must follow **Link's limb hierarchy** (21 limbs in Link's skeleton). Each limb gets its own display list. Vertices are weighted to one limb (rigid). Link's N64 mesh doesn't use smooth skinning.
- Animations always stay **Link's**: the game drives the limb rotations. A model with "Unaltered Skeleton" therefore animates correctly, but proportions are limited. Ganondorf needs taller limbs, which the "Altered Skeleton" mods handle by changing limb offsets.
- Equipment display lists (sword, shield, hands holding items, bottle, etc.) are separate named display lists that the manifest maps. A playable model needs them all, or gameplay will show missing or Link-shaped items.
- Polygon and texture budgets are N64-tight for ROM/ML64. SoH is more forgiving.

### Source assets
- OoT Ganondorf (`object_gnd` for the Ganondorf boss, `object_ganon`/`object_ganon2`) can be viewed and exported with **Z64Utils**: https://github.com/zeldaret/Z64Utils. Reference rips (view only): https://models.spriters-resource.com/nintendo_64/thelegendofzeldaocarinaoftime/
- The OoT decomp plus Fast64 can import the decomp's objects into Blender (https://github.com/Fast-64/fast64).

---

### N64 ROM: built into gBox (`gbox/oot_swap.py`, `oot_writer.py`, `oot_place.py`, `oot_live.py`, 2026-10-07)

Status: **works on NTSC 1.2 (USA Rev B, the operator's ROM), checked in game on the Spark**. Tifa played as child
and adult Link (walking, rolling, sword swings, Kokiri Sword + Deku Shield, Master Sword + Hylian Shield on the back).
A Cloud model was put on the Kokiri boys. A Cloud statue was placed in Kokiri Forest, both live and in the ROM.
The ROM layer also reads NTSC 1.0 / 1.1, PAL 1.0 / 1.1 and the GameCube US/EU ports. It finds versions by md5,
else by the dmadata position, and finds `code` tables by content. Those versions were only checked offline (Link's
skeletons, the code tables and the reusable bytes are all found); they have not been checked in game.

Reference: zeldaret/oot (github.com/zeldaret/oot), cloned on the Spark at `/home/ehm_eckx/ref/oot` and read as
documentation only (it has no LICENSE file; nothing from it is shipped or run). gBox keeps only facts from it: offsets,
table contents, struct layouts and enums.

**ROM model** (`oot_writer.Rom`)
- Every file is Yaz0-compressed and reached through dmadata `{vromStart, vromEnd, romStart, romEnd}`.
- DmaMgr searches dmadata linearly, and `romEnd = 0` means the file is stored uncompressed.
- A changed file is stored uncompressed after the ROM data, so the ROM becomes 64 MB.
- A file that grows gets a fresh VROM range past every other file. Every table that names the old range is updated:
  - `gObjectTable` in `code` (found by its gameplay_keep entry)
  - a scene's room list, for room files (`Rom.ref_files`)
- `code` keeps its size. The CIC-6105 CRC is recomputed.
- Mod images keep the game's own file name, so RetroArch uses **the same save file** for the plain game and every OoT
  mod. Save states made with a different build don't carry over (the RAM copy of dmadata is old); load the file instead.

**Display lists**
- `oot_writer.run_dl` is an F3DEX2 walker. It handles 32-entry vertex batches, matrix slots on segment 0x0D, the
  texture and TLUT state and the combiner.
- `object_mesh` and `write_gltf` turn any object skeleton into a skinned glTF. Textures are decoded from
  CI4/CI8/RGBA16/IA/I. Mirrored wraps are unfolded into the image. PRIM and ENV are multiplied in when the combiner
  uses them.
- `encode` writes new lists:
  - textures as RGBA16 LoadBlock, at most 2048 texels
  - Link's own combiner and render mode (TEXEL0×SHADE, then PRIM×COMBINED; G_RM_FOG_SHADE_A / AA_ZB_OPA_SURF2)
  - lit by the scene's lights through vertex normals, or unlit with baked vertex colours (statues)
  - culling off while the model draws

**(A) Link** (`characters op=use character=X session_id`, or `game`)
- Target: `object_link_boy` at 0x377F4 (adult) and `object_link_child` at 0x2CF6C (child). Both are
  FlexSkeletons with 21 LOD limbs and 18 display lists.
- Pose: Link's idle animation (gameplay_keep 0x3238 → link_animetion). The child's root is ×0.64, as the game does.
- Roles are fixed (`LINK_ROLES`). The retarget is `sm64_swap.retarget` with a joint map (`jmap`): rigid, one limb per
  vertex. Limbs without a display list pass their vertices to the nearest ancestor that has one.
- Link's limb count, order and joint offsets never change, so every animation plays.
- Every limb that had a list keeps one (empty if the model has nothing there). The flex matrix count and
  `bodyPartsPos` therefore stay the same.
- Hands, waist and first person: the 20 display-list tables of z_player_lib.c in `code` are found by content and
  repointed. The plain hand lists become the new hands.
- Equipment lists (sword, shields, bow / slingshot, hookshot, ocarina, hammer, boomerang, bottle):
  - Link's hand triangles are turned into no-ops, matched by material (any texture or colour that his body uses).
  - The table then points at `[new hand] → branch to the stripped list`, so the item stays in the new hand.
- The sheath and the shield on the back are left as they are. Iron / hover boots, gauntlet plates and the Goron
  bracelet are blanked.
- Object space: the 19 object slots of a scene share about 1000 KB (child Kokiri Forest has about 130 KB free with
  vanilla objects). Each object therefore grows as little as possible:
  - `oot_writer.reclaimable` finds the bytes only the replaced body used: its limb and plain-hand lists and their
    vertices. It excludes anything a kept list, the sheath tables, or a word in `code`, `ovl_player_actor` or
    `ovl_kaleido_scope` uses.
  - `encode` fills those bytes first.
  - Example: adult Tifa reuses 48 KB and grows 28 KB; child Tifa reuses 43 KB and grows 33 KB.
- The equipment lists are stripped **before** the old bytes are overwritten. Doing it the other way round made the
  emulator crash with SIGBUS.
- Budget: Blender decimation down to 1500 triangles (then 70 / 50 / 35 %). Textures go 64×32 → 32×32 → 16×32 before
  any texture is flattened to its mean colour. Up to 40 KB of growth per age is allowed.

**NPCs** (`op=use` with x/y or `slot=<name>`)
- `oot_live.pick` reads every actor list in PlayState+0x1C24. It projects world.pos and focus.pos with
  `viewProjectionMtxF` (PlayState+0x11D60) and picks the actor nearest to the point.
- The actor's object comes from its objectSlot → objectCtx.
- The SkelAnime sits at the end of the retail Actor (0x13C). It gives the limb table, as a RAM address converted to an
  object offset, and the current jointTable, which is used as the fitting pose.
- Without a session, the most upright animation frame found in the object (or in object_os_anime for En_Ko) is used.
- `guess_roles` labels any skeleton:
  - legs: the two lowest leaf chains
  - head: the highest joint outside the legs
  - hip: where the legs and the head meet
  - arms: the two longest remaining chains, with left and right taken from the shoulder side; models face +Z
  - If it can't find two arms and two legs, it says the NPC isn't humanoid. The app's overlay is the fallback.
- The same guesser gives Tifa (FF7, no meta roles) her roles. It reproduces Cloud's hand-made roles exactly.
- Compound actors: `GROUPS` lists them. For example, En_Ko boys draw from `object_km1`, while girls draw from
  `object_kw1` with Fado's head from `object_fa`. A group gets the same data at the same offset in every object of the
  group, and the constant head list is branched to the new head.
- Writing the object changes every actor that uses it (all Kokiri boys).

**Extract / swap / play as**
- `op=extract` takes a picture point or a name (Link, Saria, a Kokiri girl, En_Sa, object_sa). It writes the
  object's skeleton, lists and textures as a glTF in the collection (`oot_link_adult` / `oot_link_child` / `oot_<object>`),
  with roles, and checks the preview.
- `op=swap a b` extracts both if needed. In one mod it writes B into A's target and A into B's.
- `one_way=true` ("Play as B") writes only Link ← B.
- `op=use` / `op=swap` merge with what the session's mod already does, so "Tifa as Link" survives "Cloud as the Kokiri".

**(B) Statues in the world** (`op=place character=X session_id [near=Y | x y | pos] [size, yaw]`, `op=unplace`)
- Chosen method: hook the room's own display list. This needs no new game code, hits no actor or object-slot limits,
  and works the same live and in the ROM.
- Room_Draw calls each mesh entry's opaque list with an identity model matrix and SetupDL 25.
- gBox points one entry at a wrapper: for each statue, `G_MTX push(placement matrix) → statue lists → G_POPMTX`, then
  a branch to the room's own list. The statue is unlit (baked shading), restores SetupDL 25's modes, and has no
  collision.
- For cullable rooms, the hooked entry is the nearest one, and its bounding sphere is grown.
- Live:
  - The data sits at the end of the object space (objects fill from the start).
  - It is addressed through segment 0x0E, so it can sit wherever the space ends.
  - A watcher thread on the session's worker (`oot_models op=apply`) re-hooks after every room or scene load. If the
    game's objects ever reach the data, the statue is unhooked.
  - The expansion RAM (0x80400000+) can't be used: GLideN64 masks display-list addresses to 4 MB and drew garbage.
  - Live statues are about 600 triangles (40 KB).
- ROM:
  - Data appended to the room file (segment 3), at most 1200 triangles.
  - The room file moves to a new VROM range, and the scene's room list is patched.
  - Placements are stored per game in `<cache>/oot_places/<game_id>.json`. Every OoT mod built afterwards contains
    them.

**What's left**
- The live tools (pick, place, the watcher) know NTSC 1.2's PlayState address only, like `gbox/oot.py`. ROM builds
  work for every version listed above.
- Items that draw from the hand lists Link holds in cutscenes (Get Item, ocarina) keep Link's hands.
- Masks, the Goron / Zora tunic colour and eye / mouth expressions don't apply to the new model.
- A source missing a hand bone (FF7 Tifa's right hand) leaves that hand on the forearm.
- No live hot swap for Link yet: the swap is a ROM mod and a relaunch (with the same save).

**Bounded live NPC replacement (#706, 2026-10-08)**
- Experimental: compiler, transaction and dispatch checks pass, including a real Cloud→Saria object build.
  Visual gameplay verification is still pending: a private cloned-save test reached NPC loading but stalled
  with a black frame and pending object DMA. No user session or save file was modified by that test.
- `characters op=live_use character=cloud session_id=... x=... y=...` resolves the NPC at that exact picture point.
  This is a native memory replacement, with no relaunch, ROM switch, or overlay. The model-card drop menu exposes
  it directly without a chat/vision call; the separate build-and-restart option keeps its existing behavior.
- Currently limited to NTSC 1.2 humanoid NPCs with one object and enough reclaimable model bytes. The compiler
  retargets the library character, simplifies it to the memory budget, and stores all lists/textures/vertices,
  including the empty limb list, inside the original object size. Compound NPCs and Link return unsupported.
- The worker pauses for target validation and writes, validates the allocation and expected bytes, reads back
  changed ranges, and rolls back a partial write. A game that was already paused remains paused.
- A replacement affects every loaded actor sharing that object, and ends when the object reloads. Repeated
  changes in the same loaded object are supported. This does **not** fulfill individual-instance targeting,
  persistence over room/age changes, Link hot swapping, or universal game/character support. #706 remains pending.

---

## 2. Phantasy Star Online (Boomas)

### Formats
- BB (PC): enemies live in `.bml` archives (PRS-compressed) that contain `.xj` (or `.nj`) meshes, `.njm` animations and `.xvm` textures. Ultimate variants are `*_a.bml`.
- GC: `.bml` (models/animations) and `.gsl` (textures).
- DC: Ninja `.nj/.njm` with `.pvm` textures in `.afs`/`.bml`.

### Tools
- **PSOBMLExtract** (extracts and repacks `.bml/.gsl`, handles PRS automatically): https://github.com/Shadowth117/PSOBMLExtract
- **pso-utils** (Python unpack/repack for the GC formats): https://github.com/choogiesaur/pso-utils
- **pso-blender** (jtuu): Blender 4.2+ import/export for BB `.xj`/`.bml`, `.rel` and `.xvm`, with *experimental* `.njm` export: https://github.com/jtuu/pso-blender (fork: https://github.com/BiscuitIsntMyName/pso-blender)
- **PSO Ultimate Importer** (Blender, import only: `.nj/.njm/.xj` from DC/GC/BB): https://github.com/theanine3D/pso_ultimate_importer
- Noesis-based workflow and the older toolchain (bmltool, vmt, AFSManager, ModelViewer, GSLUpdater): https://www.phantasystaronline.net/forum/index.php?/topic/34646-how-to-mod-pso-with-noesis-and-blender/
- Community status threads: https://www.pioneer2.net/community/threads/state-of-model-swapping-in-psobb-updated-05-01-2020.16700/ and https://www.pioneer2.net/community/threads/modding-all-the-3d-models.21944/ (Cloudflare blocked automated fetches of both, so they're cited from search snippets.)

### Prior art
- Enemy model replacement on BB has been done before, for example a PSO2 Rappy high-res port into BB: https://kireekpso.wordpress.com/2012/10/27/pso2-rappy-high-res-port-nighttime-paradise-for-bb/. Character body swaps: https://www.youtube.com/watch?v=bv-fhdNihzs

### How to retarget onto the Booma
To keep the Booma's `.njm` animations, the new mesh has to be bound to the **Booma's Ninja node tree**: the same node count, order and rest transforms. The `.njm` motions address nodes by index.

1. Import the Booma `.xj` and its `.njm` with pso-blender.
2. Fit the OoT model (for example a Moblin or Ganondorf from Z64Utils) to the Booma armature. Booma is a hunched quadruped-ish biped, so a humanoid needs heavy proportion edits.
3. Weight the mesh to the Booma bones. PSO meshes are mostly rigid per node, so each mesh chunk goes to one node.
4. Export the `.xj`, repack the `.bml`, and replace the file in the client `data/` folder.

Server checks: the files are client-side. Private servers may checksum the data, so test offline or on a local server such as newserv: https://github.com/fuzziqersoftware/newserv

Feasibility: **Hard.** The exporter is experimental, the skeletons are different and the fit has to be done by hand. Automation can do the import, export and repack. It can't make a good fit.

---

## 3. GTA III / Vice City / Liberty City Stories

### PC (III / VC)
- Format: RenderWare `.dff` (model) and `.txd` (textures) inside `models/gta3.img`. Peds are defined in `data/default.ide` (`peds` section: model, txd, anim group): https://gtamods.com/wiki/PEDS
- Tools: **DragonFF** Blender addon (import/export `.dff`, skinned meshes, mass export): https://github.com/Parik27/DragonFF and https://extensions.blender.org/add-ons/dragonff/. Use an IMG tool (or Magic.TXD) to replace entries.
- Rig: the stock PC III/VC peds are **segmented, rigid hierarchies**. Frame names and order must match the original ped (for example the root, pelvis, spine, head and limb frames). Vertices are rigid per frame. Smooth skinned peds need the **Skin and Bones** plugin (aap) for III: https://gtaforums.com/topic/815077-skin-and-bones/ and https://www.mixmods.com.br/2018/08/iii-skin-and-bones-3-0-xbox-peds-claude-corpo-suave/. re3/reVC also support skinned (Xbox/mobile) peds: https://github.com/GTAmodding/re3
- **Player**: replace `player.dff/player.txd` (VC) in the IMG.
- **Replace all pedestrians**: copy or rename the same `.dff/.txd` over every ped entry in the IMG. Alternatively, point each `default.ide` ped line at one model and txd. Scripting this is trivial.
- **Built into gBox (2026-10-12, classic VC PC port)**: `gbox/gta_vc_models.py` (reader: IMG v1, HAnim/Skin, D3D8 geometry + rasters, rigged GLB) and `gbox/gta_vc_swap.py` (writer: slots `player`, `ped:<dff>`, `peds:all`, `all`; rebuilt `gta3.img/.dir` in a filemods mod dir). Routed for both windows_native ids. The owned install is the **Definitive Edition** (UE4 pak, no `gta3.img`), which `op=use` detects and reports as a gap; see `docs/gta_vc_pc_swap.md` for the facts, the bone-tag role map and the live check.

### Existing skins
- VC Mario player model (ripped from SM64): https://www.modland.net/gta-vice-city-mods/skins/mario-player-model.html. Thread: https://gtaforums.com/topic/289934-trying-to-use-the-mario-skin-mod/
- VC Sonic Pack (Sonic, Shadow, Super Sonic): https://www.gtainside.com/en/vicecity/skins/10238-sonic-pack/
- VC Sonic (SSBB): https://www.gtainside.de/en/vicecity/skins/198207-sonic-ssbb-skin/
- VC Sonic Boom: https://libertycity.net/files/gta-vice-city/100301-sonic-boom.html
- GTA III Ryo Hazuki (Shenmue): https://www.moddb.com/mods/gta-iii-shenmue-ryo-hazuki-skin
- Ganondorf exists **only for San Andreas** (SA's skeleton is different, so these skins need converting to III/VC): https://www.gtainside.com/en/sanandreas/skins/169001-ganondorf-3ds/download/ and https://www.gtainside.com/en/sanandreas/skins/114752-super-smash-bros-brawl-ganondorf/
- Leon (RE4 Remake) also exists only for SA: https://www.gtaall.com/gta-san-andreas/skins/214911-resident-evil-4-remake-demo-leon-kennedy.html

### LCS (PS2): built into gBox (`gbox/gta_stories_models.py`, 2026-10-07)

Status: **works on the PS2 USA disc (SLUS-21423)**. gBox identifies the player, extracts him, and builds a disc-image mod that puts any rigged collection character in his place. It was checked in game on the Spark with HUcast: walking, running, getting into a car, driving and getting out, with no crash. Frames are in `gbox-cache/lcs_re/frames/` on the Spark. VCS and the PSP versions are not done (see "What's left").

The only third-party code used is aap's open-source librwgta `tools/storiesconv` (rsl.h, rslconv.cpp, leedsgta.h). It was read as a format reference and isn't shipped or run. Every struct offset below was checked against the disc.

**Files on the disc**
- `MODELS/GTA3PS2.IMG` (46 MB) holds all non-map models and TXDs. There is one copy, and there is no `.DIR` file.
- The directory lives in `CHK/PS2/GAME.DTZ`. That file is zlib-compressed and holds a relocatable `GTAG` chunk, the ResourceImage.
  - Offset `0x20+0x18`: numModelInfos (4118).
  - Offset `+0x1C`: the modelInfo pointers. CBaseModelInfo has the hash at `+8`, the type at `+0x10` (7 = ped) and the TXD slot at `+0x1E`.
  - Offset `+0x40`: the TXD pool. Items are `{texlist*, refs, name[20]}`.
  - Offset `+0x5C`: CStreaming. `ms_aInfoForModel[6175]` starts at `+4`, 20 bytes per entry. Each entry has the 2 KB sector position at `+12` and the sector count at `+16`. TXD slot k is entry 4900+k.
- Model names are hashes: CRC32 of the upper-cased name, without the final xor (`gta_key`).
- The player is model 0 and is a **special model**. Its streaming size is 0, and it's loaded by name from the special-model directory. That directory is in GAME.DTZ, at CStreaming `+0x1E328`. It has 160 entries of 32 bytes each: `{u32 sector, u32 sectors, "name\0mdl"}`.
  - Toni's outfits are `player` (sector 23, 41 sectors, unused by the story) and `plr`..`plr16`. The story **starts in `plr3`** (the traveller outfit), not `player.mdl`.
  - Each outfit has a TXD with the same name. If there is none, the game falls back to "generic".
  - `csplr*` and `csplayer*` are the cutscene Toni models.

**Relocatable chunk** (`.mdl` ident `ldm\0`, `.chk` ident `xet\0`, GTAG)
- The header is `{ident, shrink, fileSize, dataSize, relocTab, numRelocs, globalTab, u16 numClasses, u16 numFuncs}`.
- Pointers are file offsets. `relocTab` lists the file offsets of the pointer slots.
- Strings, such as a material's texture name, can sit after the reloc table.

**Ped `.mdl` layout**
- Data starts at `0x20`: `{CColModel*, RslElementGroup*}`.
- Each RslNode is 0xAC bytes: object, objectList, modelling and LTM 4x4 matrices, child, next, root, `nodeId` at `+0x9C`, `RslTAnimTree*` at `+0xA0`, `name*` at `+0xA4`.
- The skeleton is 24 hierarchy bones in this order: Root, Pelvis, Spine, Spine1, Neck, Head, the L clavicle/upper arm/forearm/hand/finger, the R side the same, L Thigh/Calf/Foot/Toe0, R the same. Bind is a T-pose, Z up, facing +X, left arm along +Y.
- The RslTAnimTree is 92 bytes in LCS. Its node info is `{s8 id, s8 index, s8 flags PUSH=2/POP=1, RslNode*}`. Skin bone i is hierarchy node i.
- There is one RslElement of 0x30 bytes. Its geometry is at `+0x14` and its hierarchy at `+0x2C`. The RslGeometry is 0x20 bytes: matList, then `RslSkin*` at `+0x18`. RslSkin is `{numBones, …, invMatrices*}`.
- sPs2Geometry follows (0x40 bytes):
  - `size` = numMeshes<<20 | block bytes.
  - `flags` 0x17 = positions, normals, UVs and skin.
  - numVerts and dmaOffset.
  - A bounding box as ±s16 extents in quantised space.
  - `scale` (powers of two, e.g. 0.25 / 1 / 1) and `pos`.
- Next come the 0x30-byte mesh headers. Each has a sphere, uvScale (1, 1), an "unknown" field (-8 for body materials, 20 for the head and hands material), `dmaPacket`, numTriangles (= strip vertices - 2), matID, and the s16 min/max of its vertices.
- Each mesh is one triangle strip in a DMA packet. The packet starts with a RET tag (qwc), then has batches of up to 42 vertices that overlap by 2. Each batch is:
  - `UNPACK V4-32 1 @0` (GIF tag; nloop = vertex count)
  - `STMASK 0x40404040`, `STROW 0`, `UNPACK V3-16 @1` for positions: `s16/32767.5*scale+pos`
  - `STMASK 0x50505050`, `STROW 0,0,0xFF,0`, `UNPACK V2-8 unsigned @0x55` for UVs: `u8/127.5`
  - `UNPACK V3-8 @0x2B` for normals: `s8/128`
  - `UNPACK V4-32 @0x7F` for skin: 4 floats per vertex, with the low byte = bone index × 4
  - `MSCAL 6`
- The ped renderer **doesn't cull**: the game's own strips mix both windings.
- `player.mdl`'s second material has a null texture name. The game fills it with the TXD's other texture at run time (Toni's head, `toni_head128_X_8bit`).

**Texture list `.chk`**
- RslTexList (24 bytes), then RslTexture `{raster*, dict*, link, name[32], mask[32]}`, then RslRasterPS2 `{data*, flags}`.
- flags = logw | logh<<6 | depth<<12 | mips<<20 | swizzle-mask<<24.
- The data holds all mip levels, then the palette. 8-bit levels whose swizzle bit is set are stored PSMT8-swizzled (`gta_rw._swz8_map`), and their palette is in CSM1 order. 4-bit levels are nibbles. Palette alpha 0x80 means opaque.
- Toni's TXDs are 8-bit with 5 mips (128²/256²). Some outfits use 4-bit 64² textures.

**Ghidra** (gBox `ghidra_script DecompileAll` on SLUS_214.23, processor `MIPS:LE:64:64-32addr`, `gp:0x3D6EF0`)
- Notes:
  - The Spark had no arm64 Ghidra decompiler. I built one from Ghidra's bundled source into `Ghidra/Features/Decompiler/os/linux_arm_64/`.
  - `gp` was derived from `RequestSpecialModel`'s gp-relative loads, and is confirmed by `gp+0x2DC4 = 0x3D9CB4`.
- Addresses:
  - `FindPlayerPed` = `0x107368`. It returns `*(CWorld::Players 0x408E40 + PlayerInFocus)`, where PlayerInFocus is a pre-scaled offset at `0x3D9BC8`. It has 162 callers.
  - The CPed fields: the CEntity modelIndex is a s16 at `+0x58`, the position at `+0x30`, the vehicle at `+0x534`, and in-vehicle at `+0x538`. These were checked live.
  - `CStreaming::RequestSpecialModel(id, name, flags)` = `0x18FF80`. It calls:
    - `GetUppercaseKey` 0x1838D8 (the hash)
    - `CBaseModelInfo::SetModelName` 0x1B7C80 (the hash at +8)
    - `RemoveModel` 0x18C428
    - `CDirectory::FindItem` 0x1450D8 on `*(CStreaming**)0x3D0CC8 + 0x1E328`
    - `SetTexDictionary` 0x1B7B18 (the model's name, else "generic")
    - `RequestModel` 0x18B400
  - `CModelInfo::ms_modelInfoPtrs` = `*0x3D8720`. numModelInfos = `0x3D9BA0`.
  - The intro movies are played by `0x1F3728`, which calls `jal 0x35A020` four times (at 0x1F3744, 0x1F3758, 0x1F376C, 0x1F3780).
- So, to identify the player: `FindPlayerPed()` gives the modelIndex (0), and `ms_modelInfoPtrs[0]->hash` gives the outfit name. Example: hash `0x5B6B0525` = `plr3`, giving "You are playing as Toni Cipriani, outfit plr3 (traveller), driving".

**What gBox does**
- `characters op=extract character=Toni game=Liberty City Stories` uses the DEDICATED `gta_lcs` route. It reads `plr3.mdl` and its TXD from the disc and writes a skinned 24-bone .glb with textures and body roles. The result is collection entry `lcs_toni` (1472 triangles, 2 textures, preview checked).
- `characters op=use character=<any> session_id=<LCS session>|game_id=002b9dca58a18ea1`:
  1. It identifies the player from the session.
  2. It builds `lcs_<slug>` on the Spark. Every outfit (player, plr..plr16) is replaced: the character is retargeted onto Toni's skeleton by body roles (`re4gc_enemies.retarget`, a numpy port of `scripts/retarget_rigid.py`). Vertices are rigid, with one bone at weight 1. The bone count, order, hierarchy, skin matrices and collision are kept, so all animations drive it.
  3. Textures are packed into each outfit's own texture slots, with the same sizes, depths and mips.
  4. The .mdl geometry block is rewritten and the file relocated. Every outfit must fit its IMG slot: largest first, with Blender decimation when a slot is smaller.
  5. The CHD is unpacked once with chdman. The new files are written into a copy of the ISO under `gbox-cache/mods/<game>/lcs_<slug>/`.
  6. It launches the mod on the requesting session's node.
- Sizes: HUcast fits every outfit untouched (974 triangles, about 60 KB per .mdl). A Melee fighter (around 6000 triangles) is decimated. The smallest slot, the mascot outfit `plr9` (33 sectors with 4-bit 64² textures), holds about 690 triangles.

**What's left**
- Cutscenes still show Toni. They use the `csplr*`/`csplayer*` models, which have more bones (face) and weren't retargeted.
- VCS needs:
  - a port of the reader and writer: RslNode has no node ids, RslRasterPS2 has 2 more words, and ResourceImage and CStreaming differ (see leedsgta.h)
  - Vic's outfit list
  - the same Ghidra pass
- PSP needs sPspGeometry vertex formats instead of the VIF batches.
- Skinning is rigid, one bone per vertex. Smooth weights from skinned sources aren't carried over.
- The Spark's arm64 pcsx2_libretro hangs LCS (at the intro movies and the loading bar) with the EE recompiler. It runs with `pcsx2_ee_cpu = Interpreter` and `pcsx2_renderer = paraLLEl-GS` (GL shows black frames). Both are set in the Spark's retroarch `core-options.cfg`. With them the game runs at about a third of full speed.

---

## 4. Resident Evil

### RE4 (2005): PC UHD (Steam) is the practical target
- Player model files are `pl*.udas`/`.lfs` (the Leon variants are `pl00`/`pl08`, etc.) and contain `.bin` (mesh) and `.tpl` (materials).
- Tools: **JADERLINK RE4-UHD-BIN-TPL-TOOLS** (extract and repack BIN/TPL to and from OBJ/SMD and MTL, open source): https://github.com/JADERLINK/RE4-UHD-BIN-TPL-TOOLS. Older Importer/Exporter Toolset: https://residentevilmodding.boards.net/thread/2486/re4-model-importer-exporter-toolset. RE4UHD Mod Installer (model swapping with backups): https://www.moddb.com/games/resident-evil-4/downloads/re4uhd-mod-installer-now-supports-model-swapping. PS2 BIN converter: https://residentevilmodding.boards.net/thread/17490/re4-ps2-model-converter-tool
- Rig: the SMD must keep **Leon's bone list and order**, because animations are external and index-based. Blender can do the SMD round trip with the Source Tools addon.
- Existing swaps: Ashley/2B and others replacing Leon: https://www.nexusmods.com/residentevil4/mods/98 (2B replaces Leon), https://residentevilmodding.boards.net/thread/15222/resident-evil-uhd-replace-leon. Modding board: https://residentevilmodding.boards.net/board/68/re4-uhd-model-modification
- The well-known **Mario/Luigi mod is for the RE4 *Remake* (2023)**, not 2005: https://gamerant.com/resident-evil-4-mod-mario-and-luigi/. I found no ready Mario or Sonic mod for 2005 UHD.
- GC/PS2: the BIN formats are similar. The PS2 converter exists, but rebuilding the ISO adds friction. Target UHD PC.
- Feasibility: **Medium.** The pipeline is fully file-based and the tools are CLI-ish (.bat-driven). That is good for automation.

### RE1/2/3 classic (PC; PS1/DC)
- Formats: RE2 uses `.EMD/.PLD/.PLW` with TIM textures, RE3 uses `.PLD/.PLW`, RE1 uses `.EMD/.TMD`. Models are **rigid per-part** meshes (~15 parts) with fixed animation in the file.
- Tools: **RE2MV** (view and edit PLD/EMD/PLW, OBJ/MD1 export and replace): https://residentevilmods.fandom.com/wiki/RE2MV and https://lgt.createaforum.com/tools-23/re2mv-a-tool-to-viewedit-3d-models/. **RE3MV**: https://lgt.createaforum.com/tools-24/re3mv-a-tool-to-edit-pld-files/. **Resident Evil Classic Toolkit** (OBJ import/export, EMD/PLD replacement): https://www.moddb.com/mods/resident-evil-classic-toolkit/downloads/resident-evil-classic-toolkit-v1-1-0-beta-setup-x64. Blender scripts (Blender Evil, PmData): https://www.tapatalk.com/groups/residentevil123/tool-blender-evil-t3228.html. Classic REbirth for mod loading: https://www.tapatalk.com/groups/residentevil123/resident-evil-classic-rebirth-t3175.html. Model swap tutorial: https://residentevilmodding.boards.net/thread/10087/updated-model-swap-tutorial
- I found no existing Mario or Sonic player mods for RE1/2/3.
- Feasibility: **Hard.** The low-poly, per-part fit and palette-limited TIM textures need an artist's eye. These are mostly GUI tools.

---

## 5. Mario Kart 64

- **Drivers are pre-rendered sprites**, not 3D models. "Ganondorf as my driver" means rendering a 3D Ganondorf sitting in a kart from every angle and animation frame.
- **SpaghettiKart** (Harbour Masters PC port) supports custom characters as `.o2r` mods that **replace** an existing racer, not add one. The Kart Setup `.blend` (from the Overkart server) has an armature: you replace Mario's mesh, weight it, and render the animation at a power-of-two size (64/128/256). **Racer Ready-Up** (Godot tool by VinieVex) packages the result and makes the nameplate. Then you zip it to `.o2r` and put it in `mods/`. Docs: https://harbourmasters.github.io/SpaghettiKart/md_docs_2custom-characters.html (the GitHub copy 404'd while I was fetching), modding: https://github.com/HarbourMasters/SpaghettiKart/blob/main/docs/modding.md, tool: https://vinievex.itch.io/racer-ready-up, example mod: https://gamebanana.com/mods/606351
- ROM route: decomp (https://github.com/SpeedRunTooked/mk64-decompile and mirrors) and MK64 Pitstop/tools: https://hack64.net/wiki/doku.php?id=mario_kart_64:hacking_tools. Custom-driver ROM hacks exist (Link, Sonic and others shown at https://www.deviantart.com/mk64-customdrivers). MK64 Recompiled lists model replacements as *planned*: https://github.com/SilverCard/MarioKart64Recomp
- **No ready Ganondorf kart mod found.**
- **Obstacle**: no data-only route. You'd have to write a new actor (or reskin an existing one, such as the Piranha Plant, Thwomp or train) in decomp C or a SpaghettiKart code fork. Reskinning an existing obstacle's texture or sprite is **Medium**. A new collidable actor is **Hard**.
- Feasibility: driver **Medium** (and very automatable). Obstacle reskin **Medium**. New obstacle **Hard**.

---

## 6. Source asset extraction

| Character | Source | Tool | Output |
|---|---|---|---|
| Ganondorf (OoT) | OoT ROM `object_gnd`/`object_ganon` | Z64Utils (https://github.com/zeldaret/Z64Utils), or OoT decomp + Fast64 | OBJ/DAE or `.blend`, rigid limbs |
| Mario (SM64) | SM64 decomp `actors/mario` | Fast64 import (https://github.com/Fast-64/fast64), Fast64's bundled `mario.blend` | `.blend` with armature |
| Sonic (SA2 PC) | `sonicmdl.prs` etc. | SA Tools SAMDL (https://github.com/X-Hax/sa_tools/wiki/SAMDL) and SAIO Blender addon (https://x-hax.github.io/SonicAdventureBlenderIO/about/) | `.sa2mdl`, then Blender (rigged, with animations) |
| Ryo (Shenmue I&II PC) | `.MT5` parts (body YKB_M, face, hands) | yazgoo MT5 tools / DAE converter (https://www.shenmuedojo.net/forum/viewtopic.php?t=47275, https://zenhax.com/viewtopic.php@t=3386.html) | Partial. The parts have to be assembled. **Hardest source.** |
| Leon (RE4 UHD) | `pl00/pl08.udas` | JADERLINK BIN/TPL tools | SMD/OBJ |

Shortcut: for GTA the Mario, Sonic and Ryo skins already exist, so no extraction is needed.

---

## 7. What gBox can automate end-to-end

| Step | Automatable? | Notes |
|---|---|---|
| (1) Export source model | **Mostly yes.** Fast64 import (SM64/OoT decomp), SAIO (SA2), JADERLINK CLI (RE4) and Z64Utils (CLI is limited, GUI-first) can all run headless in Blender with `bpy`. | Shenmue MT5 is a manual job. |
| (2) Retarget/rig to the target skeleton | **Partly.** A `bpy` script can import the target skeleton, scale the source to fit, parent mesh parts to the nearest bone by name map or proximity, and transfer weights from a template body (Data Transfer modifier). This works for *rigid-limb* targets (OoT, GTA III/VC, RE classic, PSO) when you supply a **hand-written bone map per source-to-target pair**. | **A human artist is needed** for proportion fitting (Ganondorf on a Booma, Mario on Leon), fixing deformation, equipment display lists (OoT) and the visual QA. |
| (3) Convert to target format | **Yes** where an exporter exists: Fast64 (OoT/SoH), zzplayas (CLI-capable), DragonFF (`.dff`), pso-blender (`.xj`, experimental), SMD to JADERLINK (RE4), SpaghettiKart sprite render (Blender `--background -a`). | gBox writes LCS PS2 `.mdl`/`.chk` itself (gbox/gta_stories_models.py); the RE classic tools are GUI-only, and DC `.nj` export is unreliable. |
| (4) Inject | **Yes.** Copy `.o2r` into a mods folder (SoH/SpaghettiKart), replace IMG entries (GTA), repack `.bml` (PSOBMLExtract), copy `.udas` (RE4), apply zzplayas to a ROM. All of these are file operations and fit the planned mod-builder (staging, `file_mutation` permission, rollback). | Back up the originals. Only patch ROMs and installs the operator owns. |

Realistic first automations, ranked:
1. **Install a ready-made mod** (SoH Ganondorf `.o2r`, GTA VC Mario/Sonic skin). This is pure file staging and needs no AI-generated art.
2. **GTA VC "replace all peds"** with one existing skin. Script it: copy one dff/txd over every ped IMG entry, or rewrite `default.ide`.
3. **SpaghettiKart driver** from any rigged model: `bpy` swaps the mesh in the Kart Setup `.blend`, auto-weights it, renders the frames, zips the result as `.o2r`. You get a recognisable result with no manual work, because sprite rendering hides weight errors at 64px.
4. **SoH/ML64 player model** from a decomp-exported model, using the template blend with an artist pass.
5. RE4 UHD Leon replacement, then the PSO Booma retarget, then RE classic (each needs a lot of artist work).

Integration note: `docs/blender-bridge.md` (headless `blender --background`) and `docs/mod-builder.md` (staging and rollback, Phase 8) are the hooks for steps 2–4. Blender isn't installed on the build host yet. The Blender addons needed are Fast64, DragonFF, SAIO, pso-blender and Source Tools (SMD).

---

## 8. Metal Arms: Glitch in the System (GameCube): built into gBox (`gbox/metal_arms.py`, 2026-10-07)

Status: **works on the USA disc (GM5E7D, catalog `7e103ec3aab47fa2`)**. gBox identifies the player (Glitch, or the bot he's possessing) and the bots on screen, extracts any of them with skeleton and textures, and builds disc-image mods that put a collection character in Glitch's place or in a bot's place (picked by screen point). Checked in game on the Spark (Dolphin): Cloud as Glitch walking, running, strafing, jumping and shooting; Sonic in place of the Droid Miners (both walking near the start of Droid Mines / Hero Training). Frames are in `gbox-cache/ma_re/frames/` on the Spark. Glitch himself also went the other way: `characters op=use character=glitch` in RE4 GameCube (`re4_glitch`) was played in The Mercenaries (walk, run, aim, shoot).

No third-party code or spec was used. Everything below comes from Ghidra on `main.dol` and from the data. There's no public format documentation for Swingin' Ape's engine (its own name, "Fang", is in the master file magic).

**Files on the disc**
- 210 FST files. Nearly everything is in `mettlearms_gc.mst` (358 MB), the master file. It's the **last file on a full 1.36 GB disc**, and the files inside are packed back to back, so a file can't grow. Every replacement must fit its old slot (the writer decimates until it does).
- Master file: magic `GNAF` ("FANG" little-endian), then big-endian: `+0x08` file size, `+0x0C` entry count (12048). Entries from `0x6C`, 36 bytes each: `{char name[20], u32 offset, u32 size, u32 mtime, u32 crc}`. The game doesn't check the crc. The writer updates the size.
- Extensions: `.ape` meshes (2231), `.tga` textures (6237, GameCube texture data despite the name), `.mtx` animations, `.csv` tables, `.wld` worlds, `.fpr` particles, `.sma` scripts, `.gt`, `.rdg/.sfb` sounds, `.cam`, `.fnt`.
- Name scheme: `gr<d|m|z><x><name><nn>.ape` for in-game bots (`d` droid, `m` Mil, `z` zombie, then a class letter), `gc*` for the cutscene versions, `t<same>.tga` for their textures. Glitch is `grdggltch00` (+ `grdggltch01`, a variant some levels load; `grdggltchmp` multiplayer; `gcdggltch00/01` cutscenes, texture `trdggltchh0` at 1024²). The Mil Grunt is `grmggrunt00` and the Droid Miner `grdmminer00`.

**.ape (FMesh)**: every pointer is a file offset. The loader's fixup is `0x8029DB68` (called by the MESH resource create, `0x802A63D4`), and it lists every pointer slot, which is what lets the writer move blocks.
- `0x00` name[16], `0x10` bound sphere, `0x20` bbox. `0x3C` u8 count of the bone-sphere table, `0x3E` u8 bones, `0x40` u8 segments, `0x44` u8 materials, `0x45` u8 collision trees. `0x4C` 7 LOD distances.
- `0x68` bone spheres (24 bytes: sphere, u8, u8 bone). `0x6C` bones (0x138 bytes): name[32], then four 4x4 row-vector matrices (bone-to-model = the bind pose, model-to-bone, parent-to-bone, bone-to-parent), a sphere, u8 parent (0xFF = root), u8 child count, u8 first child in the skeleton byte list at `0x74`. `0x70` lights. `0x78` materials. `0x7C` collision trees (0x44 bytes, inner pointers at `+8` (an array of 16-byte records with 2 pointers), `+0x10`, `+0x40`). `0x80` segments. `0x84` the GameCube mesh: `{mesh*, sphere, +0x15 u8 VB count, +0x18 VBs*, +0x1C extra*}`.
- Material (0x48 bytes): `+0` shader registers*, `+4` texture-layer pointer list (a layer record has the u32 3 at `+0x10` and its texture name's file offset at `+0x18`), `+8` u8 shader, `+0xC` u32 part mask, `+0x10` → `{packets*, u16 count}`, `+0x16` u8 texcoord sets.
- VB (0x1C bytes): u32 position count, u8 position type (1 S8 / 3 S16), u8 index type (3 = 16-bit), u8 stride, u8 fraction bits, u16 colour count, u8 colour index type, **u8 vertex format (VAT)**, then the position*, colour* (RGBA8; RGB is 0 and only alpha is used) and texcoord* (2 × S16, 8 fraction bits) arrays. VATs 4/5/6 are preset to S8 positions with 7/6/5 fraction bits. **VAT 7 is set up from the VB** (type and fraction bits) by the packet drawer `0x802EBD48`. The writer uses it for S16 positions.
- Packet (0x18 bytes): u8 flags (0x80 = the display list is in streaming storage), **u8 bone**, **u8 LOD**, u8 part bit, u16 ?, u16 list triangles, u16 strips, u8 1, u8 VB, u32 display-list size, u32 display list*, RGBA. Each packet is drawn with its one bone's matrix, so models are **rigid**, with positions in the bone's space. The material loop `0x802A4920` draws the packets whose LOD matches the one picked by distance and whose part bit is set in the instance mask (instance `+0xCC`). So a bot needs packets for every LOD it has (miners have 3, Grunts 4, Glitch only LOD 0).
- Display lists are GX `0x9x` triangles / `0x98+` strips. Each vertex is `{u16 position, u16 normal, u8 colour, u16 texcoord × n}`. The normal is an index into the **engine's global table of 32800 S8 normals (6 fraction bits)**, built at boot. Its pointer is at `0x804B90F4`. gBox dumped it from RAM once to `gbox/metal_arms_normals.bin` (zlib). Front faces are clockwise against the stored normals.
- Axes: Y up, the model faces +Z and its left is −X (left-handed). glTF export mirrors X.

**.tga (texture)**: a 0x20-byte header: name[16], `+0x14` u8 format, `+0x17` u8 mip count, `+0x1C/+0x1E` u16 width/height. The format table is at `0x803DDAB0`. Format 7 is CMPR colour followed by a second CMPR mip chain that `0x802B72EC` binds as a second texture object. For Glitch it's the reflection/specular mask (the writer fills it with a low constant). Format 6 is plain CMPR. The texture resource create is `0x802B7D14` → `0x802B7474`.

**Ghidra** (gBox `DecompileAll` on `main.dol` converted with `gcdisc.dol_to_elf`)
- Processor: `PowerPC:BE:32:default`. Ghidra's stock PowerPC has no Gekko paired-single instructions, so the handful of functions that use them decompile only partly. No loader extension was installed.
- SDA bases: `r13 = 0x804BABE0`, `r2 = 0x804C2420` (from `__init_registers`). They're passed with the new `reg:<name>:<hex>` option of `adapters/ghidra/DecompileAll.java`.
- The decompilation (10800 functions) is in `gbox-data/analysis/metal_arms_gc_main_decomp.c` on the Spark.
- Addresses:
  - Master file name `0x803B3A80` (set by `0x80218038`). The MESH type is registered by `0x802A3624` (`"MESH"`/`"ape"`), TXTR by `0x802B6EDC`.
  - Player update `0x801C9B20`, called with `Player_aPlayer` = **`0x80481AF8`** (0x24C8 bytes each). `+0x18D8` is the player's own bot, **`+0x18DC` the entity he controls now** (Glitch can possess bots).
  - Entity: `+0x40` position, `+0x13C` flags (bit 0 = bot), `+0x1B8` CFWorldMesh*.
  - CFWorldMesh: vtable **`0x803D5354`**, `+0x10` owner entity, `+0x3C` bound radius + centre, `+0x60` mesh instance, whose `+0` is the FMesh* (the loaded .ape, name at `+0`). The instance matrix is at `+0x10`.
  - Camera-to-world (3 axis rows + position): `0x804A2DE0`. Horizontal half-FOV ≈ tan⁻¹ 0.70. It projects bots to within a few pixels of where they're drawn.
  - The strings `grdggltch00`/`GRDGgltchMP` in the DOL (`0x803A204F`) are how the Glitch bot class names its meshes. Other bots get theirs from the `.csv` bot tables.

**What gBox does**
- `characters op=extract character=<Glitch|Mil Grunt|Droid Miner|Krunk|Zobby|Exavolt|Titan> game=Metal Arms` (DEDICATED `metal_arms` route) reads the `.ape` and its textures from the disc. It writes a glTF with the full skeleton (Glitch: 107 bones), rigid weights, textures, and body roles mapped by bone name. Collection entries: `glitch` (3127 tris), `ma_grunt`, `ma_miner`, `ma_krunk`, `ma_zobby`, `ma_titan`.
- Glitch's roles: pelvis Groin, hip Waist, chest Torso, neck Neck, head Head, L_Arm_Upper/L_Arm_Lower/L_Hand, R_Shoulder/R_Arm_Lower/Off_R_Hand_Dummy, L/R_Leg_Upper, L/R_Knee, L/R_Foot_Back. Oddities: Glitch is a robot with very short thighs (Leg_Upper → Knee, 0.26 units) and long shins (Knee → Foot_Back, 1.24). His forearms point forward in the bind pose. His right forearm is a gun arm with no hand bone, so r_hand is the gun-attach dummy that rides the forearm.
- `identify(session)`: Player[0] → controlled entity → world mesh → .ape name. For example, "You are playing as Glitch (grdggltch00.ape)", or "possessing a Mil Grunt".
- `bots_on_screen(session)` scans the heap (`0x80600000–0x81000000`) for the CFWorldMesh vtable and projects each bot's sphere centre with the game camera. It takes about 50 s over the GDB stub. `bot_at(x, y)` picks the nearest.
- `characters op=use character=<any> game_id=7e103ec3aab47fa2` (slot player) builds `ma_<slug>`:
  1. The character is retargeted onto Glitch's skeleton by body roles (`re4gc_enemies.retarget`, with the new optional `fit_shoulders` that widens the torso to meet Glitch's wide shoulders).
  2. Normals are oriented away from each part, because library models disagree on what's outside: FF7 models are inside-out and Melee winds against its normals. Each triangle's winding follows its normals.
  3. Positions go in bone space as S16 via VAT 7, with the nearest table normals. There's one display list per bone (strips that keep the winding) and a packet per LOD.
  4. Textures are atlased into the bot's own texture slot (same size, format and mips).
  5. The character is decimated until every file fits its slot.
  6. The image is a copy of the disc with the files rewritten in place inside the .mst (`filemods.build_image`), with its own image name.
- Glitch's two story files and two cutscene files are written in pairs that share a texture (`trdggltch00`, `trdggltchh0`). Sizes: 194880 / 193824 bytes for play, about 173 KB for cutscenes. Cloud fits at about 2000 tris and HUcast/Mario/Aya untouched. Melee fighters and Leon are capped at 3000 tris (about 96% full).
- `slot=npc session_id=… x=… y=…` builds `ma_<slug>_<ape>` for the bot drawn at that point (that bot type everywhere, plus numbered variants that share its texture). It's drawn with the bot's first textured material: Droid Miner → `trdmminery3`, 128².

**What's left**
- The NPC writer puts the atlas in the bot's first textured material's texture. That texture can be small (miner: 128²), and other meshes can share it: `trdmminery3` is also used by `gcdmminer02`, `grdmgrenade` and `grdmhead_01`, which get scrambled textures. Bots with alternate skins (miners' `h` materials) draw only the replaced material.
- Cutscene bots (`gcd*`) aren't replaced by the NPC route. Glitch's cutscene files are.
- An NPC mod and a player mod are separate disc images. There's no combined build yet.
- Skinning is rigid, one bone per triangle.
- There's no live hot swap into RAM. Every change is a reboot of the disc image. Booting to gameplay takes about 5 minutes, because the opening movie can't be skipped.
- The second catalog entry "Metal Arms: Glitch in the System (USA)" (`e3053b5165af24a0`, windows_native) is the **PS2 disc**, `collections/Sony Playstation 2/roms/USA/... .chd`. The catalog merged it with the HyperSpin *Microsoft XBOX* collection, which has Metal Arms artwork but no Xbox image, so it took that system's platform rule (windows_native). There's no PC version. The PS2/Xbox formats aren't handled.

---

## 9. AKI wrestling (N64): WWF No Mercy built into gBox (`gbox/aki_wrestling.py`, 2026-10-07)

Status: **works on WWF No Mercy (USA) (Rev A)** (NW4E 1.1, catalog `23a346e48b6368a6`). gBox identifies who is in each slot, extracts any default wrestler into the collection (rigged, textured, previewed), and builds ROM mods that put any rigged collection character in place of one or more wrestlers. Checked in game on the Spark in a private headless RetroArch (parallel_n64): Cloud wrestling Triple H (grapples, strikes, the Buster Sword riding the hand); Mario (Melee) in The Rock's slot in a four-way and against Peach (Melee) in Trish Stratus's slot: suplex, slam, more than a minute without a crash. Frames are in `/home/ehm_eckx/gbox-cache/aki_re/frames/` on the Spark (`f1_sheet.png`, `mf_sheet.png`, `pf_sheet.png`, `mp_tr1.png`, `mod_cloud_austin.png`). WCW World Tour USA and WCW/nWo Revenge USA now have native writers in `gbox.aki_wcw`. SmackDown! 2 USA has a native disc writer in `gbox.yukes_sd`. The reverse-engineering notes below describe the earlier investigation.

References (read only, no code copied or run; their licences are recorded in `LICENSES-THIRD-PARTY.md`): AKI-Club's **VPW Studio** (MIT) and **akifiletable / akiarc** (Unlicense) for the file table, the Asmik LZSS, the AkiModel / Ci4 / Ci8 layouts, the per-game ROM offsets and the file-id database. Everything the writer relies on was checked against the ROM and in Ghidra.

**Formats**
- FileTable: one u32 per file, `offset from FirstFile | 1` when compressed. File id k (1-based) spans entries k-1 .. k. A raw file's size is the next entry minus this one; a compressed file's size is its 4-byte header (`00` + 24-bit length). No Mercy NW4E 1.1: FirstFile `0x1BD150`, table `0x16C31D8`, ids 1..`0x4C02`.
- Asmik LZSS: 4 KB ring starting at `0xFEE`, flag byte LSB first (1 = literal), a match is `pos(12) len(4)+3`. gBox has both directions (`lzss`, `lzss_store`, greedy, about the size of AKI's own).
- AkiModel: `{u8 scale, u8 nverts | 0x80 (the colour bytes are normals), u8 nfaces, u8 influence, s8 off x/y/z, u8 tex size = w/8 << 4 | h/8}`, then nverts × `{s8 x y z, u8 u v (texels), s8 nx ny nz}`, then nfaces × 3 u8 indices (CCW, like glTF).
- **A vertex's rest-space position is (x, y, z) + 16 × off.** All parts of a wrestler share one rest frame: arms down, facing +Z, his left = +X, feet at about y = -100, head top at about +90. The engine poses each part with its own matrix (F3DEX2 `G_MOVEMEM 0x0E`, a forced MVP) about its joint. Dividing two parts' matrices cancels the projection and leaves a rigid transform, so the skeleton can be read from any frame.
- Ci8 texture: `{w-1, h-1, u16 colours, mirror s, mirror t, log2 w, log2 h}` + w×h indices. Palette: 256 × RGBA5551. Body parts are 64×32 or 32×64, hands 32×16.
- 11 body classes × 20 parts (`[Body Parts] (Skinny) Chest Front` ... in the VPW Studio database): pelvis L/R, waist front/back, chest front/back, upper/lower arm, hand, fingers, upper/lower leg, foot per side. Plus the face model, the back of the head, the hair and a common neck. A whole body is 609 vertices / 669 faces, a full wrestler about 700 / 800.

**Ghidra** (gBox `DecompileAll` on a 4 MB RDRAM image taken at Superstar Select, `MIPS:BE:32:default`, base `0x80000000`, `entry:0x80000400 jalscan`; the boot segment is ROM `0x1000` → RAM `0x80000400`, linear up to `0x80056400`)
- `0x80003ab0` loads the file table: `malloc(0x1300C)`, DMA from ROM `0x16C31D8`, then precomputes every file's size into a second buffer (`malloc(0x13008)`, loop `< 0x4C02`). `0x80003bd0` resolves a file id (it hangs in a loop for ids outside 1..`0x4C02`).
- `0x80018a3c (costume, partlist)` builds a wrestler's part list from his unpacked costume. The part list is 0x270 bytes per slot at `0x800A8980`. Its 24 entries `{u16 model, u16 texture, u16 palette, u8 skin, u8 x}` sit at `+0x08..+0xC0`, then the attire layers (`+0xE0..+0x24F`), which are composited into each part's CI8 texture at load. Body type → class `0x80048A48`, class → model row `0x80048A78`, body type → skin row `0x80048AA4` / `0x80048AD4` (texture = palette + 1), row position → part entry `0x8004FD28`.
- `0x800148f0 (slot, costume, ...)` calls it at `0x8001495C`. `0x80015d8c` loads the parts; parts `+0xB0..+0xC0` are loaded without a zero check, and an empty finger entry hangs the game too.
- The roster: wrestler number n's four costume records are `0x4E` bytes each at `*(0x80047E90) + 0x138 × n` (the packed costume is at `+0x31`). Default costumes in file id 1, 38 bytes each, 4 per wrestler; field 29 = face number. Face texture = `u16 0x8004D254[face] + 1`. It is unique per roster wrestler, so it identifies him.
- Wrestler number in slot s: `s16 0x80076264 + 2s`. Wrestler objects: `0x800A11FC + 0xB24 × s` (position floats at `+4`).

**The writer** (no file is overwritten; data goes at the end of the ROM)
1. The character is retargeted onto the replaced wrestler's own body type in rest space (`sm64_swap.retarget` with an AKI joint map; joints come from the seams between parts). It is cut into the 24 parts: torso by height, then front/back and left/right halves like the game's parts. The head goes into face + back of the head.
2. Each part is decimated in Blender (`scripts/decimate_parts_gltf.py`, one object per part with its own budget). It gets a cylindrical UV map around its long axis, so UVs are continuous and the engine counts few duplicated vertices. Its texture is re-baked by sampling the nearest point of the source surface.
3. **Budgets found by testing:**
   - Each part may be no bigger than the game's own part: the per-wrestler vertex/face pools hold about 700 / 800. The largest models anywhere in the game have 63 vertices / 85 faces.
   - Parts that share a skin texture in the game share one baked texture: the composited textures live in a fixed buffer.
   - There is one 256-colour palette per character.
   - Every body part must exist: a speck triangle stands in for an empty one.
   - New files are LZSS-compressed: the part loader goes through a staging buffer.
4. **ROM layout:**
   - The new files go after the last id. A spacer id keeps file `0x4C02`'s size intact.
   - The table moves to the end of the ROM with a 27-instruction MIPS hook and the part-list templates behind it.
   - Boot-segment patches (each checked against the original instruction): the table no longer goes into the heap but into `0x80700000` (Expansion Pak RAM, which the game never touches), with the new DMA size, the size buffer, the loop count and the id bound.
   - `jal 0x80018a3c` at `0x8001495C` becomes `jal hook`. The hook calls the original function, then compares the part list's face texture (`+0xA2`) with each template's key and copies that template (0x250 bytes: all 24 parts, no attire layers) over the part list.
   - The CIC-6102 CRC is recomputed.
5. The skeleton, animations, moves, grapples and hit boxes are the game's own. Every costume of the replaced wrestler shows the character, on Superstar Select, entrances and in the ring.

**What gBox does**
- `characters op=use character=<any> game_id=23a346e48b6368a6 [slot=<wrestler name or number>]` builds `nomercy_<character>_as_<wrestler>` on the Spark and launches it. Without a slot, it uses player 1's wrestler in the session (from RAM), else The Rock. Cloud as The Rock is 620 triangles; Mario 503; Peach 573.
- `characters op=match game_id=... pairs=[{character, slot}, ...] title="..."` puts several characters in one ROM. Example: `nomercy_mario_vs_peach`, card title "Mario vs Princess Peach", Mario = The Rock, Peach = Trish Stratus. Both are pickable on Superstar Select (page 1 / LADIES) and keep those wrestlers' move sets.
- `characters op=extract character=<wrestler> game_id=...`, by name:
  - The `nomercy` DEDICATED extractor boots the original ROM in a **private headless RetroArch** (`aki_wrestling.PrivateN64`: its own Xvfb display and UDP port, never a gBox session).
  - It reaches Superstar Select, copies that wrestler's costume records over The Rock's, re-hovers, and reads the frame: part list + the composited CI8 textures from the display list. This takes about 65 s.
  - The result is a rest-pose skinned glTF: 19 joints with body roles hip/chest/neck/head, clavicle-less arms, legs. It is the same frame every other gBox writer retargets from.
- With a running No Mercy session, `op=extract session_id=... [x, y]` takes the wrestler at that picture point (part boxes projected with their MVP matrices from the display list), or by name, or player 1.
- `aki_wrestling.identify(read, rom)` / `slots_on_screen(ram, rom)` answer "who's on screen": the wrestler in each slot (by face texture; a gBox mod's templates map the character back to the wrestler it replaced) and each slot's picture box. Checked on a four-way match frame of the Mario vs Peach mod (Mario found as The Rock, top left).
- Starter set in the collection: `nm_the_rock`, `nm_steve_austin`, `nm_undertaker`, `nm_mankind`, `nm_kane` (all with attire, previews checked).
- **Cross-game:**
  - `nm_the_rock` in RE4 GameCube (`re4_nm_the_rock`) was played on the Spark: story opening, then The Mercenaries Village (mission start, aiming, firing, fighting Ganados). Frames: `/home/ehm_eckx/gbox-cache/aki_re/frames/re4_19.png`, `re4_20.png`, `re4_merc_sheet2.png`, `re4_merc_sheet3.png`.
  - Ocarina of Time (`oot_nmsteveaustin`) and Metal Arms (`ma_nm_undertaker`) builds succeed. They were not booted.

**What's left**
- **Revenge / World Tour writer.** The reader (file table, LZSS, models) is shared.
  - Revenge NW2E: FirstFile `0xDAC50`, table `0xCE2752`.
  - World Tour NWNE 1.1: FirstFile `0x39500`, table `0x7C1C70`.
  - Their costume definitions list each part's palette/texture directly, and a body table of 52 pointers to 17 model ids (`0x800310A0..`, ROM `0x31CA0..`). So the same moved-table trick, plus a repointed body entry and costume entry, would replace a wrestler without a hook. It wasn't built.
- **Revenge (NW2E), Ghidra on a menu RDRAM image:**
  - `0x800034a0` loads the table: `malloc(0x77A8)`, DMA from ROM `0xCE2752`, sizes loop `< 0x1DE9`. `0x800035b4` / `0x80003684` resolve ids, with the bound `0x1DE9`. The moved-table patch ports one to one.
  - `0x8000bdd0 (slot)` loads a wrestler's parts:
    - wrestler code `0x8006A2A4[slot]` → group `(code >> 6) & 0x7C`, member `(code & 0x1F) - 1`;
    - costume set `0x80031998[group][member] & 0x7F` → `0x800360F0[set]` → pointer per costume number (`0x8007DFBC[slot]`) → its first u16 `& 0x7F` = body index → body definition `0x800317F0[index]` (17 model ids; slot → field `0x80031088`);
    - head definitions `0x80032B44[group][member][0x8007DFB0[slot]]`.
  - A Revenge writer = these pointers repointed into the moved-table payload (new body / head / costume records with new file ids). Not built.
- **WWF WrestleMania 2000** (N64, AKI, catalog `4dbec1a56fefe363` / `fe76dc7ec4acfd50`) is in the library too. It is No Mercy's direct predecessor (VPW Studio covers it). Not attempted.
- **Not AKI** (no reader in gBox; each needs its own format work and a Ghidra pass):
  - WWF SmackDown! 1/2 (PS1, Yuke's);
  - SmackDown vs. Raw 2006-2011 (PSP, Yuke's, PPSSPP);
  - SvR 2008-2010 (DS).
  - The PS2 SmackDown! Shut Your Mouth / Here Comes the Pain / SvR aren't in the library.
  - The library's "pro wrestling" matches are Japanese/retro titles (Fire Pro, Toukon Retsuden, Giant Gram, Power Move Pro Wrestling...). There's no Virtual Pro Wrestling entry.
- No Mercy Europe (`2e8850a2a6c53375`) and other revisions: offsets differ. The patcher refuses any ROM whose instructions don't match.
- The hook's key is the face texture. Wrestlers who share a face (Cactus Jack / Mick Foley) are replaced together.
- Saves: a cart save that already holds edited wrestlers overrides the default costumes, but the hook still matches by face. The CAW (create-a-wrestler) slots aren't covered.
- Rigid skinning, one joint per part. The seams open slightly on big bends (waist/chest).
- Real hardware needs the Expansion Pak (the table lives at `0x80700000`).

## 10. Parasite Eve (PS1): any character as Aya, built into gBox (`gbox/pe_swap.py`, 2026-10-07)

Status: **works, checked in game on the Spark** (pcsx_rearmed, headless). Mario played as Aya in the opening street
cutscene, the opera entrance and the lobby and hall, walking. Mod `pe_mario`, card "Parasite Eve: Mario as Aya".

- `characters op=use character=<name> game="Parasite Eve"` builds `pe_<slug>` (a raw `.bin/.cue` copy of the disc) and
  launches it. It works on Disc 1 and Disc 2, which share a byte-identical PE.IMG.
- **Slot:** Aya's real-time model, all 5 outfits (PE.IMG common blobs 18..22 hold model + animations, blobs 13..17 hold
  the VRAM textures). Field and battle use the same model. FMVs are pre-rendered and still show Aya.
- **Retarget:** Aya's rest pose (frame 0 of her lowest animation) gives the target skeleton. `pe_swap.OUTFIT_BONES` maps
  body roles to bones for each outfit, and the head's bulk decides left/right. The generic rigid retarget is
  `sm64_swap.retarget`, with `fit_height`: the whole figure is scaled to 0.9 x Aya's height, not to her head joint.
  Bone count, traversal list and bounding spheres stay Aya's, so her animations play.
- **Budgets:** these are Aya's own. Model bytes must fit her model's slot in the blob (the blob keeps its sectors).
  Vertices must not exceed hers, and GPU packet bytes (GT3 0x50, GT4 0x68) must not exceed hers. If the model is over,
  Blender decimates it. Mario ends up at 600 to 750 triangles per outfit.
- **Textures:** the 256x256 4-bit page at VRAM (960,256) with 32 CLUT slots (rows 448/449). Each texture gets its own
  15-colour CLUT, and flat colours become 4x4 cells. The blob's own three VRAM uploads are refilled at the same size.
- **Disc:** the PE.IMG sectors of the 10 blobs are rewritten in place. EDC/ECC is recomputed (`gbox/psxdisc.py`
  `RawBin`, `fix_sector`; checked against mastered sectors).
- **Collection:** the extractor now reads all 5 outfits with correct roles: `aya`, `aya_evening_dress`,
  `aya_long_coat`, `aya_tshirt_jeans`, `aya_liberated`.

## 11. Final Fantasy VII (PS1): any character as Cloud, field + battle, built into gBox (`gbox/ff7_swap.py`, 2026-10-07)

Status: **works, checked in game on the Spark**. Mario walked in the Sector 1 station with Barret and fought the first MP
battle (attacking with the Buster Sword). Mod `ff7_mario`, card "FF7: Mario as Cloud".

- `characters op=use character=<name> game="Final Fantasy VII"` builds `ff7_<slug>` for Disc 1, 2 or 3.
- **Field model** `FIELD/CLOUD.BCX`. The format was reverse-engineered here and is documented in
  `gbox/ff7_models.py` `read_field_model`: 22 bones, 15 parts, Gouraud polygons with a per-vertex lighting normal index.
  The normal table is FIELD.BIN, gunzipped, at 0x3F520, 240 entries.
  - **Budget:** FIELD.BIN's file table loads exactly 7072 bytes for this file, so the LZS stream must not grow
    (gBox has its own LZS encoder). The decompressed file stays at or under Cloud's size, with 255 vertices or polygons
    per part and GPU packets no larger than Cloud's.
  - **Result:** about 430 triangles, as quads where two triangles share an edge.
  - 10 special-scene BSX files (e.g. CLSIN2_1, LAS4_4) carry their own copy of Cloud's mesh and are not patched.
- **Battle model** `ENEMY6/CLOUD.LZS`. Section 0 (skeleton + meshes) is rebuilt as Gouraud triangles and quads.
  Animations, settings, the TIM and the weapons (the Buster Sword) are copied unchanged. The compressed size must not
  exceed the original 66694 bytes. Mario keeps all 752 triangles.
- **Textures:** baked into per-corner colours, since the PS1 field and battle bodies are Gouraud.
- **Rip side:** `read_field_model` + `field_to_gltf` extract every party field model, and `ff7_swap.field_spec` derives
  body roles from the skeleton topology. In the collection: `ff7_cloud_field`, `ff7_tifa_field`, `ff7_ballet_field`
  (Barret), `ff7_earith_field` (Aerith), `ff7_red_field`, `ff7_cid_field`, `ff7_vincent_field`. `ff7_yufi_field` and
  `ff7_ketcy_field` are ripped without roles because their layout doesn't match.
  The battle models of the other party members can be extracted but have no automatic roles yet.

## 12. Coverage matrix

`characters op=coverage` (`gbox/char_coverage.py`) returns, for each game gBox has studied (games with a writer, games
the collection came from, games this document discusses), three things: whether it can **rip** the game's characters
(extractor → collection), whether it can **reimport** any collection character into it (a swap writer that
`characters op=use` actually routes to), and which slots. A game with no writer answers `op=use` with the overlay
fallback: if the game is running, the character is drawn over the player in the desktop app right away. It also files
a **gap report** (inbox source `gap`, title "GAP: character writer for <game>") so the writer gets built.

Snapshot 2026-10-07: 33 games, 20 with an extractor, 19 with a routed writer, 15 with both; 80 collection characters.

| Game | Platform | Rip (extractor) | In the collection | Reimport (writer, slots) |
|---|---|---|---|---|
| Final Fantasy VII (Discs 1-3) | psx | ff7 (battle LZS + field BCX) | cloud (+2 variants), ff7_tifa, 9 field models (7 with roles); not ripped: battle models of Barret, Aerith, Red XIII, Cid, Yuffie, Vincent, Cait Sith (no auto roles yet) | **gbox.ff7_swap**: player (Cloud field + battle) |
| Parasite Eve (Discs 1-2) | psx | parasite_eve | aya + all 4 other outfits | **gbox.pe_swap**: player (Aya, all outfits) |
| Super Mario 64 (USA / Europe) | n64 | sm64 | mario | **gbox.sm64_swap**: player |
| Resident Evil 4 (GC, Discs 1-2) / Wii Edition | gamecube / wii | re4gc | leon | **build_re4 (+ re4wii)**: player (+ enemies via re4gc_enemies by hand) |
| Resident Evil 6 | xbox360 | re6_models | re6_leon, re6_helena | **gbox.re6_tool**: player, enemies, enemy:<family> |
| Legend of Zelda: Ocarina of Time | n64 | oot_swap | oot_link_child, oot_link_adult, oot_km1, oot_kw1 | **gbox.oot_swap**: Link (both ages), any NPC, swap, place |
| Metal Arms: Glitch in the System | gamecube | metal_arms | glitch, ma_grunt, ma_krunk, ma_miner, ma_titan, ma_zobby; not ripped: Exavolt | **gbox.metal_arms**: player, npc, enemy |
| WWF No Mercy (USA; EU Rev A reader) / WCW Revenge / World Tour | n64 | nomercy | nm_kane, nm_mankind, nm_steve_austin, nm_the_rock, nm_undertaker; not ripped: the rest of the roster | **gbox.aki_wrestling**: any wrestler, player |
| GTA: Liberty City Stories | ps2 | gta_lcs | lcs_toni, toni_cipriani; not ripped: the other Toni outfits | **gbox.gta_stories_models**: player (every outfit) |
| Sonic Adventure 2 | dreamcast | sa2 | sonic, sa2_shadow, sa2_tails, sa2_knuckles, sa2_rouge, sa2_dr_eggman, sa2_amy_rose, sa2_metal_sonic, sa2_tikal, sa2_chaos_0 | **gbox.sa2_chars**: player (Sonic; section 13) |
| Phantasy Star Online Ver. 2 | dreamcast | pso | hucast; not ripped: the other 8 classes | overlay only (gbox.pso_player builds the files, the game doesn't draw them yet: section 14) |
| Super Smash Bros. Melee | gamecube | melee | 27 fighters | overlay only |
| Shenmue (Disc 1) | dreamcast | shenmue | ryo | overlay only |
| Resident Evil 4 (2023, Steam) | pc | re4r | re4r_leon, re4r_ashley (no roles) | overlay only |
| RE Director's Cut, RE3 Nemesis, Parasite Eve II, FF8, GTA III, GTA VCS, RE4 PS2, Mario Kart 64, Mercenaries 3D | various | - | - | overlay only (gap report on first op=use) |

Regenerate it with `characters op=coverage`: `char_coverage.markdown()` prints this table from the live data. A new
writer counts as soon as its module has `GAME_IDS` + `use()`, is listed in `char_coverage.WRITERS`, and
`characters_tool` routes to it.


## 13. Sonic Adventure 2 (Dreamcast): any character as Sonic, built into gBox (`gbox/sa2_chars.py`, `gbox/ninja_swap.py`, 2026-10-07)

Status: **works on Sonic Adventure 2 (USA) DC** (catalog `d95ed7ed1e40552a`). `characters op=use character=<any> game_id=d95ed7ed1e40552a`
builds `sa2_<slug>` on the Spark: a copy of the GD-ROM image (GDI, unchanged tracks hard-linked) with Sonic's model and
textures replaced. Checked on the Spark (Flycast): RE6 Leon (`sa2_re6_leon`, 649 triangles) through the Hero story's City
Escape, on the board and running on foot, Sonic's motions driving him.

**Files**: `SONIC2/SONICMDL.PRS` (PRS) holds a table `{s32 id, u32 offset}` ending at id -1; pointers inside are file
offsets. Id 0 is Sonic's full 62-node tree; most other ids (1-30: upper body, hands, shoes, ...) point INTO that tree,
and 31 / 48 are lower-detail copies (each with their own sub-ids). `SONICTEX.PRS` is a PVM of 11 textures.
Both files are packed back to back on a full GD-ROM: **each must fit its old sectors** (39 / 29).

**What the writer does** (`sa2_chars.build_swap`):
1. Retarget onto Sonic's bind pose (`ninja_swap.fit` → `sm64_swap.retarget`, roles = node indices; the head goes on
   node 44, the head bone, because 47 / 49 below it are head variants the game may hide), decimate in Blender until it fits.
2. Per node, rigid geometry: chunk vertices 0x29 (position + normal) in the node's space, strips 0x41 (greedy
   stripify), the body's own material + texture flags, double-sided.
3. **The game needs Sonic's original vertex chunks**: with them removed it hangs loading a stage (bisected on the
   Spark: emptying the strips is fine, emptying the vertex lists hangs). So every node keeps its vertex chunks and the
   character's vertices follow them from a cache slot past the highest original one; only the strips are replaced.
4. The LOD trees 31 / 48 and all their sub-ids are repointed to the same node of the main tree (same node order), which
   frees their bytes; new data goes into freed holes first (best fit), so the file barely grows.
5. Textures: one 256 px atlas (`re6_models._pack`), VQ-compressed (`ninja.pvr_vq`, k-means codebook) into texture 5
   (`sonic_soapshoes`, the biggest, only used by the replaced models).
6. PRS: `ninja.prs_compress` (optimal parse; ~0.5 % bigger than SEGA's own). GD-ROM: `gdrom.patch_gdi` rewrites the
   files in place, updates the ISO9660 size, recomputes EDC/ECC (checked against real sectors).

**Not covered**: Sonic's spin ball / board / Light Dash parts (separate ids, still Sonic), cutscene (event) models, 2P
and alternate costumes (`HSONIC*`, `XSONIC*`, `PSOSONIC*`), the other playable characters' slots. The model budget
is low (~650 triangles) because the original vertex chunks must stay. The GameCube version (SA2 Battle) isn't done.

Shared pieces: `gbox/ninja.py` now writes Ninja data too (PRS, VQ / small-VQ / twiddled PVRs, PVM entries, chunk
vertex + strip lists with a base slot, NJS_OBJECT trees, POF0); `gbox/gdrom.py` patches GDI images (`patch_gdi`;
moved files can only go into a donor file's sectors: Flycast crashes reading past the last file).

## 14. Phantasy Star Online Ver. 2 (Dreamcast): player class writer, NOT working yet (`gbox/pso_player.py`, 2026-10-07)

The operator's character is **GBOX, a HUmar** (class A; read from the memory card screen), not the HUcast in the
collection. `pso_player.build_swap` writes the HUmar (or HUcast) body: `PSO/PL<x>BDY00.NJ` (loose, NJCM + POF0) and
the same file inside `PSO/PL<x>NJ.BML` (repacked, PRS), every head / hair / cap file as an invisible speck, and the
atlas into all 97 textures of `PL<x>TEX.AFS` in each texture's own size and format (VQ, small VQ, twiddled).
Findings from the Spark (offline mode only, never online):
- In game (Pioneer 2) the **loose** `.NJ` files are drawn; the memory card / character screens use them too.
- With the body's weighted vertex chunks replaced by rigid ones the game draws garbage (menu preview) — same engine
  rule as SA2. Keeping the original chunks makes the body ~60 KB, far over its 11 sectors; a bigger body file
  (moved to a donor file's sectors or past the last file) makes Flycast drop the content or draws nothing.
- So `characters op=use` for PSO answers `not_working` instead of building. What's needed: find the game's buffer limit
  for the body file / why it needs the weighted chunks (Ghidra on 1ST_READ.BIN: the player model loader), or write the
  character as weighted chunks in the original slots (0x2C vertices with Ninja-flag weights), keeping the original
  vertex counts per chunk.

## 15. RE6 Leon (`re6_leon`) in other games, and fixes found on the way (2026-10-07)

Mods (all built on the Spark, mod cards with game frames): RE4 GC `re4_re6_leon` (story opening: walk, run, aim),
SM64 `sm64_re6_leon` (castle grounds), OoT `oot_re6leon` (child in Link's house, adult in the Fire Temple / Death
Mountain Crater, climbing), SA2 DC `sa2_re6_leon` (City Escape, section 13). PSO: section 14 (not working).
- **RE6 extractor bone order** (`re6_models.Mod.decode`): in the 4-bone vertex formats (0x14D4..., 0x6459...) the four
  u8 bone indices are stored last-to-first (b[3] goes with weight 0). Reading them in order put almost every body vertex
  on the chest (thighs, upper arms: 0 vertices), so every rigid retarget left the sleeves in a T-pose. `re6_leon` was
  re-exported (vertices now sit next to their bones); `re6_helena` was not (its arc names didn't resolve: re-export
  it before using it). Untextured RE6 materials (Leon's earpiece) now export dark grey instead of glTF white.
- **RE4 GC build loop** (`characters.build_re4`): the last decimation (20 %) was written but never tried; a 17k-triangle
  source failed with "decimating didn't help". RE6 Leon fits at ~3400 triangles with 64 px textures.
- **SM64 / OoT material keys** (`sm64_swap.to_writer`, `oot_swap.to_parts`, `oot_place`): materials were keyed by the
  texture array's `id()`, so a model whose primitives each decode their own copy of the same image (RE6: 84 materials,
  11 images) got one texture per primitive and the budget flattened 72 of them to colours (white patches in OoT).
  They're keyed by the image content now (OoT Leon: 9 textures, nothing flattened).
- SA2 characters (Sonic, Shadow, Tails, Knuckles, Rouge, Eggman, Amy, Cyclone) are built for RE4 GC, RE6 (on i9-NUC)
  and LCS PS2. Played: Shadow in RE4 (`re4_sa2_shadow`), Sonic and Shadow in LCS (`lcs_sonic`, `lcs_sa2_shadow`).
  RE6 `re6_sonic` / `re6_sa2_shadow` are built but not booted (cards say so). Shadow / Knuckles / Rouge got body roles
  from `characters.tree_roles` (same node layout as Sonic); the Cyclone's are hand-picked (mech legs 27-32, Tails in
  the cockpit: arms 7-18, head 24).


## Automatic collection and WCW / SmackDown completion (2026-10-08)

Successful game launches queue one `characters op=collect` job on the Linux collection worker for games with a registered native reader. No vision or LLM call is involved. Verified collection entries are reused. Each result lists verification, mapped rig readiness and individual failures; partial results and unsupported games are explicit. The extraction panel shows progress and offers **Collect entire roster** for an explicit retry. Jobs inherit the launch request, falling back to the operator request configured through `/api/character-collection/policy`. Automatic collection creates no new top-level inbox requests.

Native readers cover OoT (adult/child Link), Melee, Dreamcast SA2, FF7, Parasite Eve, PSO Ver.2, Shenmue, SM64, RE4 GameCube, GTA LCS PS2, RE4 Steam, No Mercy, SmackDown! 2, WCW World Tour, WCW/nWo Revenge and Metal Arms. This is a list of adapters, not a guarantee for every region/version or every NPC. Unsupported titles still require a reader. Frame-captured geometry is not presented as a rigged native extraction. Retargeting requires a supported target writer and stays within that game's geometry/texture limits. It does not change a running game at arbitrary times.

`characters op=use character=<slug> game=<catalog id> slot=<wrestler> launch=false` builds an actual replacement; `op=match pairs=[{character,slot}, ...]` builds several into one image. The native wrestling writers support No Mercy USA Rev A, World Tour USA Rev A, Revenge USA and SmackDown! 2 USA. Each replacement keeps the slot's animation and move set; existing selection portraits and names remain. Original game images are preserved. SmackDown! 1, PSP SvR and PS2 Shut Your Mouth / Here Comes the Pain remain separate writer work.

Revenge's extraction picker now reads its actual ROM roster, including hidden entries, rather than the World Tour list. Its CI4 textures can contain two palette banks; pixel depth is identified from the payload size and both banks are preserved when writing. WCW build work and target previews are separated by game ID. Concurrent target saves are serialized, and metadata uses a unique temporary file before atomic replacement.

Verification: SM64 launch triggered and completed collection; SA2 collected 12/12 mapped characters; OoT collected 2/2 Link models; All 45 World Tour, 92 Revenge and 66 SmackDown! 2 roster models passed model/texture/preview checks with mapped rigs. Sonic/Shadow multi-character native image builds passed for World Tour, Revenge and SmackDown! 2. UI checks cover canonical slug selection, collection results, explicit failure display and completion polling.

WCW player detection uses each ROM profile's slot address (World Tour `0x80057520`, Revenge `0x8006A2A4`). If the active wrestler cannot be identified, the tool asks for a named slot instead of silently replacing the first wrestler.

Native gameplay verification frames are stored as inbox attachments and artifacts: Revenge Shadow/Hogan wrestling Raven (`e9b2338628546fc19e1968fd9d5062dbed2c83b832a480e8abf94a187543eb74`), SmackDown! 2 Sonic/Rock wrestling Undertaker (`de141f9dee3efd4f6cebf098ce07550fc8aa48d9ad4f4bd2b56a0bd1ab71d385`). Completed implementation/validation sub-requests #757 and #758 are nested under operator request #753; the original WCW replacement gap #557 is complete. Universal live replacement #706 and unsupported title extraction/writers remain pending.
