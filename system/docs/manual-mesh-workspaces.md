# Editable geometry and shoe fitting

Use **Jobs > Review mesh > Editable Blender workspace**, or **Fit & textures > Geometry approval >
Editable Blender workspace** for a library character. The job returns a downloadable `.blend` artifact.
It never launches an emulator, changes the running game or overwrites a library donor or ROM.

The EDIT collection contains the rigged library donor with materials and gBox round-trip tags.
An untouched source copy is hidden in REFERENCE. When opened from a fit job, the complete saved before/after
pair is also imported as hidden references, with its job, donor, target slot and allocation measurements.
An expired or old pair cannot be reconstructed: the donor workspace can still be exported.
Fitted snapshots have target coordinates and no editable donor rig; do not send them back as a donor.

The reduction modifier starts disabled at ratio 1.0. Detail protection and reduction masks are editable
vertex groups, initialized from head/hand/foot influences. A collapse mask guides reduction; it does not
guarantee that silhouette, UV seams, volume or animation survive. Work on the EDIT mesh, keep the reference,
and inspect difficult joints and silhouettes. Hard Ops DICE can be used if installed; the workspace does not
install it, apply it automatically, or imitate it. Cutting adds topology and consumes the game's vertex budget.
Blender's own Knife/Bisect/loop cuts are also available. Notes can be kept in the scene's `gbox_review_notes`
property and submitted, with marked images, through the mesh review report.

Return only the selected EDIT armature and meshes using the gBox add-on, or export a GLB with custom properties
and import it as a new character variant. Changes to guide empties are explanatory and are not silently
converted into retarget settings. Set those settings in the fitting editor and save for the target game/slot.

## Stop automatic reduction

Save **No automatic geometry reduction** on the edited donor's target profile before building.
The shared Ninja writer (including JGR), SC2, DOA2 and FF7 attempt the full edited geometry. If native allocation
or index limits reject it, the build stops with that error and saves comparison evidence where available.
They do not quietly reduce it again. Other writers do not yet honor this control; the editor names that scope.
This setting controls topology reduction, not native vertex quantization, material packing, texture allocation,
retargeting, supported influence counts or game performance. It is not proof that a native build will look correct.

## Separate shoes from legs and specify ground

In **Goals**, assign distinct shin and foot bones and move each ankle pivot onto the ankle, not the sole.
Enable **Specify shoe boundaries**. Left/right sliders set the shoe's upper plane as a fraction of source body
height above its lowest body point. Same-side leg vertices below that plane become foot vertices; vertices
incorrectly owned by the foot above it return to the shin. Props and the other side are excluded. Source axes
are converted through the donor-facing frame; the shared retargets apply the same correction before fitting.
Missing or aliased shin/foot roles cause an explicit error rather than a guessed whole-leg shoe.

**Ground lift** positions the target sole plane; **Plant mesh feet at reference ground** aligns the fitted sole
to it in the preview pose. Shoe boundaries, ankle pivots and foot proportions remain separate controls.
Both soles, walking, crouching and attacks need native checks: this is not animated foot IK, collision editing,
or a promise to prevent every sliding contact. Original profiles and builds remain unchanged until saved and rebuilt.
