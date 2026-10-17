# Local editable HOps topology workspaces

In **Review mesh reduction** or the retarget editor's **Geometry approval**,
choose **Local HOps 2D node cuts**, **3D node cuts**, or **Experimental voxel
study**, then request an editable Blender workspace. The original mesh option
remains available without Hard Ops. Each workflow follows its own worker job
and produces a downloadable `.blend` with packed textures and source references.

The worker uses the operator's local `C:/_tools/HOps` installation, configurable
with `GBOX_HOPS_PATH`. It imports the installed HOPS_Boolean node asset without
enabling the complete UI add-on or changing Blender preferences. The current
local asset requires Blender 4.5 or newer. An older Blender fails explicitly;
gBox does not install a different Blender or modify the open Blender instance.

Select **DICE GRID** and edit its **Cuts X/Y/Z** custom properties. Two-dimensional
cuts start on X/Z; the 3D preset includes Y. Counts range from zero to six per
axis. Translate, rotate or scale the grid to place the planes. Zero counts bypass
the nodes and restore the source topology. A sequence of individual node knives
avoids passing intersecting open cutters into a single boolean operation.

Dicing **adds** topology; it does not reduce triangle counts or expand a game's
native allocation. New vertices receive weights and UVs from the preserved
source while original vertex weights remain intact. Review the face, shoes,
joints, UV seams and silhouette before enabling the existing masked reduction
modifier. Native triangle/cache/byte limits still apply. Export only the reviewed
EDIT character, with modifiers applied, and return it as a new donor variant.

The voxel preset leaves EDIT unchanged and makes separate hidden study meshes
with disabled Remesh modifiers. Deliberately reveal and enable a study, adjust
voxel size/adaptivity, and inspect detail, UVs and skinning. It is an experimental
workspace, not a validated remesh or automatic native import.

The operator's local Blender 5.4 was tested in separate factory-startup background
processes. A closed cube retained its volume and weighted new vertices through
live 2D, 3D and zero-cut changes. The owned Amy donor retained seven source meshes,
1,384 original triangles and its 62-bone hierarchy after export of each preset.
These are offline checks; they do not approve the failed JGR prototype or a new ROM.
