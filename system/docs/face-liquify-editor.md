# Correct native face textures before baking

Open **Models → Liquify / lattice face editor**, or the same button beneath a
source selfie. In a DOA2 session, **Face texture editor** opens the same window.
Choose the saved photograph and a named fighter/costume face, then **Load original
face**. The current editor catalog supports the owned DOA2 Limited Edition Japan
disc. Other games' existing face editors remain separate.

The original native face is a fixed reference. The photo projection is a separate
layer: toggle either layer, vary the comparison opacity, zoom in, and choose
**Show original** to inspect the reference. **Liquify** pushes local photo
features in the direction of a drag; brush size and strength control its reach.
**Lattice** moves control points for broader proportional adjustments. Grids
cannot fold over themselves. Undo, redo and reset affect this face's deformation,
not the original photograph or the native mesh.

Local canvas feedback follows the drag immediately. The fixed native UV coverage
clips the photo layer. After a completed edit, the editor obtains a second preview
decoded from the actual native texture encoding. This preview can show native
resolution and compression limits that the local photo layer cannot. Existing
eyeball geometry, meshes, rigs, animation and original body proportions are not
changed by a 2D texture correction.

**Accept and save this face** stores an immutable mapping on Spark, bound to the
photo, original native texture, geometry, settings and encoded candidate. Selecting
a different face retains its own accepted mapping. **Load saved mapping** restores
that face's recipe. Merely viewing a preview does not approve it or launch a build.

**Build accepted faces for this photo** creates a separate disc containing exactly
the saved face recipes. Unreviewed faces retain their original textures. Changes
made after the last acceptance are not silently included. The writer recreates
and checks each accepted native payload before rebuilding; an old worker or changed
source requires a fresh inspection/preview. Builds appear in the normal Jobs and
Builds views for playback or download. Existing ROMs and saves are preserved.

Deformations store normalized forward lattice points and bounded Liquify strokes.
The browser and Python renderer use the same inverse sampling and premultiplied
bilinear interpolation. The native projector composites only the photo layer,
preserves original alpha, and protects pixels outside reviewed face triangles
before encoding. DOA2's native VQ encoder can quantize other pixels within the
selected face texture; those changes are visible in the decoded candidate.
Other native texture payloads remain unchanged. Source
photographs are not regenerated, and no corrected likeness is automatically
accepted on the operator's behalf.

The [validation receipt](native-face-editor-validation.json) records an actual
owned DOA2 texture round-trip and distinguishes it from browser fixture tests.
