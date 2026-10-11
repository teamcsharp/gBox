# Dead or Alive 2 Limited Edition Japan: native RE and reintegration

Request #1135 / missing-writer gap #1140. Game `1de2e7634f3161ff`, owned Dreamcast GD-ROM. Acceptance requires a character replacement rendered and animated by the game; exporting an asset, an overlay, or a completed agent run does not meet that requirement.

## Source identity and preservation

| Asset | SHA-256 |
|---|---|
| Original CHD | `a0b4dd4e53db905909bc6255077cc436549ce51d0821fe4ce2819aa3e4e452fe` |
| Unscrambled `1ST_READ.BIN` | `27a014aeda35983df749f7d575bbddbea3f1ffd1f7776194ef503108c20c97e1` |
| `DOA2/KAS00.CHR` | `63a67aa37da73d09e795c7e14b6ad39ed533ef6adeb7cd17787d749c7ae5dcee` |
| `DOA2/KAS00.BIN` | `49e09538244a8617c1457ed5c81b0b502f51c8392a772e9536630599dfd335d1` |

Executable load address `0x8c010000`; processor SuperH4 little endian. Original CHD and extracted GDI tracks remain unchanged. Modified copies use `gdrom.patch_gdi`, retaining filesystem extents when allocations fit and recomputing Mode 1 EDC/ECC. An enlarged SUP can reuse only sector tails freed by modified, smaller resources. The two-pass allocation protects directory metadata and unmodified aliases; it does not sacrifice another costume. GEN00's 7,784-byte replacement SUP exceeds its original 6,144-byte space and exercises this relocation path.

## Corrected CHR and BIN layout

The earlier reader misidentified the texture count as a bone count and texture descriptors as bind-pose triplets. Those claims are incorrect and have been removed.

CHR starts with six u32 words: header bytes (24), model-pointer-table offset, texture-directory offset, model count, **texture count**, reserved zero. The model-pointer table uses absolute work-RAM addresses. Model file offset is `pointer - first_pointer + 24`.

Each NaomiLib model starts with two flag words and a four-float bounding sphere. Submeshes have 80-byte material headers followed by strips or independent triangles. Inline vertices contain XYZ, normal XYZ, UV; compressed records refer to earlier vertices through DMA and RAM deltas. Packed-normal and constant-color variants are also decoded. The end marker records the logical vertex count. Rebuilding relocates model pointers and preserves texture descriptors.

Texture descriptors contain packed width/height, pixel/data-format flags, and an absolute VRAM address. BIN addresses are relative to the first descriptor address. Supported pixel formats: ARGB1555, RGB565, ARGB4444. Supported layouts: square twiddled, rectangular twiddled, VQ with a 256-entry codebook. Texture encoding preserves allocations and untouched bytes.

Kasumi KAS00 has 56 models and **55 textures**; Ayane AYA00 has 48 models and 45 textures; Gen Fu GEN00 has 52 models and 52 textures. These are not skeleton joint counts. Exported model parts retain local coordinates until runtime transforms are recovered.

## Validation evidence

