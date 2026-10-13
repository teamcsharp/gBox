# Assimilation: what each title taught gBox, and how the next one starts

Each title gBox cracks should make the next one faster. This doc records what each landed title taught. The code
uses the same knowledge in three places:

- `gbox/assimilate_kb.py`: every title below as data (formats, engines, reader, techniques, documented files, magics
  and strings, effort).
- `gbox/assimilate.py`: the `assimilate` tool. `op=fingerprint game_id=...` ranks a new game's containers, codecs,
  model, texture and animation formats and its engine or middleware. It does this from magic bytes (file heads and
  inside the largest archives), extensions, executable strings and ELF symbols. It also names the nearest titles
  here and proposes the reader to start from, with a module skeleton.
  - It is step one of the local agent's RE playbooks (`study-title`, `asset-loader-format`, `assimilate-title`).
  - It is step one of Hermes's readiness inventory stage (`hermes/gbox/FAVORITE_WORK.md`).
  - `gbox/hermes_work_queue.py` attaches it to every new readiness ticket (`context.assimilation_fingerprint`).
- `gbox/formats/`: the shared low-level code that used to be copied per title. The table at the end shows what moved.

`gbox/re_seeds.py` turns the knowledge base into agent knowledge in two ways:

- It turns each title into `TITLE_FACTS`: its formats, its reader, and the techniques that cracked it, as documented
  facts in the title's dossier.
- It turns each technique into a playbook, with these titles as worked examples.

When a title is done, add it to `gbox/assimilate_kb.py` and to this doc. `assimilate op=evaluate` then reports
whether that changed the fingerprinter's accuracy.

## History and effort: read this first

The repository history starts on 2026-10-05. Bulk commit `a0a5d2b` (2026-10-07) imported a lot of work that was done
before git, as did `341ed24` and `5b10691`. For modules that first appear there, the real effort is **not visible**.
PR numbers below come from first-parent "Merge pull request #N" commits. A "#13xx" in a commit subject is an inbox
request, not a PR. PR #126 (`codex/assimilate-games`) is a bulk integration PR that carries many of the inventories.

## Techniques

Each technique has a playbook of the same id in `gbox/re_seeds.py`.

