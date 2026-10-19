"""Blender headless: import a fitted .glb and save an editable .blend with the decimation left to the operator, so
they can adjust reduction and preserve volume/geometry instead of the writer collapsing the mesh to fit a native
allocation. Face / neck / hand / finger / foot / toe vertices get a `gbox_protect_detail` group and everything else
a `gbox_reduce_allowed` group; the COLLAPSE modifier starts DISABLED at ratio 1.0 (no reduction).

  blender --background --factory-startup --python gbox/editable_blend.py -- in.glb out.blend <name>
"""
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
src, out, name = argv[0], argv[1], argv[2]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
PROTECT = ("head", "neck", "hand", "finger", "foot", "toe")
for obj in meshes:
    keep_groups = {g.index for g in obj.vertex_groups if any(k in g.name.lower() for k in PROTECT)}
    protect = obj.vertex_groups.new(name="gbox_protect_detail")
    reduce = obj.vertex_groups.new(name="gbox_reduce_allowed")
    for v in obj.data.vertices:
        keep = any(g.group in keep_groups and g.weight >= 0.3 for g in v.groups)
        (protect if keep else reduce).add([v.index], 1.0, "REPLACE")
    mod = obj.modifiers.new("REVIEW - adjust reduction", "DECIMATE")
    mod.decimate_type = "COLLAPSE"
    mod.ratio = 1.0
    mod.vertex_group = reduce.name
    mod.show_viewport = False
    mod.show_render = False
text = bpy.data.texts.new("START HERE - adjust reduction")
text.write(
    f"Fitted model: {name}\n\n"
    "The 'REVIEW - adjust reduction' modifier is DISABLED at ratio 1.0 (no reduction).\n"
    "To preserve volume and geometry: enable it and lower the ratio, and paint\n"
    "gbox_protect_detail on the face, hands and feet (they start pre-filled from the\n"
    "skin weights) so the collapse keeps their detail. Return the edited mesh as a new\n"
    "donor variant, then set the target game's preserve_geometry profile so the writer\n"
    "does not reduce your edited geometry again.\n"
)
if arm:
    bpy.context.view_layer.objects.active = arm
bpy.ops.wm.save_as_mainfile(filepath=out)
print("EDITABLE_BLEND", out)