- All 80 fighter costumes: strict decode and byte-exact CHR reconstruction; 3,800 models, 7,974 submeshes, 711,215 triangles, 394,786 compressed references.
- All 3,072 textures across those costumes: validated texture boundaries and decoding.
- Amy Rose source: 62 donor joints, 15 mapped body roles, seven materials, all 1,384 triangles preserved by native geometry conversion. Maximum decoded attribute error `2.97e-8`.
- Amy's complete 1,384 triangles were structurally converted for all 79 available native costume bindings. Production strip builds for all five Ein costumes and Gen Fu preserve their geometry; the latter requires the safe SUP relocation described above. Runtime acceptance is recorded per combination. YTI00 has no valid native render binding and is rejected. The executable also declares BAY02, whose resource triplet is absent from this disc.
- A gentle single-vertex KAS00 edit survives GDI reintegration. All 959 other disc files remain identical; 145 touched Mode 1 sectors verified. Original source hashes remain unchanged.
- Actual KAS00/AYA00/GEN00 exports produce validated manifests, PNG textures and GLB part geometry (663,196 / 568,708 / 812,612 bytes respectively).
- Explicit PVR header synthesis and descriptor conversion cover all 79 Amy costume allocations without image resizing. Untouched texture slots and unrelated models remain separate.
- RGBA atlas fallback resolves all 77 previously failing native donor/target material pairs, plus Gen Fu to Kasumi. Twenty-four cases retain image resolution; 54 report resizing. Geometry, joints, alpha and sampler semantics are checked independently.
- Complete native source decomposition covers 79 available costumes: 653,970 triangles, 475,055 vertices, 320 ACS draw instances, 114 deformed chains and 93 cloth grids. Original SH4 cloth initialization and generators are reproduced in a read-only Ghidra emulator; all 93 initializers, 93 generators and 5,512 aliases verify without errors.
- Full GEN00 source export reimports as 7,512 triangles, 5,264 vertices, 17 joints and 15 semantic body roles. Influence-preserving fitting succeeds on all 79 available target rigs. Allocation and native gameplay checks are separate from fitting.
- Final combined affected regression suite: 483 tests and 46 subtests pass on Windows, including native exports, registration, reintegration, save-file evidence, favorite coverage and Hermes quota recovery. Native runtime acceptance is independently required.

Evidence files live in private `gbox-data/doa2-re/{geometry,rig,animation}`. They contain owned asset data and are not distributed with source.

## Native rig, motion and supplements

The executable resource table at `0x8c17f5f4` resolves actual fighter/costume filenames. Render scripts at `0x8c1c85f4` select fifteen primary models, two eye models, shadows and accessories. Default Ein costume C1 is KTE01; KTE00 is C2. Filename suffixes must not be treated as selection indices.

Seventeen rest vectors are recovered from `0x8c1949a0`. SUP records constrain local body axes and supply curved seam geometry; they are not a standalone skeleton. Fifteen body roles have explicit model bindings and parent relationships. Eye joints 15/16 follow head joint 1 through `0x8c07859e`. Tengu's six wing joints follow the native ACS initialized rotation/translation chains. Neutral export reproduces curved seam positions; two-joint GLTF seam weights approximate later nonlinear deformation.

Complete export follows the executable's actual ACS binding, including JAN02's shared JAN_A01 resource. It preserves repeated draws, props, vertex chains, generated cloth grids, and provenance to native resources and routines. Cloth is frozen at the reconstructed neutral moment. Native nonlinear seam deformation is approximated by linear glTF skinning outside the game; projected texture coordinates, procedural effects and subsequent native cloth physics remain explicit limits of the interchange export.

MOT has shared clip/track payloads. The loader at `0x8c01494c` relocates 44 channel pointers and stores the MOT base at move-definition offset `0x58`. These are IK/control channels, not 44 bones. The inspector validates all 149 containers: 80 indexed44, 68 paired44 and one legacy26, comprising 8,407 unique clip tables and 368,996 physical streams. M_SAMBO mixed raw streams and TINA_C legacy coefficient records have separate strict schemas. Native compact signed20 values and linear/quadratic/cubic Hermite polynomials are decoded from `0x8c0e86c2`; comparison with live SH4 float32 samples and legacy/raw runtime semantics remains unverified. The corpus retains 44,844 opaque unreferenced bytes explicitly. Native replacements preserve original move and motion files byte-for-byte.

Old APV/SUP vertex offsets cannot be retained after changing mesh topology. The writer disables stale APV sections and reconstructs SUP records against the new topology. It preserves all mapped donor influences before native seam quantization; identical logical vertices share one sample even across triangles owned by different joints. The native format supports at most two mapped influences per vertex, a common owner per face, fourteen seam records and available supplementary models. Unsupported cases fail with an actionable reason. Duplicate SUP draws are used only for opaque material with byte-identical geometry, strict GREATER depth comparison and depth writes; transparent material must draw once. ACS uses its native eight-byte empty terminator while the original executable and mode-two initialization remain intact. The executable command substitution was disproved: it suppressed both fighter draw passes. Every modified resource is hashed and verified after GDI reintegration.

