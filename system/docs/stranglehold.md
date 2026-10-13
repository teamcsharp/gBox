# Stranglehold (PS3): native model reader and character writer

Ticket #1410 ("Session models: John Woo Presents Stranglehold": no native model reader registered). Catalog entry
`9c436f5a9754f777`, platform `ps3`, BLUS30081, a PS3 disc folder (`.../PS3_GAME/USRDIR/EBOOT.BIN`) run in RPCS3.
The second entry `cd8e9ef22b93c3af` is the 7z of the same disc and is not playable.

- Reader: `gbox/stranglehold_models.py`. It is registered as the `stranglehold` DEDICATED reader in
  `characters.DEDICATED`, and its reader version is recorded as `stranglehold_reader`.
- Writer: `gbox/stranglehold_swap.py`. It is routed from `characters` `op=use` and registered in
  `char_coverage.WRITERS`, `cast_swap` (`pairs`, `build_cast`) and the `replacement_readiness` SPECS.
- Inventory: `gbox/stranglehold_inventory.py`, which reads package tables only.
- Tests: `tests/test_stranglehold_models.py` and `tests/test_stranglehold_swap.py`, which use synthetic packages
  built in `tests/stranglehold_synth.py`. No game data is committed.

## Packages

`StrangleholdGame/CookedPS3/*.xxx` are Unreal Engine 3 packages, version 375 with licensee 25 (Midway), big-endian.
Most are **chunked zlib**:

- **Summary:** the uncompressed summary has the Midway fields before the `None` folder name. The compressed-chunk
  table follows it and sits outside the logical package: logical offsets start at the first chunk's
  `uoff = 0x71`.
- **Chunks:** each chunk is a standard UE3 compressed chunk: tag `0x9E2A83C1`, block size `0x10000`, totals, a block
  table, then zlib blocks.
- **Exceptions:** script packages are fully compressed, and 5 packages are raw.
- **File size:** every file is padded to 32 KiB.
- **`PS3TOC.txt`:** lists each file as `size 0 0 ..\StrangleholdGame\CookedPS3\<file> 0`, with no CRCs. A rewritten
  package must update its size there.

One SkeletalMesh per character package:

| group | packages |
|---|---|
| Tequila | `char_tequila`, `_suit`, `_jacket`, `_sweater`, `_jack_swtr` (each also `_MP`) |
| gang enemies (multiplayer skins) | `char_{GK,DC,I9,RM}_<Class>_<n>_MP` (22) |
| named cast | Damon / Vlad Zakarov, Jerry Ying, Wong, the tea house boss, Captain Lee, Lou, HKPD, John Woo, the junk captain, Lok, Yung (`char_*_MP`) |

The campaign enemies live inside the level packages (`*_mission`, `*_mso`).

## SkeletalMesh layout (PS3 cook)

After the 4-byte net index and the tagged properties (`Sockets`, `LODInfo`, `MeshGuid`), the export contains:

- `FBoxSphereBounds`, the `Materials` TArray, `Origin` and `RotOrigin`.
- `RefSkeleton`: `TArray<FMeshBone>`, 48 bytes each: FName, flags, FQuat, FVector, children, parent.
  - The bind pose composes with UE row vectors: `world = local * parent`.
  - Mesh space is centimetres, -Y up, +Z front, +X = the character's left.
  - Every cast member uses the shared HumanIK-named "medium_skeleton" (87 to 94 bones).
- `SkeletalDepth`, an `i32 0`, then `LODModels`. Tequila has 1 LOD and the multiplayer meshes have 4. Each LOD
  contains, in order:
  - sections: `{u16 material, u16 chunk, u32 first index, u16 triangles}`;
  - an empty index buffer;
  - `ActiveBoneIndices`;
  - an empty `TArray<u8>`;
  - chunks, each with its first vertex, empty rigid/soft arrays, its bone map, rigid/soft counts and max influences;
  - a 4-byte value that is never initialised, then the vertex count and 0;
  - the SPU geometry: `i32` chunk count, then per chunk an `i32` segment count and the segments;
  - `RequiredBones` (`TArray<u8>`).
- The name-index map and the rest of the export follow the LODs.

### SPU segments (Sony Edge style partitions)

Each segment is laid out in this order:

