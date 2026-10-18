# RE5 PS3 experimental exact-donor fitting

`gbox.re5ps3_fit` creates a new native ARC for either the original Chris normal
pack with the owned Sonic donor, or the original Sheva normal pack with the
owned Peach donor. It verifies the source hashes, fits every mapped skin
influence, writes MOD/TEX, and reads every ARC resource back before publishing
an exclusive output. It does not install assets, touch saves or launch a game.

This is offline engineering evidence for two body replacements. It is not a
full-cast or gameplay-approved writer and is not registered as one in
`char_coverage.WRITERS`. Existing fixed-layout and multi-resource editing stays
available through [re5ps3_write](re5ps3-writer.md).

## Exact sources and commands

Target game: `e7ca89bbeb67360d`, PS3 BLUS30491, Gold USA v02.00.

| Target | Original ARC SHA-256 | Donor |
|---|---|---|
| Chris normal | `51df8884b6a114101356e19fcc608b69c196e7c0cd56c626a3f7660aeb99d867` | `sa2_super_sonic`, visibly blue Sonic, **not super-yellow** |
| Sheva normal | `27ce670e29438738d024e5ec5a7b729ea5da19eab98a668ada42da9630d92d6f` | `sm64ds_peach`, Princess Peach |

The donors were selected reproducibly from the owned Sonic/Mario library using
the lowest SHA-256 score of `order2396:re5ps3:first-fit:TARGET:SLUG:GLBSHA`, among
the inspected rigged candidates with at most 2,000 triangles, one per family.
The candidate inventory and selection are retained in the local proof, rather
than silently choosing new models when a library changes.

Sonic comes from game `d95ed7ed1e40552a` (Dreamcast Sonic Adventure 2 USA),
`SONIC2/SSONICMDL.PRS` and `SONIC2/SSONICTEX.PRS`. The accepted donor GLB hash is
`a2fe5100cb09202f7f470fa0abcbb0ba4f47d8f9c4b211db3cb2a20ff8a62246`.
Peach comes from game `917483267d246594` (Super Mario 64 DS USA),
`data/enemy/peach/peach_high.bmd`. Her accepted GLB hash is
`2437b114788a6a75de1ab1995a2d484eeade85b7d1b97f79dd38b692b3f78d73`.
Changing a donor, target pack or native model requires new evidence; filenames
or character labels cannot substitute for these byte identities.

```sh
python -m gbox.re5ps3_fit OWNED_CHRIS.arc --donor-glb EXACT_SONIC.glb \
  --expected-sha256 51df8884b6a114101356e19fcc608b69c196e7c0cd56c626a3f7660aeb99d867 \
  --out NEW_CHRIS.arc
python -m gbox.re5ps3_fit OWNED_SHEVA.arc --donor-glb EXACT_PEACH.glb \
  --expected-sha256 27ce670e29438738d024e5ec5a7b729ea5da19eab98a668ada42da9630d92d6f \
  --out NEW_SHEVA.arc
```

The CLI prints a JSON receipt with native source/donor identities, counts,
fit bounds, foot spacing, source-to-native joint mapping, texture error, output
hash and explicit limits. Existing output files are never overwritten. All
conversion and readback occur before publication, using the same exclusive
NTFS/ext4 hard-link publication as the bounded writer. A failure leaves the
requested output absent. The API `build_fitted_archive` constructs bytes in
memory; `fit_archive` validates unchanged input files and publishes the result.

## Fit and native encoding

The target uses the 18 [exact-source native body anchors](re5ps3-roles.md).
The source loader retains all glTF influence sets. Each source joint resolves
through its actual parent chain to the nearest explicit donor role (unassigned
roots resolve to hips); all weights for the same target joint are summed. An
independent check compares the complete mapped weight distribution per vertex.
No strongest-joint reduction or triangle decimation is performed.

The fit anchors the donor head joint to the native head and retains donor head
proportions. Its total height can exceed the original body: camera and gameplay
clearance have not been established. Sonic's rigid boots preserve donor up/front
orientation at the native ankle, with positive axis scales that keep them above
the original ground and leave at least 10% of the ankle separation between
their X bounds before native quantization. Unsupported blended boot correction
fails explicitly. Peach has no rendered leg/foot geometry controlled by her six
leg roles; those identities are retained but are not visually proven anatomy.