## Tools and runtime acceptance

`doa2_assets` v1.1 provides inspect, decompose, motions, native_cache and build operations for the owned title through the public job/MCP system. `native_cache` prepares, executes and verifies the original SH4 cloth pipeline. Complete decomposition requires verified cache data and emits editable rigged GLTF, raw resources, part GLB, rig evidence and a report. Full provenance is attached separately from the bounded response. The character-use route builds a specified fighter and all its actual costumes. Large donors use reported atlas/LOD attempts within native allocations; downscaling is explicit. Builds remain `built_unverified` until independent gameplay evidence exists.

`characters op=extract character="Gen Fu" game_id="1de2e7634f3161ff"` registers the complete source with all fifteen semantic roles when its verified cache is available. Older partial entries refresh and their existing mods require rebuilding. Edited skinned GLB/glTF donors can be registered with `characters op=add path=... character=... rig_roles={...}`; each supplied role must name a unique actual skin joint. `doa2_assets op=build fighter="Leifang" costume="05" character=...` then retargets it and writes a copied playable GDI.

The Ein C1 replacement now renders all 1,384 Amy triangles inside the game's native Sparring match against untouched Ayane. Movement and attacks produced a 30-damage critical hit. Saving and reloading the actual slot-zero state restored the fight. The test used Flycast v2.6 on JAYBUILTFINALE's NVIDIA RTX 3070, with agent volume at 2%; i9-NUC remains reserved for the operator.

Independent saved-state analysis of the final strip-based weighted build matches all 1,139 inline records and 3,013 compressed references. Native SUP positions and normals agree with the original curved solver to `2.384e-7`; 222 shared vertex groups, including 48 crossing different owners, have maximum gap `2.469e-7`. Native GPU strip multisets contain all 1,384 source triangles, with correct strip ends, finite positive depth and byte-identical duplicated opaque vertices. State SHA-256: `c398d36b4db048e14d097fd1b9b908722949110b1e0e9e8c0b0871d96b2ba1a1`. Evidence: private `geometry/production_strip_ein_live_audit.json`, screenshots, the actual slot-zero state and successful save/load job receipts.

Writer repairs retain a valid zero-area triangle/material header for unused primary parts, initialize moved intensity colors, set inline X/V native payload tags, and preserve indexed geometry flags. Native strips use bit4 (`0x71`), and DMA references account for every polygon header and vertex. The independent 79-costume primitive audit finds only strips and independent triangles; unsupported fan/sprite flags are rejected. The original executable is preserved, and ACS termination disables stale geometry writes without skipping its initialization.

The second acceptance case replaces Leifang C6 (`LEI05`) with the complete native Gen Fu source: all 7,512 triangles and 52 original textures retained without resizing. Native attacks produce 28 damage, and loading the actual slot-23 checkpoint restores the match. The saved state is 10,371,920 bytes, SHA-256 `0026a87089b6efd11e563225e08f814c76673dd17bf980c8d101f80d3eeb9c31`. Independent native audit matches 5,250 inline records, 6,106 compressed references and every GPU strip; maximum shared-vertex world gap is `1.145e-7`. All fourteen audit checks pass with no GPU parser warnings. Evidence: private `geometry/production-gen-lei05-live-audit.json`, gameplay/attack/restoration screenshots and the original saved state.

The old save job reported requested slot zero while RetroArch actually wrote slot 23. That discrepancy is preserved in the evidence rather than counted as a slot-zero success. The adapter now verifies a newly written, stable nonempty native state file, reports its actual slot and path, reconciles its slot counter, and rejects missing capture evidence. The source tests cover this discrepancy and bounded large-log reads; deployment acceptance of the new capture path is separate from the already verified slot-23 restoration.

Deployed capture acceptance verified requested slot30 equals actual slot30 and native loading selects the identical 10,070,931-byte portable file, SHA-256 `4f57b81700c67e64e52d78d6b27e5ef862d94a205539a4803d985f50b15732d5`. Resuming this separate stock-core checkpoint originally corrupted its backdrop. Report #1216 preserves that failure, its state, screenshots, native log and exact driver/core hashes. Inbox #1106 closes only the false slot/file preservation report.