1. **Config (16 bytes):** `06`, the command-buffer hole (one step per 768 indexes, from `0x0D`), `FF FF FF`
   (custom formats), `31` (compressed indexes + skinning), `u16` vertexes padded to 8, `u16` indexes, `FFFFFFFF`, `0000`.
2. **Header:** `u16 A` (index block bytes, a multiple of 16), `u16 B` (explicit indexes), `u16 C` (delta bias),
   `u16 D` (bytes of the sequential bit stream), `u8 E` (bits per delta), `u8 0`.
3. **Index block:**
   - D bytes of one bit per index read: 0 = the next new vertex, 1 = explicit.
   - Two bits per triangle: `0` shares `(p0, p2)` of the previous triangle, `1` shares `(p2, p1)`, `2` shares
     `(p1, p0)`, `3` has three own indexes.
   - B values of E bits each.
   - Padding (uninitialised bytes), then `[u16 A][u32 0][u16 vertex bytes]`.
   - **Decoding the explicit indexes:** explicit index k = explicit index k-8 (0 for the first eight) + value - C.
     These are eight interleaved delta chains, one SPU quadword of u16 lanes.
4. **Vertexes:** 23 bytes each, padded to 16:
   - `3 x half` position;
   - 9 bytes of packed tangent frame (not decoded; the reader rebuilds normals);
   - `2 x half` UV0;
   - `2 x half` UV1.
5. **Skin header (36 bytes):**
   - two DMA sizes for the vertex stream (each 16 KiB at most);
   - two bone-matrix ranges as byte offsets and sizes of 48-byte matrices into the RefSkeleton;
   - the weight-stream size (twice).
6. **Weights:** `4 x (u8 weight, u8 slot)` per vertex, summing to 255. The slot indexes range 0 and then range 1.
7. **Trailer:** two SPU scratch words (`[1]` = 7 x the padded vertex count), then 30 zero bytes.

### Textures

Texture2D tagged properties (`SizeX`, `SizeY`, `Format`: 5 = DXT1, 7 = DXT5, 2 = A8R8G8B8) are followed by:

- the empty source-art bulk record;
- `TArray<FTexture2DMipMap {bulk record, SizeX, SizeY}>`.

The 2048 top mip of the body atlases is not cooked (bulk flags `0x21`, size -1); the 1024 mip is stored inline.
The DXT blocks use the usual little-endian layout. The body uses `<char>_all_diffuse` with `_normal`, `_specular`
and `_graypack` alongside it; the hair has its own small set.

### How the index coding was found

| clue | what it showed |
|---|---|
| Ones in the bit stream = `B` (764 in Tequila's first segment) | 1 = explicit |
| Bits read = 3 x code-3 triangles + 1 x others | matched D x 8 exactly |
| The UV layout of the first all-new strip | the edge rules for codes 0 and 1 |
| The first eight explicit values equal `index + C` | lane start = 0 |
| A beam search over UV/3D-consistent triangles (scratch, not shipped) | ground truth for 400 triangles |

In that ground truth, `index[k] - index[k-8] = value - C` held for 65% of the pairs, and the misses were the solver's
own errors. The full decode then gives exactly `vertex count` new vertexes in every segment of all 39 meshes, with
every index in range and ~100% small UV triangles.

## Reader

`characters op=extract` / `op=collect` uses the roster below.

| Entries | Slugs |
|---|---|
| 5 Tequila outfits | `stranglehold_tequila`, `stranglehold_tequila_suit`, ... |
| 22 gang enemies | `stranglehold_gk_assault_1` ... `stranglehold_rm_sniper_1` |
| 5 bosses and 7 named characters | Damon and Vlad Zakarov, Jerry Ying, Wong, ... |

Each entry becomes a GLB with these properties:

- **Primitives:** one per material, with the bind-pose skeleton as glTF joints (world matrices kept).
- **Weights:** 4 per vertex.
- **Textures:** the material's diffuse; hair uses an alpha mask.
- **Frame:** metres, +Y up, facing +Z, left on +X (mesh space mirrored on Y, winding flipped).
- **Roles:** 18, by bone name (`hips`, `spine2`, `neck`, `Head`, `Left/RightShoulder`, `...Arm`, `...ForeArm`,
  `...Hand`, `...UpLeg`, `...Leg`, `...Foot`).

The source folder is found in this order:

1. next to the catalog EBOOT.BIN;
2. `//10.89.1.125/QuickSwap2/...`;
3. `/mnt/gbox/quickswap2/...`.

CLI: `python -m gbox.stranglehold_models [CookedPS3] --out dir [--only char_tequila,...]`.

Measured on the owned disc, 2026-10-13: all 39 packages extract with 0 errors.

- **Tequila:** 11,713 triangles in 12 segments, 94 bones, 1.96 m.
- **Enemies:** 5,090 to 9,063 triangles, 88 bones.
- **Collection:** every entry passes `verify_entry` and its readiness is "ready".

## Writer

`characters op=use` takes these slots:

- `player` / `tequila`: all 10 Tequila packages;
- `tequila:<default|suit|jacket|sweater|jack_swtr>`;
- `enemy:<gk_assault_1 ...>` (a multiplayer skin) and `enemies` (all 22);
- `model:<package stem>`.

A cast plan goes through `cast_swap` (`pairs`, `build_cast`) and produces one folder mod (`filemods.build`) holding
the rewritten `.xxx` files plus `PS3TOC.txt`. The mod is named `sh_<slot>_<hash>`.

For each package:

1. **Retarget:** `sm64_swap.retarget` puts the donor on the package's own bind pose (JMAP: the 15 limb roles to the
   RefSkeleton bones) and emits the fit events (weights, decimate, encode, write).