One atlas bakes each donor material's repeat, mirror or clamp behavior, color
factor and binary alpha. Source triangles remain in order. Explicit double-sided
donor materials receive reversed-winding back copies with reversed normals.
Sonic remains 1,369 triangles; Peach has 798 source triangles plus 215 required
back copies. Texture encoding is lossy DXT1/DXT5 with all native mips read back.

`re5ps3_topology.replace_body` replaces the entire draw list with one four-weight
mesh using LOD mask 255, so the replacement appears in every included LOD.
It retains the original native skeleton records, local and inverse bind matrices,
parents and animation IDs. It writes quantized positions, normalized byte weights,
native joint palette, UVs, normals and UV-derived tangents. Weight conversion uses
deterministic largest remainder to a byte sum of 255; tests bound each influence
error by 1/255. Native vertex limits, finite data and exact source roles are checked.

The new mesh uses a proven original group-0, textured four-weight layout:
Chris mesh 25/material 18 (`pl00Harnes_BM`) or Sheva mesh 40/material 15
(`pl0100_05Arm_BM`). The original material shader, normal map, mask map and
unknown vertex/descriptor fields are retained. This is a significant runtime
uncertainty: successful diffuse GLB rendering does not reproduce those shaders.

The encoder writes new model/group spheres and per-weighted-bone bounds. Each
144-byte envelope contains a bone ID, 12 opaque bytes, sphere, AABB and oriented
box in inverse-bind bone space. Existing opaque bytes for that exact joint are
preserved. New directly weighted joints without an original envelope get zero
opaque bytes, identified in the receipt (Chris 46/50/77; Sheva 79/85/108/112).
Independent tests prove the quantized points are inside all three geometric
bounds. Runtime interpretation of the opaque fields and new envelopes remains
unverified. Original mesh/vertex/index bytes remain unchanged as orphaned
sections; offsets point to the appended replacement. Unknown header fields,
including `num_edges`, retain their original values. No compression or resource
identity is guessed from a filename.

## Evidence and remaining work

Owned evidence lives under `re-export-evidence/re5-donor-fitting-v1`. The
selection snapshot records source metadata and hashes. `donor-poses` contains
32 Blender controls checked against complete descendant-weight predictions.
`peach-joint-comparison-v1` contains 14 source/native baselines and shoulder,
elbow and wrist rotations, independently recomputed from source weights and
pivots. Both arm sheets were visually reviewed: the thin silhouette is present
in the original DS source and the native controls move the same body regions.
`native-first-fit-v6` retains the visually reviewed MODs; the integration tests
require the formal CLI's MOD bytes to match those exact reviewed artifacts.
`formal-fit-v1` contains actual CLI-created ARC/GLB previews and JSON receipts.
No owned models, textures or game bytes are committed to the repository.

Tests check all mapped source weights, source/backface counts, unchanged skeleton,
every unrelated ARC member, native envelope containment, finite positive scale,
ground and foot bounds, actual CLI publication, wrong-source no-output behavior,
and independent weighted pose prediction. Set `GBOX_RE5_EVIDENCE` to the owned
evidence root to run those integration checks.

Format evidence was cross-checked against the owned PS3 bytes and primary
[Albam MOD156 definitions](https://github.com/Brachi/albam/blob/d1fda41beeae129fbb26128157511afdee4002ea/albam/engines/mtfw/structs/mod_156.py)
and [RevilLib mesh definitions](https://github.com/PredatorCZ/RevilLib/blob/e17f9718ea571f040a7e1f331c28a4d45a6066b5/src/mtf_mod/mesh.hpp).
The PS3 descriptor's envelope count is byte 47 and palette is byte 46; PC
packed-field order is not copied blindly. The implementation is independent.

This stage does not establish native group visibility, culling, motion, weapon
grip, camera clearance, shadow/material behavior or gameplay. It covers two
normal player models, not other costumes, NPCs, enemies or cutscenes. A complete
modified game, verified installation, unlocks and live sidebar inventory/equip
support remain separate requirements. Original request 1885 remains in progress.