The supplied ranking moment retains Ein, the lab geometry, score 1825 and its ranking display commands, but its RGB565 backdrop at guest VRAM `0x473800` is stale. The private frozen native-render experiment selects TA context `0x563100`, whereas the restored saved context is keyed `0x163100`. A guarded host-only alias lets the exact stock renderer consume the saved original geometry and write its native 512×256 backdrop without advancing guest CPU execution. Original RAM and VRAM outside the 262,144-byte target remain identical. The host alias is not persisted in the recovered state, and no screenshot/reference pixels supply the repair.

The texture-only reconstructed state is 10,120,183 bytes, SHA-256 `9239cb198e94eb2e605d83b46702c68d247e101877773d72720f53387c9e622a`. It changes 257,384 bytes inside that one texture range; original CPU/RAM, normal TA, PVR registers, ranking quad, all remaining VRAM and opaque RASTATE blocks are byte-identical. Only compressed chunks 62–64 are recompressed. Independent validation compares the entire decoded container and unchanged compressed chunks.

Isolated unmodified stock-core tests pass on NVIDIA GB10/Linux and the original NVIDIA RTX 3070/Windows core. Both verify load, frame advance, bounded resume, actual asynchronous native save completion, exact private-slot reload, another frame advance and resumed playback with green SURVIVAL RANKING, original Ein/lab and score 1825. Their actual completed native saves have SHA-256 `85ba793e860e5c698e93d781e57c94507b2405a58992c135e9a6657a021ac499` (Spark) and `e16e3578c4ab5165fd698249b02f5f022b7e0cae43766b43088596fc3ef37fbb` (Windows). The first minimized Windows paused view was black until a native frame was presented; that failed initial presentation is recorded separately. These are standalone stock-core tests, not a verification of Chromium's integrated capture path. Original shared saves/core/config files are preserved; screenshots, command receipts, native logs and repaired checkpoints are private inbox attachments. This is a bounded recovery of the supplied checkpoint, not a general Flycast state repair or arbitrary donor acceptance.

The public offline CLI reproduces that exact tested derivative from the original report state and its native-produced buffer:

```sh
python scripts/doa2_recover_checkpoint.py --original ORIGINAL.state --native-buffer native-replayed-rtt-v2.bin --output NEW.state
```

Encoding requires the optional `zstandard` package. The CLI validates exact input sizes/hashes, V59 layout, guest RAM, preservation boundaries and expected output hash before creating a new file exclusively. It refuses unknown inputs and existing output paths, runs no emulator and never overwrites a shared save. Thirteen portable synthetic checks pass normally and under Python `-O`; actual reported inputs reproduce SHA-256 `9239cb19…`, while altered original/native inputs and overwrite attempts are rejected. The report buffer is required; this does not regenerate missing textures for other checkpoints.

Final production preparation passes all 79 available Amy targets, including the explicit `LOR`, `MAM`, `PDG` and `WBA` variants. All retain 1,384 triangles without downscaling or geometry reduction. All-target allocation validation is separate from gameplay acceptance.

Native rendering, smooth joint continuity, playable attacks and save-state restoration are established for Amy-to-Ein and Gen-Fu-to-Leifang-C6. Complete fighter/costume source exports and all-fighter retarget fitting are verified separately. Other target/donor gameplay combinations require their own acceptance; unverified builds do not inherit a success claim from these tests. Stage extraction, arbitrary game formats, native animation round-trip equivalence and universal unlock profiles remain outside this verified writer scope.

## Primary format references

Independent implementation acknowledges VincentNL, EgregiousGuy and The_Zocker160:

- [DOA2 CHR format](https://github.com/NaomiMod/games-ExtractTools/blob/main/DOA2/CHR_Format.md)
- [NaomiLib model format](https://github.com/NaomiMod/NL-ModelFormat/wiki)
- [NaomiLib Blender importer/exporter](https://github.com/NaomiMod/blender-NaomiLib)
- [Original author's DOA Ghidra research](https://github.com/ryu-highabusa/COMDATsamba)
