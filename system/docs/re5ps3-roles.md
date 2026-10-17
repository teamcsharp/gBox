# RE5 PS3 exact-source offline body roles

Reader version 2 exposes eighteen body anchors for each original Chris/Sheva
normal model. It keeps native numeric joint names and attaches a separate role
map. Roles are returned only when the entire native MOD matches one of these
SHA-256 identities:

- Chris: `d7ceb6b055b3854a27975f1609f758cd8e281611149e8fe0a96f53ea984776e6`
- Sheva: `99fe7f291a80c32be3440028c9eb7bbf2bb8ec565fea68473ca49766604a8dbb`

Unknown or edited model bytes get no automatic roles, even if their skeleton
looks identical. The collection retains `role_mapping_policy=explicit_only`.
Cached version-1 entries are re-extracted through the exact-build source gate.
Two collected models can be retargetable while full-cast coverage remains
partial; `roster_complete=true` records completion of this two-target subset.

## Controlled evidence

Each original textured GLB was imported into ARM Blender 4.0.2. One named
native joint at a time was translated +0.35 metres along world X, with all
other pose transforms restored to their original state. The evaluated skinned
mesh was baked to an independent static GLB. Eighteen controls plus a baseline
were generated for each model. Original source bytes were retained.

The independent check walks the native parent links, sums each vertex's
weights assigned to the selected joint or its descendants, and predicts
`position + weight_sum * (0.35, 0, 0)`. Every referenced vertex in each baked
Blender mesh has a native predicted point within 0.00005 metres, and conversely.
Blender's mesh validation removes repeated faces that use the same native
vertex indices, irrespective of winding: 30 for Chris and 2 for Sheva. The
baked counts are consequently 18,603 and 18,068 triangles, and every controlled
pose must equal its native count after that exact index-face deduplication.
The original native files and source GLBs retain all their faces. The largest measured witness distance was
0.0000003621 metres for Chris and 0.0000003185 metres for Sheva. This checks the
native palette/joint identities and all four/eight weight influences against
Blender's independent skin evaluation.

All six contact sheets were visually reviewed. The controls isolate the body
regions below; native joint world positions, parent chains and weighted-region
bounds corroborate them. Character-left is positive native X in the front-facing
source model. An animation-map number is recorded as corroboration, never used
to assign a role to an unknown source.

| Body anchor | Chris native joint | Sheva native joint | Native animation map |
|---|---:|---:|---:|
| Pelvis/hips | 111 | 1 | 15 |
| Upper torso/chest | 2 | 21 | 2 |
| Neck | 3 | 22 | 3 |
| Head | 4 | 23 | 4 |
| Right clavicle | 45 | 78 | 5 |
| Right upper arm | 46 | 79 | 6 |
| Right forearm | 50 | 85 | 7 |
| Right hand | 54 | 88 | 9 |
| Left clavicle | 75 | 107 | 10 |
| Left upper arm | 77 | 108 | 11 |
| Left forearm | 79 | 112 | 12 |
| Left hand | 81 | 115 | 14 |
| Right thigh | 112 | 2 | 16 |
| Right lower leg | 113 | 3 | 17 |
| Right foot | 114 | 4 | 18 |
| Left thigh | 117 | 8 | 20 |
| Left lower leg | 119 | 9 | 21 |
| Left foot | 120 | 10 | 22 |

The exact-source tests distinguish Chris joint 4 (head) from Sheva joint 4
(right foot), verify hierarchy/side/weight evidence, and refuse a changed model
hash. The optional owned-pose test consumes `blender-proof.json` and its static
GLBs from `GBOX_RE5_ROLE_POSES`, plus native MODs in `GBOX_RE5_EVIDENCE`. It
recomputes the independent weighted point checks rather than trusting a stored
pass flag. The local proof directory is `re-export-evidence/re5-role-pose-proof-v3`.
No owned model or texture bytes are committed to the repository.

## Scope

These roles describe observed offline skin/body regions for fitting. They do
not prove native animation clip semantics, stance, weapon grip, motion retargeting,
engine shader/culling behavior or gameplay. Helper/facial/accessory joints keep
their numeric identities. Full cast replacement still requires donor fitting,
native topology/bounds/tangent engineering and game acceptance checks.
