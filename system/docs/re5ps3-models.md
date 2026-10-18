# RE5 Gold PS3 editable native models

`python -m gbox.re5ps3_models` exports an exact model resource from an already
extracted owned PS3 ARC to a self-contained GLB. The reader retains native
positions, normals, UVs, hierarchy, inverse binds, diffuse textures, and all four
or eight skin influences. Numeric joint names retain native animation-map IDs in
their metadata; semantic retargeting roles are not guessed.

```sh
python -m gbox.re5ps3_models /path/to/uPl00ChrisNormal.arc \
  --model 'pawn\pl\pl00\model\pl0000' --lod 1 --out /new/path/chris.glb
python -m gbox.re5ps3_models /path/to/uPl01ShebaNormal.arc \
  --model 'pawn\pl\pl01\model\pl0100' --lod 1 --out /new/path/sheva.glb
```

Output creation is exclusive. An existing output is never overwritten. LOD
masks `1`, `2`, and `4` select one native distance level, including primitives
marked visible at multiple levels. Other levels remain available by exporting
them explicitly. No original source is modified.

## Normal Models collection

Use the existing job/tool route `characters op=collect game_id=e7ca89bbeb67360d`.
`gbox.re5ps3_collection` registers exactly two targets: Chris Redfield and Sheva
Alomar in their normal player costumes. The catalog ID and PS3 platform must
match. The adapter accepts the owned folder, `PS3_GAME`, `EBOOT.BIN`, or the
catalog's `.7z`; it does not require a launched game or emulator process.

For the solid `.7z`, the adapter selects only the exact `PARAM.SFO`, `EBOOT.BIN`,
`uPl00ChrisNormal.arc` and `uPl01ShebaNormal.arc` under one unambiguous
`PS3_GAME` root. A single 7-Zip pass flattens these four members into
`<cache>/re5ps3-native/<source-key>`; unrelated files and the full game are not
unpacked. A new source path/size/mtime gets a new key. Failed extraction does not
publish a cache. Every target export rehashes the actual SFO, executable and its
character pack against the owned-build fingerprints. Folder members cannot
escape their PS3_GAME root. The outer 7z is identified by path/size/mtime, not
mislabelled with a content hash; actual member SHA-256 values are recorded.

Missing or corrupt character packs produce individual failed rows while the
other target can still collect. Models metadata retains source member paths,
actual hashes, platform/revision, archive/model resource identity, reader
version, native formats and explicit two-target coverage. Normal collection
exports LOD mask 1; the CLI still exposes all three validated masks.

These entries set `role_mapping_policy=explicit_only`. Reader version 2 supplies
18 body anchors verified against each exact native MOD by controlled offline
skin poses; it never guesses roles for other source hashes. Numeric joint names
remain intact. See [the role evidence and literal mappings](re5ps3-roles.md).
Normal collection reports two verified, retargetable models while preserving
`status=partial`, `roster_complete=true` and `full_cast=false`: these two targets
do not represent the full cast. The fixed-layout MOD/TEX batch writer remains
separate from arbitrary donor topology and gameplay acceptance.

The collection tests exercise real normal collection and preview verification,
readiness, independent GLB readback, reuse, source immutability, exact-build
rejection, per-target failure and a four-member 7z/cache round trip. Set
`GBOX_RE5_EVIDENCE` to the evidence root with `re5/**/PS3_GAME/PARAM.SFO` and the
three other owned files. No owned bytes are committed.

## Proven format details

The owned release is catalog game `e7ca89bbeb67360d`, PS3 `BLUS30491`, disc
VERSION `02.00`, APP_VER `01.00`. The model header stores version 156/revision 1
as big-endian `0x019c` (412 when read as one 16-bit field). This is not RE6's
Xbox 360 format.

Compared with the PC RE5 model structure, the verified PS3 differences include
64-entry bone palettes and a reversed packed `skinInfo` word: the mesh palette
selector is byte `+46`. Bone records occupy 24 bytes, followed by parent-space
and inverse-bind matrices, the 256-byte fallback map, and 68-byte palette
records. Material vertex declarations use the big-endian bitfield positions.
The stored index extent is `(header index count - mesh count) * 2`; each mesh
owns its explicit strip range. Restart markers reset parity; degenerate strip
indices advance it.

TEX resources use version 102, a 36-byte fixed header, an absolute mip offset
table, and linear DXT1/DXT5 blocks. Header values are big endian; DXT payloads
retain their little-endian block encoding. All mip extents are validated, though
the GLB embeds only the highest-resolution mip as PNG. Unsupported formats,
vertex declarations, bind inconsistencies, invalid weights, absent texture
references, overlaps, and resource-budget violations stop extraction explicitly.