| id | what it is | where it cracked something |
|---|---|---|
| `symbols-first` | Use shipped symbol tables (ELF `.symtab`, debug strings) before anything else. | AUF Bond.elf (17,636 symbols), GTA III PS2 ELF, Clay Fighter debug names |
| `string-xref-loader` | Go from a file name or format string in the executable to its loader. | Crazy Taxi `polDC0.all`, Def Jam `data/data.bin`, Time Stalkers `%s\man%03d%02d.BIN`, Nightfire `Bondcombat skin must be loaded` |
| `instruction-pattern` | Find code by its instruction shape in every overlay or build (`gbox.formats.insn_pattern`). | MGS VR clear routine (91 overlays), AKI Revenge PAL patch sites, Nightfire lis/addi, DMC3 R5900 lui/addiu, SA1 SH-4 mov.l loads |
| `routine-oracle` | Run the game's own routine as ground truth (`gbox.formats.oracle`). | DOA++ BIOS decode, expander and skeleton on the R3000 interpreter; DOA2 cloth initialisers in Ghidra's emulator |
| `community-spec` | Start from a decomp, wiki or open tool, then prove it on the owned build. | Ninja SDK (PSO/SA), NaomiLib (DOA2), Qhimm (FF7), OpenBiohazard2 (RE2), librw/re3 (GTA), UE source, tengine source (Turok), HSDLib (Melee) |
| `magic-census` | Classify every file and archive member by its first bytes. | Illbleed, Sonic Shuffle, Mercenaries 3D, Warzone, CT2, DMC2/3 |
| `ram-capture` | Read the loaded object or structure from RAM (entity probe, save states). | AUF entity probe, SD2 rest pose, RE4/RE6 live maps, MGS VR save states |
| `frame-capture` | Use rendered frames as ground truth. | JGR pick-whip identity, AUF probe frames |
| `round-trip-proof` | Get byte-identical re-writes before any writer. | DOA2 (80 costumes), Def Jam (290/290 slots), PE2, MvC2 LZSS, DOA++ packer (327/327) |
| `welded-fit` | One welded mesh per chunk with per-vertex bones, inside the native budgets. | SmackDown 2 (#603), Crazy Taxi principal-axis fit |
| `decomp-reference` | Use a matching decompilation project as the map. | SM64, MK64, SF64, SSB64, OoT/MM, Perfect Dark |

## Dreamcast, NAOMI and ZN arcade

### Dead or Alive 2 (Dreamcast: JP LE, plus USA)

- **Modules:** about 30 `doa2_*` modules (`doa2_chars`, `doa2_geometry`, `doa2_textures`, `doa2_motion`, `doa2_rig`,
  `doa2_sup_*`, `doa2_swap`, ...) and `doa2usa_inventory`.
- **Docs:** `doa2_re_findings.md`, `doa2-moment-context.md`, `doa2_writer_linux_validation.md`.
- **Container:** GD-ROM ISO9660. `DOA2/*.CHR` is a NaomiLib model archive with a 24-byte header and absolute work-RAM
  pointers. Companion files: SUP seam/morph records and APV/ACS cloth companions.
- **Model:** NaomiLib meshes with 80-byte PVR material headers (PCW/ISP/TSP/TCW) and strips.
- **Texture:** headerless PVR in `*.BIN` (ARGB1555/RGB565/ARGB4444, twiddled, rectangular or VQ, mipmapped formats 2
  and 4).
- **Skeleton:** not in the CHR file. It is a 17-joint rest table in 1ST_READ (`0x8c1949a0`).
- **Animation:** MOT banks (compact44/mixed44/legacy26) with 44 IK channels, not bones.
- **How it was cracked:** `string-xref-loader` with Ghidra on the SH-4 1ST_READ (`FUN_8c0dcfe8/8c0dd826/8c0dd906`;
  the motion decoder `8c0e86c2`), plus `community-spec` (NaomiMod CHR_Format / NL-ModelFormat).
  - `routine-oracle`: all 93 cloth initialisers and generators were reproduced in Ghidra's emulator.
  - `ram-capture`: Flycast savestates for the RTT backdrop.
  - `round-trip-proof`: byte-exact CHR round trip on all 80 costumes, with live acceptance (Amy as Ein).
- **Effort:** 2026-10-10 to 2026-10-13, about 20 module commits. PRs #8 #16 #27 #126 #157 #168 #180 #205 #236 #251.
- **Reusable:**
  - Reuses `gdrom`, `ninja.pvr_decode`, `sm64_swap` (load_rig/retarget), `re4gc_enemies` and `melee_models.write_gltf`.
  - Feeds `anim_clips`, `cast_swap` and `characters`.
  - `doa2_textures` now uses the shared twiddle (`gbox.formats.texture`).

### Dead or Alive++ (Tecmo TPS / Sony ZN-1 arcade)

- **Modules:** `doapp_inventory`, `doapp_models`, `doapp_motion`, `doapp_chars`, `doapp_swap`, `zn_tps_boot` (R3000
  interpreter plus a CAT702 model) and `psx_gte` (GTE model).
- **Doc:** `doapp_pipeline.md`.
- **Container:** a MAME zip. The 0x2800000-byte bankedroms are seen through an 8 MiB window. The program is encoded
  behind the SCEI licence. FILE_TABLE is 280 x 12 bytes at RAM `0x800515a4`.
- **Model:** model files [49-102] are a 14-section container. Sections 3-10 and 12 are packed. Mesh marker 0x42,
  SVECTOR vertices, prebuilt GPU packets.
- **Texture:** standard PS1 TIM.
- **Skeleton:** built at run time by the game (`0x800a4848`: FK, 2-bone IK and chain physics).
- **Animation:** motion banks [27-37] hold IK bend tables and 12-bit rotation and 10-bit limb tracks.
- **How it was cracked:** `routine-oracle` throughout.
  - The BIOS's own decode runs on the interpreter ("nothing here re-implements that cipher"). The decode was checked by
    code density, the entry point, and the file table tiling the ROMs with no gaps.
  - The game's expander `0x8006c718` unpacks the models.
  - The motion decode was checked against the game's stepper state: 3045 motions, 285,347 frames, 0 mismatches.
  - The writer's `pack_mesh` is the expander's exact inverse (327/327 sections), and each build is read back through
    the game's own code.
- **Effort:** 2026-10-12 to 2026-10-13 (2 days), 11 module commits. PRs #126 #224 #242 #254.
- **Reusable:**
  - The interpreter-oracle pattern is now generic as `gbox.formats.oracle.RoutineOracle` / `check_inverse` /
    `check_reader`.
  - Reuses `sm64_swap`, `re4gc_enemies.decimate` and `characters.render_preview`.

### Phantasy Star Online (Ver.2 Dreamcast, Ep I&II GameCube)

- **Modules:** `ninja` (the shared Ninja codec), `ninja_swap`, `pso_player`, `pso_enemy`, `pso_gc`,
  `pso_gc_inventory`, `pso_inventory`, `pso_mods_tool`, `psoitems`, `psomap` and `psotext`.
- **Container:** BML archives (PRS'd), AFS texture banks, and on GameCube a GCZ disc.
- **Model:** NJCM Ninja chunk models with NJTL and POF0 (little-endian on DC, big-endian on GC).
- **Texture:** PVM/PVR (twiddled, VQ) on DC; GVM/GVR on GC.
- **Skeleton:** one 64-node tree for all nine classes.
- **Animation:** NJM/NMDM on DC. On GC, `PlyMotionData.rlc` ("RelChunkVer0.20", 572 motions).
- **How it was cracked:** `community-spec` (public Ninja SDK layouts, newserv for PRS/BML and player visual config).
  - Ghidra on PsoV3.dol for the GC loaders (`FUN_8001f018/8001f128/8001fcc4`).
  - SH-4 disassembly for the DC mods.
  - The texture layout was matched by drawing each texture's UV layout over the images.
  - Role maps for all nine classes were checked per skeleton (#1485).
- **Effort:** the core predates the history (a0a5d2b). Work on 2026-10-12 to 2026-10-13: about 15 commits.
  PRs #8 #126 #148 #163 #197 #200 #211 #219 #251.
- **Reusable:**
  - `ninja` is the most reused codec hub: SA1/SA2, JGR, DOA2 textures, Shenmue, Time Stalkers and Sonic Shuffle all
    use it.
  - Its PRS now lives in `gbox.formats.lz`, its twiddle in `gbox.formats.texture`, and its decode/encode roles are
    indexed in `gbox.formats.ninja_chunk`.
  - `pso_player.check_roles` became `gbox.formats.rig.check_role_map`.

### Sonic Adventure 2 and Sonic Adventure (Dreamcast; SA2B on GameCube)

- **Modules:** `sa2_chars`, `sa2_inventory`, `sa2_mods`, `sa1_inventory` and `sa1_analysis`.
- **Doc:** `sa2_mods.md`.
- **SA2 formats:**
  - Container: `SONIC2/<CHAR>MDL.PRS` (PRS, then an {id, NJS_OBJECT offset} table).
  - Model: NJCM with weighted vertices.
  - Texture: `<CHAR>TEX.PRS` (PVM).
  - Animation: `<CHAR>MTN.PRS` (NJS_MOTION).
- **SA1 formats:** basic NJS_OBJECT/NJS_MODEL trees embedded in 1ST_READ.BIN; textures are PRS'd PVMs.
- **How it was cracked:**
  - `instruction-pattern`: SA1 follows SH-4 `mov.l @(disp,PC)` loads of each texlist to its object tree (#1324).
  - `sa2_mods` is anchored on published CodeBreaker codes, with X-Hax SA2Variables as a naming guide.
- **Effort:**
  - `sa2_chars` predates the history.
  - SA1: 2026-10-11 to 2026-10-12. SA2 inventory: 2026-10-12 (#1499). Mods: PR #217.
  - PRs #126 #206 #222.
- **Reusable:** `ninja` and `ninja_swap`. `sa2_inventory` reuses `sa1_inventory.classify`.

### Jet Grind Radio (USA, Dreamcast)

- **Modules:** `jgr` and `jgr_swap`.
- **Docs:** `jgr_pipeline.md`, `jgr_re_findings.md`.
- **Container:** `JETRADIO/PLAYER.AFS` and `ENEMY.AFS` (CRI AFS).
- **Model:** PLAY containers: a Ninja chunk node tree without the NJCM wrapper, plus the native character id. Bodies
  share a 20-node skeleton.
- **Texture:** PTEX (PVR VQ and mipmapped VQ).
- **Cel-shading outline:** an inverted hull. Strips are flagged NJD_FST_IL, sit 0.08-0.13 units outside the body, and
  have reversed normals.
- **How it was cracked:**
  - `magic-census` of the AFS members.
  - `string-xref-loader` / code xref: the 1ST_READ id lookup at `0x8c0c7f74`, plus debug labels at `0x8c10df40`.
  - Statistical geometry analysis for the outline: median dot -1.00 against the nearest body normal.
  - `frame-capture` (pick-whip frames #1150/#1153/#1156).
- **Effort:** 2026-10-11 to 2026-10-13, 10 commits. PRs #8 #126 #226 #251.
- **Reusable:** `jgr.afs_entries` is reused by `pj_inventory`. The `gbox.assimilate` engine readers point at it for
  CRI AFS.

### Time Stalkers, Sonic Shuffle and Illbleed (Dreamcast Ninja inventories)

- **Time Stalkers** (`time_stalkers`):
  - Formats: Climax LANDERS. `MANcccbb.BIN` holds the skeleton and motions (0x30-byte nodes, 128-slot motion
    table). `OBJnnn.BIN` / `.pvm` hold Ninja chunk geometry and textures.
  - Technique: `string-xref-loader` on the MAIN.BIN format strings, plus a signature-float scan.
  - Effort: 3 commits, 2026-10-11 to 2026-10-12 (#1316).
- **Sonic Shuffle** (`sshuffle_inventory`):
  - Formats: `.MDL` flat container (PVM, NJCM, NMDM, NJSL).
  - Technique: the 1ST_READ name order, confirmed by each file's PVM texture names.
  - Effort: 2 commits (#1390), PRs #144 #126.
- **Illbleed** (`illbleed_inventory`):
  - Formats: `AMAZON/*.NJ` (NJTL plus a POF0/NJCM/GBIX/PVRT chunk stream), `.NT`, `.AFS`, `.PMC` (CGAM motion).
  - Technique: `magic-census` with an exact chunk walk.
  - Effort: 2 commits, PR #161.
- **Reusable:** all three are inventory stage only. None calls `ninja` yet, even where the files are NJCM. The
  fingerprinter now proposes `gbox.formats.ninja_chunk` for them.

### Crazy Taxi 2, Marvel vs. Capcom 2, Shenmue and NFL 2K2 (Dreamcast)

- **Crazy Taxi 2** (`crazy_taxi2`):
  - Formats: DiscJuggler CDI. `POL*.BIN` are NaomiLib objects (TA parameter words, strips).
  - Technique: a structural walk of 35 files to an exact end (103,625 triangles).
  - Effort: #1482.
- **MvC2** (`mvc2_inventory`, `mvc2_dat`, `mvc2_chars`):
  - Formats: the PLxx_DAT section table holds LZSS-compressed 4bpp twiddled parts, ARGB4444 palettes, cells and
    hitboxes.
  - Technique: SH-4 disassembly; the LZSS codec is byte-exact with the game's `loc_8c0354c0`.
  - Effort: 4 commits (#1315), PRs #126 #175.
- **Shenmue** (`shenmue_mt5`):
  - Formats: `.PKS`/`.PKF` (gzip; PAKS/IPAC, PAKF/TEXN), MT5/HRCM models with negative-index limb welding.
  - Technique: `community-spec`.
  - Effort: predates the history.
- **NFL 2K2** (`nfl2k2_inventory`, `nfl2k2_analysis`):
  - Formats: Visual Concepts IFF (SCNE/SPRT/VQCB) and gdFs .DIR/.DAT.
  - Technique: header-invariant analysis.
  - Status: probe stage. PRs #126 #153.

## GameCube and Wii

### Crazy Taxi (GameCube)

- **Modules:** `crazy_taxi` and `crazy_taxi_swap`.
- **Doc:** `crazy_taxi_swap.md`.
- **Container:** the GC FST, plus `ct/polDC0.all`, a shape bank of 1586 records {name[64], size}.
- **Model:** `.shp` big-endian GX models (s16 positions/normals, RGBA8 colours, display lists).
- **Skeleton:** 15 rigid bone-local parts.
- **Animation:** `ct/motDC.bin` holds 278 motions of Hermite keys (root plus IK targets).
- **How it was cracked:**
  - `string-xref-loader`: main.dol lis/addi xrefs to `polDC0.all`/`motDC.bin`.
  - Known-shape oracle: `cube0.shp`, 36 triangle corners at +-1.
  - `welded-fit`-style principal-axis donor fit.
- **Effort:** 2026-10-11 to 2026-10-13, 10 commits. PRs #126 #225 #251.
- **Reusable:** `gcdisc` (now `gbox.formats.gcfst`) and `characters.rig_from_gltf`.

### 007: Agent Under Fire (GameCube)

- **Modules:** `au_inventory`, `auf_ngc`, `auf_ngc_writer`, `entity_probe` (generic) and `gcz`.
- **Doc:** `auf-entity-analysis.md`.
- **Container:** a GCZ disc, BIGF `.viv` files, and `maps/*.ngc` (32-byte-aligned chunks with byte-reversed ids such as
  `restable`).
- **Codec:** BOA LZ77.
- **Model, skeleton, texture:** `.gcm` NGC skinned geometry with skeleton and matrix palette; textures from the
  `restxtrs`/`shaders` chunks.
- **Animation:** `.gca`.
- **How it was cracked:**
  - `symbols-first`: Bond.elf keeps `.symtab` (17,636 CodeWarrior symbols). Every layout cites a named function
    (`RSRC_Load` 0x80016AFC, `ReadChunkData` 0x80010A7C, `NGCObject3D::FixupModelData`).
  - `ram-capture` and `frame-capture` for the entity probe (RAM dumps with byte-identical frames).
- **Effort:** 2026-10-12, 9 commits. PRs #126 #195 #203 #204.
- **Reusable:**
  - `entity_probe` is profile-driven and title-independent.
  - `auf_ngc` reuses `gta_rw.write_skinned_glb`.
  - The fingerprinter reads ELF symbols for exactly this case.

### 007: Nightfire (GameCube, Eurocom)

- **Modules:** `nightfire_inventory`, `nightfire_edl`, `nightfire_analysis` and `nightfire_model`.
- **Container:** the GC FST, `gc/<hash>.bin` (`%s%8.8x.bin`), hash packs and BIGF.
- **Codec:** EDL method 1 (Huffman plus LZ77). All 31 levels decode.
- **Skeleton:** HT_Skin (73 bones, 60 attachments).
- **Model:** type-2 objects with GX texture chunks. The vertex reader is still a probe.
- **How it was cracked:**
  - Nightfire.elf is stripped, so `instruction-pattern` (a capstone scan of lis/addi and bl xrefs) was
    cross-checked against headless Ghidra (4754 functions).
  - The EDL decompressor was rebuilt from `0x80067c24`.
  - `string-xref-loader` via "Bondcombat skin must be loaded".
- **Effort:** 2026-10-12, 6 commits. PRs #129 #207.
- **Reusable:** `gcdisc`. Nothing outside Nightfire uses it yet.

### Def Jam Vendetta (GameCube) and Resident Evil 4 (GameCube)

- **Def Jam GC** (`defjam_vendetta`):
  - Formats: `.gpl` meshes (magic `00 B7 49 E0`, GX display lists) and `.tpl` textures. `.skn`/`.act`/`.anx` are not
    decoded.
  - PR #129.
- **RE4 GC** (`re4gc_models`, `re4gc_enemies`, `re4gc_inventory`):
  - Formats: UDAS `.drs`, DAT packs, BIN meshes and TPL (CMPR decoded and encoded).
  - Technique: verified live on Dolphin. Models predate the history; inventory #1387 / PR #140.
  - Reusable: `re4gc_enemies.retarget`/`decimate` is the shared rigid retargeter for about 20 writers. Its
    `_role_of_joint` is now `gbox.formats.rig.role_of_joint`.

### Metal Arms (GameCube) and Super Smash Bros. Melee (GameCube)

- **Metal Arms** (`metal_arms`, `model_swaps.md` section 8):
  - Formats: GNAF `.mst` master file, `.ape` FMesh with pointer fixups, `.tga` in platform formats.
  - Technique: `string-xref-loader` / Ghidra (the MESH/TXTR resource registrations).
  - Effort: predates the history.
- **Melee** (`melee_models`):
  - Formats: HAL HSD `.dat` (JObj/DObj/MObj/TObj).
  - Technique: `community-spec` (HSDLib).
  - Reusable: `write_gltf` is used by about 11 writers.

## PS1

### WWF SmackDown! 2: Know Your Role (Yuke's)

- **Modules:** `yukes_sd`, `sd2_analysis` and `sd2_inventory`.
- **Container:** DPAC directories (ED1H/ED1B/ED1L.PAC), PAC entries, BPE packing.
- **Model:** EMD (32 bone records, 8 variant slots, chunks of at most 128 vertices).
- **Texture:** TIM 8bpp.
- **Skeleton:** 31 bones, shared by every wrestler.
- **Animation:** M.PAC (MOT), inventoried only.
- **How it was cracked:**
  - `ram-capture`: the rest pose came from the skeleton array during a match.
  - `instruction-pattern`: jal call sites and lui/ori constants re-derive the loader pins.
  - `welded-fit`: one welded mesh per chunk with per-vertex bones replaced the per-bone shells, which had left 270 open
    boundary edges (#603, FIT_VERSION 2).
- **Effort:** predates the history, then 2026-10-12 to 2026-10-13. PRs #126 #131 #239 #251.
- **Reusable:**
  - Its TIM parse/build is now `gbox.formats.texture.tim_parse/tim_build`.
  - It reuses `psxdisc.RawBin` and the `aki_wrestling` bake/decimate helpers.

### Parasite Eve II and Parasite Eve

- **PE2** (`pe2_inventory`, `pe2_models`, `pe2_swap`; `pe2_pipeline.md`):
  - Container: STAGE0.HED index over STAGE0.CDF chunk chains (LZ with a 256-byte ring).
  - Model: absolute-pointer model at `0x80115770`, 0x24-byte bones, lit GT3/GT4.
  - Texture: 8-bit pages and CLUT rows.
  - Technique: `instruction-pattern` (capstone on SLUS_010.42) and `round-trip-proof`.
  - Effort: 4 commits, 2026-10-12, PR #231.
- **PE1** (`parasite_eve`, `pe_swap`):
  - Formats: PE.IMG packages, 0x1C-header models, 8/16-bit rotation tracks.
  - Technique: Ghidra on SLUS_006.62.
  - Effort: predates the history.
  - Reusable: `pe_swap.base_bin` is reused by FF7 and PE2.

### Final Fantasy VII

- **Modules:** `ff7_models` and `ff7_swap`; `model_swaps.md` section 11.
- **Container and codec:** `ENEMY6/*.LZS` (Okumura LZSS) and FIELD BCX.
- **Animation:** delta bit streams.
- **How it was cracked:** `community-spec` (Qhimm wiki).
- **Effort:** predates the history.
- **Reusable:** its LZS decoder is now the shared `gbox.formats.lz.lzss_decompress`.

### Metal Gear Solid: VR Missions and Metal Gear Solid

- **Modules:** `mgs_kmd`, `mgs_pcc`, `mgs_vr_tex`, `mgs_vr_swap`, `mgs_vr_tool`, `mgs_vr_unlock` and `mgs1_swap`.
- **Doc:** `mgs_vr_decomp.md`.
- **Formats:**
  - Container: STAGE.DIR, `.stg`, DAR.
  - Model: KMD (16 objects with weld pairs).
  - Texture: `.pcc` (PCX with MGS fields).
  - Animation: OAR (not decoded).
- **How it was cracked:** `instruction-pattern`.
  - The clear routine is matched by its lui/addiu 2/sw/`or 0x10000000` shape: exactly one hit in each of 91 overlays.
  - Checked against pcsx_rearmed save states (`ram-capture`).
  - `community-spec` cross-check with MetalMintSolid.
- **Effort:** 2026-10-09 to 2026-10-12, 12 commits. PRs #126 #234.
- **Reusable:**
  - The pattern is now generic: `gbox.formats.insn_pattern`.
  - MGS1 reuses the VR writer.

### Resident Evil 2 (PS1) and Clay Fighter: Sculptor's Cut (N64, 2D)

- **RE2** (`re2psx_inventory`, `re2psx_exe`):
  - Formats: PLD/PLW (EDD, EMR, MD1, TIM), RDT, and the EXE sector table.
  - Technique: `community-spec` (OpenBiohazard2) plus home-grown MIPS lui/addiu and jal scanners.
  - PRs #126 #139.
- **Clay Fighter SC** (`clay_fighter`, `clayfighter_sc`, `clayfighter_swap`):
  - Formats: CharDef blobs, MPF RLE8, LSB-first run bitstream frames, RGBA5551 palettes.
  - Technique: `symbols-first` in spirit (debug strings name CF3CDEF.H/CHARFRAM.C). The frame decoder was transcribed
    from RAM `0x80005870` and checked on all 3,183 frames.
  - CRC: `romexport.n64_crc` with CIC 6102.
  - PRs #126 #220.

## PS2, PS3, Xbox 360 and PC

### Def Jam Vendetta (PS2, AKI)

- **Modules:** `defjam_inventory`, `defjam_models` and `defjam_writer`.
- **Doc:** `defjam_pipeline.md`.
- **Container:** `DATA/DATA.BIN`, indexed by the ELF file table (293 x {sector, sectors}). Members: WRS fighters, TIM2,
  PAK, AUD and PRM/WAZA.
- **Model:** WRS slots 1-5 are VIF UNPACK V4-32 batches with 2-weight skinning.
- **Texture:** a GS packet holding a PSMT8 page plus a CT32 CLUT.
- **Skeleton:** 0x190-byte nodes (42-node BODY).
- **Animation:** slots 14-17, not decoded.
- **How it was cracked:**
  - `string-xref-loader`: `data/data.bin`, "load wrestler buffer %d", and slot names from debug strings.
  - `round-trip-proof`: 290/290 slots.
- **Effort:** 2026-10-12, 8 commits. PRs #129 #233 #251.
- **Reusable:** it reuses the `aki_wrestling` bake/decimate helpers and `sm64_swap`. Its ISO walk is now
  `gbox.formats.iso9660`.

### Metal Gear Solid 2: Substance (PS2, Konami)

- **Modules:** `mgs2_inventory`, `mgs2_models`, `mgs2_swap` and `ps2_gs` (a GS memory model).
- **Doc:** `mgs2.md`.
- **Container:** a DVD-9 with two ISO9660 layers (layer 1 has its own PVD at the layer break).
  - `MGS2/STAGE.DAT` and `STAGE2.DAT` hold an encrypted TOC of `{name[8], sector}` rows.
  - Each stage has an encrypted header of `(type << 24 | 24-bit name hash, offset)` rows, grouped into pages.
- **Codec:** zlib 1.1.3 pages under a 32-bit LCG xor stream (`k = k * 0x02e90edd + step`). The keys come from the
  archive time stamp and the stage name hash; a page's key comes from its first u16. The first u16 is stored minus
  0x8f3.
- **Model:** kms (type 0x0a). Bone records hold rest offsets and parents. Parts are <= 32-vertex triangle strips:
  s16 position + weight word, s16 normal + ADC flag, s16 uv.
- **Texture:** packs (type 0x13). The VRAM image is uploaded page-linearly as PSMCT32 and sampled as PSMT8 / PSMT4
  sub-rects with their own TEX0 / CLAMP / CLUT.
- **Skeleton:** in the kms (rest pose without rotations, mm).
- **Animation:** type 0x0c / 0x12, not decoded.
- **How it was cracked:**
  - `string-xref-loader`: `stage.dat` -> the ELF file table (`0x180b08`) -> the readers (`0x1008b0`, `0x101448`) ->
    the cipher (`0x1007a8` / `0x1007d8`) and the name hash (`0x1424c8`).
  - Model names came from the stage overlay's strings (`sna_def`, `rai_def`, `gbs_def`).
  - Characters were identified by rendering every 18-role kms on the disc.
  - `round-trip-proof`: page re-deflate + re-encrypt reads back identically.
- **Effort:** 2026-10-13, one session (branch `mgs2-cast`).
- **Reusable:** `ps2_gs` for any PS2 texture swizzle, and the two-layer `Disc` for any DVD-9. It reuses `sm64_swap`
  (load_rig / retarget), `gta_stories_models.pack_atlases` and `defjam_writer.quantize`.

### GTA III (PS2), Vice City (PC), Liberty City Stories and Vice City Stories (PS2)

- **Modules:** `gta_rw` (shared), `gta3_*`, `gta_vc_models`, `gta_vc_swap`, `gta_stories_models`,
  `gta_lcs_inventory` and `gta_vcs_inventory`.
- **Docs:** `gta_vc_pc_swap.md` and `model_swaps.md` section 3.
- **Container:** IMG v1 plus DIR (32-byte entries).
- **Model:**
  - GTA III: RW 3.1 rigid DFF.
  - Vice City: RW 3.4 DFF with the HAnim and Skin plugins.
  - Stories: relocatable `.mdl` ('ldm\0') and `.chk` ('xet\0'), with GAME.DTZ (zlib).
- **Texture:** PS2 or D3D8 TXD.
- **How it was cracked:**
  - `community-spec`: gtamods, librw, re3/reVC, and aap's storiesconv verified byte by byte.
  - `symbols-first`: the GTA III PS2 ELF ships its symbol table.
- **Effort:**
  - VC: 2026-10-12 to 2026-10-13, PRs #199 #251.
  - GTA III: PRs #126 #152.
  - Stories: predates the history, then #1313.
- **Reusable:**
  - `gta_rw.write_skinned_glb` is used by `auf_ngc` and `ue_mesh`.
  - `gta_rw.iso_files` is used by DMC2/3 and GS2.
  - `gta_stories_models` is used by romexport and re_lab_tool.

### Devil May Cry 2 and 3 (PS2)

- **Modules:** `dmc2`, `dmc3_inventory`, `dmc3_mod` and `dmc3_slus`.
- **Formats:** CRI AFS (nameless in DMC2), MOMO/PAC packages, MOD (DMC3, f32 version 1.01), TIM2 and MOT.
- **How it was cracked:** `instruction-pattern`. Headless Ghidra failed, so a pure-Python R5900 lui/addiu plus jal
  scan was used.
- **Effort:** #1314 and #1330, PR #126.

### Stranglehold (PS3, Unreal Engine 3) and Unreal Engine 4 Steam games

- **Stranglehold** (`ue3`, `stranglehold`, `stranglehold_inventory`; `stranglehold_interception.md`):
  - Formats: UE3 cooked `.xxx` packages (v375/25, big-endian), 64 KiB zlib chunks, UnrealScript per export.
  - Technique: `string-xref-loader` on the decrypted EBOOT (`intAStrangleholdPlayerPawnexecIsPrecisionAiming` ->
    OPD -> function), plus the `unreal-script` playbook.
  - PRs #167 #230.
- **UE4** (`ue_pak`, `ue_asset`, `ue_mesh`, `ue_steam`; `ue_steam.md`):
  - Formats: .pak v1-11 and IoStore headers; zlib/gzip, or Oodle through the game's own DLL; cooked USkeletalMesh
    (4.24-4.27) LOD0 plus the reference skeleton.
  - Technique: `community-spec` (engine source).
  - Effort: 2026-10-12 to 2026-10-13, PRs #171 #240.

### Resident Evil 6 (Xbox 360) and Resident Evil: The Mercenaries 3D (3DS)

- Both titles are Capcom MT Framework.
- **RE6** (`re6*`): MT ARC v7 (big-endian), `.mod` 0xD3, TEX 0x9D (tiled DXT). Live work in Xenia; predates the
  history.
- **Mercenaries 3D** (`merc3d_*`): NCSD/RomFS/BLZ, MT ARC v16 (little-endian, zlib), MOD v229. Technique:
  `magic-census` plus invariants. #1320.

## N64

### Super Mario 64, Mario Kart 64, Star Fox 64, Smash Bros. 64, OoT/MM, Perfect Dark, Mega Man 64

- **Shared:** `n64_rom` (byte orders, archives) is used by about 29 modules.
- **Codecs, now one implementation each in `gbox.formats.lz`:**
  - MIO0: SM64 and SF64 decode through it (their two decoders were merged). MK64 and Warzone only count MIO0 headers.
  - Yaz0: OoT and MM.
  - VPK0: SSB64, ported from the decomp's `syDmaDecodeVpk0`.
  - Okumura LZSS: Mega Man 64 (`mm64_inventory`, an lui/addiu scan for the archive bounds).
- **Codecs still in their title module:** Rare zip (0x1173 + raw deflate) for Perfect Dark, in `pd_inventory`.
- **Technique:** `decomp-reference` (n64decomp sm64/mk64/perfect_dark, sonicdcer/sf64, ssb-decomp-re, zeldaret), with
  every table checked against the owned ROM. The SM64 "USA" zip turned out to be PAL.
- **Effort:** mostly single commits on 2026-10-12 via PR #126 (MK64 #158, SSB64 #151).
- **Reusable:** `sm64_swap` (load_rig/retarget) is the generic writer back-end for about 18 swap modules.

### Turok 1 and 2

- **Formats:** tengine CIndexedSet tree at 0x1F00, RNC methods 1/2 with CRC-16, POLYSTREAM geometry.
- **Technique:** `community-spec` (the released tengine source).
- **Effort:** 2026-10-12, PRs #126 #209.
- **Reusable:** Turok 2 reuses Turok 1's decoders unchanged. They now live in `gbox.formats.rnc`.

### AKI wrestling (No Mercy, Revenge, WCW vs. nWo World Tour) and WCW Mayhem

- **AKI** (`aki_wrestling`, `aki_wcw`, `nomercy_*`, `wcw_worldtour_inventory`):
  - Formats: AkiFileTable (offset | 1 = compressed), Asmik LZSS, AkiModel rigid parts, CI8/CI4 textures with
    RGBA5551 palettes.
  - Technique: `community-spec` (VPW Studio and akifiletable, as references only), Ghidra on RDRAM images, and
    `instruction-pattern` with masked immediates to derive the Revenge PAL patch sites.
  - Checked in game on the Spark.
  - Reusable: `aki_wrestling` is the hub that SD2 and Def Jam PS2 borrow from. Its LZSS decoder now calls
    `gbox.formats.lz.lzss_decompress`.
- **WCW Mayhem** (`mayhem_inventory`): EA BIGF members with RefPack (`gbox.refpack`, facade in `gbox.formats.lz`).
  #1512, PR #218.

## RE tools that landed alongside

| Tool | What it does | When it landed |
|---|---|---|
| `ghidra_bridge` / `ghidra_bridge_tool` | The operator's Ghidra as JSON functions. | PR #217 |
| `re_agent` | ReAgent's reverser -> checker -> verifier loop. | PR #217 |
| `rea` / `rea_tool` | Pinned REA catalog. | 2026-10-08 |
| `decomp_tools` | decomp.me, IDA export, N64Recomp. | PR #219 |
| `re_lab` / `re_lab_tool` | Dossiers, playbooks, `re_executable`. | 2026-10-08, PRs #126 #219 |
| `re_seeds` | PLAYBOOKS and TITLE_FACTS. | 2026-10-08, PRs #195 #217 #234 |
| `cast_swap` | Whole-cast swap across the writers above. | PR #251 |
| `entity_probe` | Profile-driven entity tables. | PRs #195 #204 |

This branch adds the following, all fed by `assimilate_kb`:

- `assimilate` (the fingerprinter).
- Twelve technique playbooks.
- TITLE_FACTS for every title in the knowledge base.
- Dossiers that merge new seed facts.

## Shared library (`gbox/formats/`): what moved where

The pieces below were each copied in several title modules. One implementation remains, and the title modules
re-import it under the old name.

The migrations were checked two ways:

- A differential test of the old functions against the new ones on synthetic streams: 0 mismatches.
- The test suites of every affected module.

| Shared piece | Was | Users now |
|---|---|---|
| `lz.prs_decompress/prs_compress` (Sega PRS) | `ninja` | ninja, pso_*, sa1/sa2, psotext, characters |
| `lz.prs_msb_decompress` (Eighting PRS) | two copies: `cnr2`, `con2_inventory` | both (cnr2 keeps its negative-index window via `zero_window=False`) |
| `lz.mio0_decompress` | two copies: `sm64_mario.mio0`, `sf64_inventory.mio0_decompress` | both, sm64_inventory |
| `lz.yaz0_decompress` | `oot_writer` | oot_writer, mm_inventory |
| `lz.lzss_decompress` (Okumura) | `mm64_inventory`, plus inline copies in `ff7_models.lzs` and `aki_wrestling.lzss` | all three |
| `lz.lz10_decompress`, `lz.vpk0_decode` | `tetris_ds`, `ssb64_inventory` | same modules, ssb64_analysis |
| `rnc.decode_rnc` | `turok_inventory` | turok, turok2, turok_analysis |
| `iso9660.walk` | five walkers: `psxdisc`, `gdrom`, `defjam_inventory`, `raidou2_inventory`, `romexport` | all five (each keeps its path convention) |
| `gcfst.parse_fst` | `gcdisc` | gcdisc (every GC title), `formats.disc` for GCZ |
| `texture.morton/twiddled_index` | three copies: `ninja`, `doa2_textures`, `mkgold_geo` | all three |
| `texture.tim_parse/tim_build` | `yukes_sd` | yukes_sd |
| `rig.role_of_joint` | `re4gc_enemies._role_of_joint` | re4gc_enemies, doa2_weighted_retarget, sm64_swap |
| `rig.check_role_map` | `pso_player.check_roles` body | pso_player |

The new shared pieces are:

- `lz` encoders for MIO0, Yaz0, LZSS and Eighting PRS (synthetic round trips).
- `lz.inflate` (zlib, gzip or raw deflate).
- `texture` pixel words (ARGB1555, RGB565, ARGB4444, RGB5A3, IA8 and PS1 15-bit, scalar and numpy), GC tile order,
  and TIM to RGBA.
- `oracle` (RoutineOracle on the R3000, `check_inverse`, `check_reader`, and the Ghidra-emulator route for SH-4/PPC).
- `insn_pattern` (masked instruction search, MIPS jal graph, PowerPC lis/addi xrefs).
- `disc.listing` (disc, ROM, zip or folder to a file listing plus the executable).
- `ninja_chunk` (Ninja decode/encode/fit by role).

`gbox.formats.INDEX` keeps this table in code and `tests/test_formats.py` checks it.

Some shared code still lives where it was written and is imported from there: `gcz`, `gdrom.GDRom/CDIRom`,
`psxdisc.PSXDisc/RawBin`, `refpack`, `ue_*`, `ue3`, `gta_rw`, `sm64_swap.retarget`, `re4gc_enemies.retarget`,
`melee_models.write_gltf`, `naomilib` and `zn_tps_boot.R3000`.

## How good is the fingerprinter?

`assimilate op=evaluate` runs leave-one-out over the 49 titles: it hides each title and fingerprints its documented
layout with only the other titles plus the generic engine markers.

| Measure | Result |
|---|---|
| Engine family ranked first, titles whose family is reachable (generic markers fire, or another member is assimilated) | **0.905** (38/42) |
| Engine family ranked first, all 49 titles | **0.776** |
| Nearest remaining title shares the engine family, titles with a sibling | **0.892** (33/37) |
| Knowledge base only, no generic markers | 0.786 engine / 0.892 neighbour |

The remaining misses are honest gaps:

- AKI N64 titles have no codec magics or strings in their documented layout.
- Crazy Taxi 2's nearest title is Crazy Taxi GC, a different engine but the same franchise.
- FF7 resolves to Konami through shared PS1 traits.

These numbers come from documented layouts, not a live scan of the owned discs. The fingerprinter runs on real
listings (see `tests/test_assimilate.py::test_fingerprint_of_a_real_disc_image`); run `assimilate op=fingerprint` on
the Spark for each owned title to confirm them.

## Adding the next title

1. `assimilate op=fingerprint game_id=<id>`. Read `nearest_titles` and `proposal.start_from`.
2. Follow the `assimilate-title` playbook, using the technique playbooks it names.
3. Build on `gbox/formats` instead of copying a codec or walker. If you need one that doesn't exist, add it there with
   a synthetic round-trip test.
4. When the reader works:
   - Add an entry to `gbox/assimilate_kb.py`: files with their head and inner signatures, strings, engines, reader,
     techniques and effort.
   - Add a section here.
   - Bump `FACTS_VERSION` in `re_seeds.py` if facts changed.
   - Run `assimilate op=evaluate`.