2. **Atlas:** one 1024 atlas (`auf_swap.build_pages`). Its DXT mips are re-encoded in place over the body diffuse
   texture. The `_normal`, `_specular` and `_graypack` maps of that atlas are flattened, because their texels belong to
   the stock UV layout.
3. **Encode every LOD:**
   - LOD 0 keeps up to 1.25 x the stock triangles, and LOD n is decimated to the stock count.
   - The mesh is split into segments of at most 700 vertexes, 1100 triangles and 60 matrices, grouped by bone then
     height.
   - Indexes are coded with code 3 and lane deltas.
   - Weights are rigid, with two-range palettes.
   - The tangent frame and UV1 are copied from the nearest stock vertex.
   - There is one section / chunk on material 0. ActiveBoneIndices, RequiredBones, the RefSkeleton, sockets and
     everything after the LODs are kept.
4. **Write:**
   - The new SkeletalMesh export is appended to the logical package. Only its export-table entry changes, so every
     other export keeps its serial offset.
   - Changed chunks are recompressed and the last chunk is extended; the chunk count, and so the summary length, is
     unchanged.
   - The file is padded to 32 KiB and its size updated in `PS3TOC.txt`.
5. **Proof:** the written package is parsed again by the reader before the mod is built.

CLI (offline, no mod folder): `python -m gbox.stranglehold_swap donor.glb roles.json <CookedPS3> <out dir> [slot]`.

Offline runs, 2026-10-13:

- **Meryl (Twin Snakes) into `char_tequila.xxx`:** 3,196 triangles in 5 segments, 6.8 s.
- **Shadow (SA2) into `char_GK_Assault_1_MP.xxx`:** all 4 LODs, 4.9 s.
- Both read back with the reader: only the mesh export moved, and only the diffuse/aux textures changed.

### Not verified / not covered

- **Not yet run in RPCS3.** These values copy the shipped segments and are not decoded semantics:
  - the SPU scratch word `[0]`: kept generous, at most the largest shipped value;
  - the command-buffer hole: same step rule as the shipped segments;
  - the copied tangent frame.

  If the SPU job rejects a segment, these are the first suspects.
- **Campaign enemies are not written.** They sit in the level packages (`*_mission` / `*_mso`), where one texture atlas
  is shared by a whole class family (`assaultClass01..05` in one level). A rewrite there has to replace every family
  member at once, or append its own texture export.
- **Tequila's cinematic meshes** (`*_cine` packages) are not written.

## Evidence

The PNGs are in `D:\gBox\research\stranglehold\evidence\`:

- `stranglehold_collection.png`: all 39 reader GLBs.
- `stranglehold_tequila_enemies.png`: Tequila and 4 enemies.
- `before_after_after_meryl.png`: stock Tequila next to the written package read back.
- `before_after_after_shadow_gk.png`: the same for the GK assault 1 skin.