Primary format references, checked against the owned bytes and independently
implemented here:

- [Albam MOD 156 description](https://github.com/Brachi/albam/blob/d1fda41beeae129fbb26128157511afdee4002ea/albam/engines/mtfw/structs/mod-156.ksy)
  and its mesh coordinate/weight interpretation (MIT).
- [RevilLib PS3 traits](https://github.com/PredatorCZ/RevilLib/blob/e17f9718ea571f040a7e1f331c28a4d45a6066b5/src/mtf_mod/traits.hpp),
  mesh/serialization declarations, and TEX 102 structure (GPL-3.0).
  Only binary-format facts were used; no upstream implementation is vendored.

## Owned-source verification

| Resource | SHA-256 | Verified model content |
| --- | --- | --- |
| `uPl00ChrisNormal.arc` | `51df8884b6a114101356e19fcc608b69c196e7c0cd56c626a3f7660aeb99d867` | 79 archive members |
| `pl0000` MOD | `d7ceb6b055b3854a27975f1609f758cd8e281611149e8fe0a96f53ea984776e6` | 130 bones, 162 native meshes; LOD 1 exports 103 primitives, 17,466 vertices, 18,633 triangles |
| `uPl01ShebaNormal.arc` | `27ce670e29438738d024e5ec5a7b729ea5da19eab98a668ada42da9630d92d6f` | 72 archive members |
| `pl0100` MOD | `99fe7f291a80c32be3440028c9eb7bbf2bb8ec565fea68473ca49766604a8dbb` | 147 bones, 179 native meshes; LOD 1 exports 93 primitives, 16,416 vertices, 18,070 triangles |

Tests export **both models at all three LOD masks**, independently parse their
GLB accessors/images, check every joint/index/weight, and confirm source bytes
remain unchanged. Parent-space matrices accumulated through the native
hierarchy agree with the inverse binds within `1.71e-5` (Chris) and `1.27e-5`
(Sheva). Independent Blender 4.0.2 imports and front/back offline renders show
both complete bind-pose characters with their textures. These are offline model
checks, not emulator screenshots or gameplay acceptance.

Set `GBOX_RE5_EVIDENCE` to the local audit evidence root containing the extracted
`re5/**/*.arc` files to run the owned-model test. The separate archive tests use
`GBOX_RE5PS3_ARCS` pointing directly to the folder with the two character ARCs.
No copyrighted model/texture data is committed.

## Sparse native group IDs

Mesh group fields refer to the 32-bit IDs stored in the native 32-byte group
records. They are not ordinal positions in that table. The reader preserves
the ID in mesh/GLB metadata, rejects IDs absent from the table, and rejects
duplicate table IDs. This corrects a reader failure on owned Josh (`0,1,3,5,20`),
Barry (`0,4,5`) and Rebecca (`0,8,9,10,11`) packs; all three now export at LOD
masks 1, 2 and 4 with their original numeric skeletons and source identities.

The seven-pack census and source/resource hashes are retained in
`re-export-evidence/re5-expanded-cast-v1/engineering-handoff.json` and attached
to original request1885. Set `GBOX_RE5_EVIDENCE` to that evidence root for
`test_re5ps3_group_ids.py`. No new semantic roles, collection entries or writer
targets are inferred from these exports. Other observed failures remain strict:
Jill's differing vertex range, referenced non-finite UVs in Jill/Wesker/Excella,
Irving's vertex-type4 declaration, and zero-bone effect MODs require separate
format evidence. The group-ID correction does not invent replacement UV values
or broaden supported vertex types.

## What remains for the requested modified export

This reader supplies editable native targets for fitting the user's randomly
chosen Sonic/Mario cast. It does not complete that export. Native engine shader
passes, normal/mask maps, texture color correction, and original blend behavior
are not reproduced by the preview material. The preview uses a 0.5 alpha
cutoff; original material flag, shader, blend-state, and alpha bytes are retained
in GLB metadata. Animation clips, semantic bone-role mapping, full NPC/enemy/
cutscene roster coverage, arbitrary-topology native MOD writing, retargeted motion acceptance,
an installable PS3 build, unlocks, and sidebar inventory/equipment controls still
need implementation and gameplay verification. No writer is registered and no
full-cast request should be closed because this reader passes.

The separate [bounded native writer](re5ps3-writer.md) now supports fixed-layout vertex edits and same-size TEX replacement in copied owned packs. It is not registered as a cast writer.
