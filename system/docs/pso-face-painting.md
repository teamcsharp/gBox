# Live PSO face painting

In a running GameCube PSO session, choose **Face paint** in the session header.
Select the current class/head/hair, then **Inspect current session**. Select a
resident face texture (HUnewearl face names contain `kao`) and one exact address.
The 3D reference uses the selected class/head/hair; it is not a capture of the
current animation, costume proportions or pose.

Choose a saved image from Faces or upload one. Drag its crop, adjust placement,
scale, rotation, opacity and feather, then paint an erase/reveal mask on the UV
image or enable **Paint mask on mesh**. Select the corresponding 3D material
(`tex101` is the default human face material). Previews are decoded from the
actual native GVR candidate, including native CMPR quantization. Untouched
compression blocks remain byte-identical; edited CMPR 4×4 blocks can quantize
neighboring pixels within that block.

**Apply in this game** pauses only an actively playing emulator, compares the
complete expected resident texture, writes the same-length native texels and
verifies the readback before resuming. An already paused game remains paused.
Restore original reverses that session edit. Apply completed previews while
editing is an explicit opt-in, disabled by default. Both the PNG and native GVR
can be downloaded. The source photo, projection settings, painted mask and
native candidate remain archived on Spark.

Only exact fingerprinted PSO Plus US GameCube revision 2 offline free-play is
currently supported. Writable formats are I8, RGB565, RGB5A3 and CMPR without
mipmaps. The owned HUnewearl bank has 24 CMPR face/ear entries; its default face
is `plBtex.afs` entry 242, `pxtBf_01d_t_kao`, 64×64. Other classes are inspected
from their own tables. No automatic face recognition or inferred 3D geometry is
used. Source ROMs and memory cards are not modified.

Resident data can have multiple exact matches; selecting one address is required
in that case. Other meshes sharing the chosen native texture can also change.
Unloaded/recycled allocations, stale source workers, unknown pause states,
expired commands and mismatched session candidates are rejected. Session
lineage is stored independently of content-addressed artifact metadata so two
sessions can safely reference identical images.

A verified RAM readback does not prove a rendered face looks correct. Dolphin
must upload the changed texture, and visual alignment still needs in-game
inspection. The 3D editor is a reference preview, not a native gameplay result.
Changes are temporary session RAM edits; a persistent rebuilt ROM writer is not
part of this workflow. Native checkpoint captures retain the changed texture,
while standalone paint-action replay is explicitly marked unavailable.

Validation: `tests/test_pso_faces.py` checks native formats, untouched blocks,
independent session lineage, address/header guards, pause/resume and restoration.
`tests/test_pso_face_editor_ui.cjs` checks review/application, stale replies,
closing and UV/mesh strokes. The UI screenshot is explicitly labeled a fixture
with a stubbed renderer. A native gameplay face-change screenshot has not yet
been verified.
