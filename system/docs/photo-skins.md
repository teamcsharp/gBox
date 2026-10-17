# Photo / selfie skins and demonstration builds

Open a character's Retarget editor and expand **Photo / selfie skin**. Upload a
JPEG, PNG or WebP, enter the person's/avatar's name, drag a crop on the photo and
a destination patch on the selected UV color map. Rotate the patch when the
native face atlas is sideways or upside down. Select all maps that share that
same layout. Prepare, inspect the candidate on the 3D model, and accept or reject.
Acceptance creates a separate donor; the original remains unchanged. The existing
Blender export/round-trip handles the accepted model as a self-contained GLB.

## Selfie model collections

The **Models** tab groups custom models under their exact source image, showing
the image, an editable tag name and a stable `selfie:<image hash>` tag. The
**Selfie models** button in a game's Models screen opens the same collection.
Search and image selection update immediately. Existing approved photo donors
are included without recreating them. Accepted donors, their Blender/derived
edits and saved `targets/*.glb` / `targets/*.gltf` fitted models stay together.
Two different images of the same person remain separate; names are not identity
matching. Pending/rejected previews are not library models.

Each asset offers **Analyze / 3D**, **Export to Blender** and **Download GLB**.
Analysis opens the rotating model with mesh, vertex, triangle, bone and texture
counts. This is model inspection, not a claim of game compatibility. Downloads
and Blender exports bundle companion buffers/textures into one GLB. The existing
local worker writes Blender's clipboard; Ctrl+V pastes it in a Blender viewport.
Model exports retain gBox round-trip metadata, with photo donors as the edit's
parent so edits do not return to the unmodified source character.

`GET /api/photo-skins/collections` lists groups. `POST
/api/photo-skins/photos/{photo}/label` saves a tag name. `GET
/api/photo-skins/collections/{photo}/models/{slug}/download` downloads a packed
GLB; `POST .../export` stores that packed GLB as an authenticated artifact for
Blender. Both accept optional `file=targets/name.gltf` and validate photo lineage,
file confinement and a 64 MiB packing budget. Collection names and images stay
in private gBox data; they are not published to GitHub.

Selfies, generated pictures and saved internet images use the same file workflow.
There is no face recognition, biometric embedding, automatic landmark detection,
background removal, or reconstruction of a new 3D head. This projects source photo
pixels onto an existing mesh. Its head shape, hair, silhouette and facial animation
remain the selected character's. The UV mapping needs visual review for likeness.
Vehicle/prop entries with color maps can use the same projection API; a native
vehicle replacement writer is still required to put that asset in a game.

## Data and review

The `photo_skin` agent tool can upload an operator-supplied image path, prepare a
candidate, read its review and plan demonstrations. It returns hashes/metadata,
not base64 photo bytes in the model context. Acceptance remains a separate action.
`POST /api/photo-skins/photos` accepts a bounded image data URL and source kind.
Inputs are limited to 8 MiB/12 megapixels, EXIF-oriented, normalized to at most
2048 pixels per side, and stored privately in gBox's authenticated artifact store.
EXIF metadata is removed. Photos are never put in the source repository or public
PR evidence. No external face-generation service is called.

`POST /api/characters/{slug}/photo-skins` takes `name`, `photo` (uploaded hash),
`maps`, normalized `crop: [left,top,right,bottom]`, `quad` (four UV corners in
source TL/TR/BR/BL order), feather and opacity. Each map keeps its size and alpha;
only base-color bindings change. Geometry, weights, nodes, normal/data/emissive
maps, and the original file remain unchanged. Model/candidate size is bounded to
64 MiB, selected maps to four megapixels each and 16 maps per operation.

`GET /api/photo-skins/{id}` returns the review. `POST .../decision` accepts
`accept` or `reject`. Approval checks source/candidate hashes and ownership, clears
stale target rigs/readiness/native-player flags, creates a new donor, and remains
idempotent. Repeating a candidate preserves an existing variant and its targets.
Prepare another face from the original donor rather than layering projections.
Separate animation-bank references are cleared rather than pointing at files that
were not copied into the new donor; native target-game animations remain unchanged.

The retarget editor's rebuild button remains blocked while either a photo or an
enhancement candidate is pending. Approval is not a claim of gameplay verification.

## Main-character lock and cast roulette

`characters op=cast_swap` accepts `lead_character` (exact library slug) and
`lead_slot` (default `player`, including the writer's player alias). This donor is
removed from the supporting roulette pool, then locked onto that slot after other
assignments. Seeds and supporting edits cannot remove it. An unbuildable player
slot is rejected; the lead is never silently placed on an enemy instead. Photo
variants do not silently replace the original Leon in unrelated cast selections.
Claiming these jobs requires matching immutable process-start source hashes from
the worker. Older workers cannot silently ignore the new lead fields. A safe
worker refresh is required; recipes wait intact in the queue until then.

`POST /api/photo-skins/{review}/demo-plans` takes up to ten catalog `game_ids`,
`supporting_sources` (default owned Twin Snakes and DOA2 collections) and a seed.
It persists per-game plans/gaps, **without submitting or launching jobs**. Existing
operator reports still need review at build submission. Single-slot writers
report `unsupported_cast`; their optional player-only diagnostic is explicitly
distinct from the requested combined cast. Native and cinematic coverage need
their own runtime evidence.

## First Bla experiment and six requested targets

The original source is the operator's private `samples_grabbed/user/selfie/bla.jpg`.
A preview donor and a separate RE4 GC disc have been assembled. This is a photo
skin on Leon's existing head, not a new scan of Bla, and is not yet verified playable.

| Target | Current result / gap |
|---|---|
| RE4 GC USA Disc 1 | Native texture-only photo-skin image built. Four Leon packs keep their sizes; every non-TPL resource is byte-identical. Supporting cast not included; gameplay validation pending. |
| RE6 Xbox 360 | Player-only Bla diagnostic assembled (five costumes, 27 files). No combined cast path or verified Bla gameplay run delivered. |
| PSO GameCube | HUmar-only diagnostic requested. Combined cast and gameplay verification remain pending. Dreamcast player output has a known not-working gate. |
| Mario 64 owned supported layout | Player-only Bla diagnostic assembled (7,980 source triangles reduced to 1,595; eight textures). Visual/runtime validation still pending; combined cast unavailable. |
| Vice City | Current writer needs a classic PC `models/gta3.img` install. The owned Definitive Edition / PS2 versions need different writers; no compatible build delivered. |
| GoldenEye N64 | Inventory/file-table work exists; no routed character replacement writer or playable photo build delivered. |

For approved photo variants of the original extracted `leon`, RE4 GC uses
`re4_photo_skin` instead of the generic body retargeter. It matches original color
pixels, re-encodes native CMPR maps/mips in place, keeps original texture dimensions,
headers/offsets/pack sizes, and verifies all non-TPL resources byte-for-byte. There
is **no decimation or skeleton rewrite**. Existing matching Leon costume/face packs
are covered; other cinematic resources and prerecorded movies are not implied.
This texture-only path refuses non-identity shape adjustments rather than silently
discarding the user's edited geometry goals.
