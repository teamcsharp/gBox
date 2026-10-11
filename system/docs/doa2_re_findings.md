# Dead or Alive 2 Limited Edition Japan: native RE and reintegration

Request #1135 / missing-writer gap #1140. Game `1de2e7634f3161ff`, owned Dreamcast GD-ROM. Acceptance requires a character replacement rendered and animated by the game; exporting an asset, an overlay, or a completed agent run does not meet that requirement.

## Source identity and preservation

| Asset | SHA-256 |
|---|---|
| Original CHD | `a0b4dd4e53db905909bc6255077cc436549ce51d0821fe4ce2819aa3e4e452fe` |
| Unscrambled `1ST_READ.BIN` | `27a014aeda35983df749f7d575bbddbea3f1ffd1f7776194ef503108c20c97e1` |
| `DOA2/KAS00.CHR` | `63a67aa37da73d09e795c7e14b6ad39ed533ef6adeb7cd17787d749c7ae5dcee` |
| `DOA2/KAS00.BIN` | `49e09538244a8617c1457ed5c81b0b502f51c8392a772e9536630599dfd335d1` |

Executable load address `0x8c010000`; processor SuperH4 little endian. Original CHD and extracted GDI tracks remain unchanged. Modified copies use `gdrom.patch_gdi`, retaining filesystem extents when allocations fit and recomputing Mode 1 EDC/ECC.

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
- Amy's complete 1,384 triangles fit all 79 actual humanoid costume bindings. The unused one-model YTI00 placeholder has no valid body binding and is rejected.
- A gentle single-vertex KAS00 edit survives GDI reintegration. All 959 other disc files remain identical; 145 touched Mode 1 sectors verified. Original source hashes remain unchanged.
- Actual KAS00/AYA00/GEN00 exports produce validated manifests, PNG textures and GLB part geometry (663,196 / 568,708 / 812,612 bytes respectively).
- Explicit PVR header synthesis and descriptor conversion cover all 79 Amy costume allocations without image resizing. Untouched texture slots and unrelated models remain separate.
- RGBA atlas fallback resolves all 77 previously failing native donor/target material pairs, plus Gen Fu to Kasumi. Twenty-four cases retain image resolution; 54 report resizing. Geometry, joints, alpha and sampler semantics are checked independently.
- A native Kasumi-to-Ayane conversion requires geometry reduction: the audited refinement retains 4,761 of 7,104 triangles in 302,896 bytes of a 303,104-byte allocation. Smooth normals are recomputed; native rigid parts use dominant weights. This is a conversion result, not gameplay acceptance.
- Current focused regression suite: 206 tests and 43 subtests pass on Windows. Earlier core geometry/material/rig tests also passed on Linux. Native runtime acceptance is independently required.

Evidence files live in private `gbox-data/doa2-re/{geometry,rig,animation}`. They contain owned asset data and are not distributed with source.

## Native rig, motion and supplements

The executable resource table at `0x8c17f5f4` resolves actual fighter/costume filenames. Render scripts at `0x8c1c85f4` select fifteen primary models, two eye models, shadows and accessories. Default Ein costume C1 is KTE01; KTE00 is C2. Filename suffixes must not be treated as selection indices.

Seventeen rest vectors are recovered from `0x8c1949a0`. SUP records constrain local body axes and supply curved seam geometry; they are not a standalone skeleton. Fifteen body roles have explicit model bindings and parent relationships. Eye joints 15/16 follow head joint 1 through `0x8c07859e`. Tengu's six wing joints follow the native ACS initialized rotation/translation chains. Neutral export reproduces curved seam positions; two-joint GLTF seam weights approximate later nonlinear deformation.

ACS decoding preserves repeated model instances, held props and all raw controller data. Further vertex-chain and cloth reconstruction remains separate from the verified body export; unsupported physics is reported rather than fabricated.

MOT has shared clip/track payloads. The loader at `0x8c01494c` relocates 44 channel pointers and stores the MOT base at move-definition offset `0x58`. These are IK/control channels, not 44 bones. The inspector validates all 149 containers: 80 indexed44, 68 paired44 and one legacy26, comprising 8,407 unique clip tables and 368,996 physical streams. M_SAMBO mixed raw streams and TINA_C legacy coefficient records have separate strict schemas. Native compact signed20 values and linear/quadratic/cubic Hermite polynomials are decoded from `0x8c0e86c2`; comparison with live SH4 float32 samples and legacy/raw runtime semantics remains unverified. The corpus retains 44,844 opaque unreferenced bytes explicitly. Native replacements preserve original move and motion files byte-for-byte.

APV morph offsets and SUP vertex writes cannot be retained after changing mesh topology. Native setup honors signed APV -1 section offsets and a zero SUP directory. Render-script mode-two ACS initialization is replaced by an empty mode-zero command, retaining later directives. Every modified file is hashed and verified after GDI reintegration.

## Tools and runtime acceptance

`doa2_assets` provides inspect, decompose, motions and build operations for the owned title. Decomposition emits editable rigged GLTF, raw resources, part GLB, rig evidence and a report. The character-use route builds a specified fighter and all its actual costumes. Large donors use reported atlas/LOD attempts within native allocations. Builds remain `built_unverified` until independent gameplay evidence exists.

Initial all-costume Ein-to-Amy ROMs boot, but fighter initialization/drawing causes Flycast's `Fatal: SH4 exception when blocked`. A control reencoding one original upper-arm material group into native independent triangles renders correctly. Full replacement controls for null markers, culling and compact references remain unsuccessful. Native material analysis found first-group intensity reuse in 13 replaced KTE01 models, while none of 8,034 original models starts with that format. The initializer does not repair this ordering; a narrowly scoped material repair is under test. None is accepted as a completed swap. An isolated Flycast v2.6 diagnostic core captures the exception before its registers are overwritten or the content unloaded. Its original-disc baseline renders the native fighters correctly; fault capture on the mod remains pending. The [upstream exception path](https://github.com/flyinghead/flycast/blob/master/core/hw/sh4/sh4_interrupts.cpp) explains why normal release logs omit the faulting PC.

JAYBUILTFINALE runs the original title through Flycast on its NVIDIA RTX 3070 with volume held at 2%. A captured native gameplay baseline is attached to #1135. The i9-NUC is reserved for the operator. Modified-ROM gameplay and animation acceptance remain outstanding; #1135 and #1140 must stay in progress until they pass.

## Primary format references

Independent implementation acknowledges VincentNL, EgregiousGuy and The_Zocker160:

- [DOA2 CHR format](https://github.com/NaomiMod/games-ExtractTools/blob/main/DOA2/CHR_Format.md)
- [NaomiLib model format](https://github.com/NaomiMod/NL-ModelFormat/wiki)
- [NaomiLib Blender importer/exporter](https://github.com/NaomiMod/blender-NaomiLib)
- [Original author's DOA Ghidra research](https://github.com/ryu-highabusa/COMDATsamba)
