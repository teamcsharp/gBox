# Native photo faces and the PSO live mapper

Photo face builds retain the game's original bodies, head meshes, skin weights,
skeletons and animations. They bake a supplied photograph into reviewed native
face texture regions. These writers do not retarget or decimate a Leon body.
Every output has a unique destination, native encoded before/after comparisons,
source photo lineage and an explicit coverage report. File validation does not
establish likeness, correct animation or complete cutscene coverage.

The typed tools are `gta3_faces`, `twin_snakes_face_build`, `doa2_face_build` and
`pso_face_build`. The latter three offer `op=plan` to inspect supported native
surfaces before building. Revision and source material identities gate the
writers. A new game revision requires its own verified profiles. Photo artifacts
must match their SHA-256 and stay within the image size limits.

## PSO: edit, inspect and keep a mapping

On a supported running GameCube PSO session, click **Face paint**. Choose the
current class/head/hair explicitly, or select a named NPC surface. Inspect reads
resident native texture bytes and offers only exact matches. It does not infer
the current class, NPC identity or correct face placement from a screenshot.

Choose a photo from Faces, or upload one. Adjust crop, translation, scale,
rotation, opacity and feather. Choose an ellipse or rectangle mask and paint
erase/reveal strokes on the UV texture or a verified reference mesh. The face
island selector retains separate projections when a native atlas has multiple
face regions. Original/result/overlay views and UV wire help compare placement.
The wire is never baked into the texture.

Every completed preview is decoded from the native encoded candidate. Choose
one exact resident address, then **Apply in this game**, or explicitly enable
**Live in game** to apply successive completed previews. Commands are pinned to
the session, expire, compare the current allocation before writing, pause only
when necessary and verify the bytes afterward. Unknown results are not retried.
Shared native textures can affect multiple meshes. A changed/unloaded allocation
requires a new inspection. RAM verification does not certify a rendered frame.

**Save mapping and mask** stores the reviewed photo/surface projection on Spark.
**Build saved face mappings** queues a separate owned disc on the Spark worker.
Unsaved changes are not part of that build. A face build carries original native
face chunks so later editing starts from the native texture rather than layering
another photograph over the already baked result. Restore returns the inspected
session's initial bytes, which can themselves belong to a photo build.
Reopening a photo build retains that build's pinned photo and mapping. **Load
latest saved mapping** explicitly loads a newer master recipe for comparison.

Right-click a person and choose **Inspect / paint face** to use the actual
captured draw under that point. This needs a session launched with Examine 3D /
RenderDoc capture support. The editor does not restart an uninstrumented game.
It rejects letterboxing, missing geometry and textures that do not match native
decoded texels. Captured geometry is a static draw, not a verified actor identity.
NPCs without a verified mesh binding remain available as 2D native textures;
the UI does not substitute an unrelated model.

The current live implementation requires the verified offline GameCube PSO Plus
US revision 2 executable. Dreamcast PSO is not supported by this face channel.
The Models collection groups the exported native photo variants under their
source selfie, with real GLB download/export and inspection.

## Native build scope and playback

- GTA III PS2 SLUS-20062: rigid head UVs for native player outfits, pedestrians
  and special/cutscene actors. Palette entries used by unmasked pixels remain
  unchanged; limited spare palette space can produce visible banding.
- Twin Snakes GGSEA4: reviewed native head materials in each disc's `stage.dat`.
  Codec portrait components, `demo.dat` streams, unreviewed/fully helmeted faces
  and stages exceeding their fixed compressed slots are reported as gaps.
- DOA2 Limited Edition Dreamcast: reviewed native fighter/costume face banks.
  The unbound YTI00 story archive, roster portraits and prerecorded videos are
  outside the current verified head projection coverage.
- PSO GameCube: named primary player/NPC face banks and identified area/quest
  container copies. Robot head geometry remains original. Generic unnamed body
  atlases are not automatically painted as though they were known NPC faces.

Use a cold boot for a new disc. An old GameCube savestate can embed the original
FST and stale texture allocations even when a different ISO is mounted. It must
not be presented as an exact compatible checkpoint for a build whose disc files
moved. Native proof reports distinguish cold boots, copied-state experiments,
actual disc loads, RAM evidence and visual review.

## Inventory

The supported GTA III PS2 Sessions sidebar exposes **Weapon inventory**:
refresh, give a selected weapon, or give all 11 ordinary carried weapons. It
uses the native model streaming and GiveWeapon functions after executable
fingerprints and initialized inventory checks, then verifies native slots and
ammunition. A failed or uncertain mutation blocks further commands until a
successful refresh. Mission objects and functioning detonators require their
native game flows; they are not a generic inventory grant.

PSO keeps its existing native item/inventory controls. Twin Snakes inventory
codes remain unverified candidates and are not exposed as working native
inventory operations. DOA2 has no RPG item inventory; these face builds do not
claim to unlock unverified costumes or roster flags.
