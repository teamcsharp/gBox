# Native PSO photo faces

`gbox.pso_face_build` creates a separate GameCube PSO disc with photo textures on
the original characters. It does not replace their bodies, heads, skeletons,
weights or motions, and it performs no mesh reduction.

The `pso_face_build` tool accepts `op=plan|build`, a catalog `game_id`, a registered
photo artifact SHA in `photo`, an optional `name`, and optional `profiles` keyed
by stable native surface ID. Builds retrieve reviewed profiles from the photo
recipe endpoint before applying explicit per-call overrides. The tool runs on
Linux where the central native asset collection lives; it never launches a game.

The owned GPOE8P source currently exposes 724 selected native surfaces:

- 660 player primary face maps, covering all twelve classes and five head choices
  for each android class, with the original color/skin variants retained.
- 64 NPC face/visor surfaces, including loose GVMs, named NPC BMLs, the extra
  S–Y banks, city/lab GSL copies and the named Chao/NiGHTS quest packs.

All 46 modified disc files are independently reread. The other 3,464 files remain
byte-identical; native CMPR format, dimensions, GVR headers and untouched
compression blocks are retained. BML rebuilds compare every decompressed mesh
and motion to the source, and GSL rebuilds compare every unrelated inner file.
The original full disc hash is checked separately by the private build proof.

This count covers the explicit native naming inventory. It is not a claim that
every possible event, downloaded quest or unrecognized atlas has been identified.
`coverage_gaps()` reports actual unmodified named NPC containers. Original robot
helmets remain robot helmets; photo/visor patches are experimental and require
visual review. Prerecorded movie faces are unchanged.

## Editing and portable provenance

`surface_catalog(disc)` returns stable locators for AFS/GVM/BML surfaces, including
`archive_entry` for packed GSL copies. `read_surface()` returns their native GVR
bytes. `export_surface_reference()` exports only an explicit original class/head
or BML model binding; an unbound NPC texture does not produce a guessed avatar.
Class references bind the exact selected skin/color face variant to its original
head material rather than silently showing the default skin.

A profile retains photo crop, destination quad, opacity, feathering, ellipse or
rectangle mask/inset and ordered destination paint strokes. Erase strokes restore
the original; later restore strokes reenable the projected result within the
projection mask. Mixed atlases can carry up to eight explicit `additional_patches`.
Class/head defaults are starting points for review, not automatic likeness proof.

The build marker keeps `photo_faces.source_photo`, per-surface profiles, source
image and standard before/after mesh preview pairs. Every original chunk travels
with the build in the single `face-originals.zip` archive as `{surface_id}.gvr`,
with at most 2,048 entries and 256 KiB per entry, so staged Windows copies can
preview from clean source bytes without a Spark-only filesystem path. The live
editor must compare against current-build texels while painting from this clean
baseline. Older directory-based originals remain readable by the editor. Native
preview frames are texture projection on an unchanged mesh;
they do not depict inferred face deformation.

Builds register 36 actual native GLBs under the selfie tag: 28 class/head
references and eight explicitly bound NPC BML references. Unbound REL-driven
NPCs remain available as texture surfaces; an exact captured draw mesh is needed
for their 3D reference. Exported models have unique build-linked collection slugs.

## Validation limits

The private Spark proof used its own Dolphin process, Xvfb display, cards and a
copied state. A native Pioneer 2 load verified 28 modified NPC texel payloads
byte-for-byte resident from the new disc and produced a native world screenshot.
This is area-loader and native texture evidence, not a completed gameplay run or
approval of every face's likeness. Static native-mesh comparisons are supplied
for per-character crop/mask review. No operator PC or production save was used.

An old GameCube checkpoint contains its original cached filesystem table. When
NPC archives grow and relocate, replaying that state against a modified ISO can
read old slots until the cached table is synchronized. The private proof first
required an exact match to the original FST, then installed the actual new disc's
same-length FST before requesting a native area load. This fixture step is not
an automatic production compatibility promise and does not make a modified run
an exact TAS. Cold boot is the normal launch route for these builds.

Bounds: 8 MiB uploaded photo, 12 megapixels decoded, 64 MiB native inner container,
4,096 GSL table entries, 256 MiB per rebuilt area archive, 512 MiB changed assembly
data, 4,096 paint strokes and eight atlas patches per surface. Build assembly
requires a source-image copy plus 4 GiB disk headroom and never overwrites a named
existing build.
