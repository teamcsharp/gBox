"""Blender headless: decimate each mesh object of a static glTF to its own triangle budget, export a .glb.
Object (node) names carry the budget: "<name>__<target tris>". Used by gbox/aki_wrestling.py (AKI N64 wrestlers:
every body part is its own model with a small vertex/face budget).

  blender --background --factory-startup --python scripts/decimate_parts_gltf.py -- in.gltf out.glb
"""
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
src, out = argv[0], argv[1]
bpy.ops.wm.read_factory_settings(use_empty=True)
try:
    bpy.ops.import_scene.gltf(filepath=src, merge_vertices=True)   # weld split corners so edges can collapse
except TypeError:
    bpy.ops.import_scene.gltf(filepath=src)
report = []
for o in [o for o in bpy.data.objects if o.type == "MESH"]:
    name = o.name.split(".")[0]
    if "__" not in name:
        continue
    target = int(name.rsplit("__", 1)[1])
    tris = sum(len(p.vertices) - 2 for p in o.data.polygons)
    bpy.context.view_layer.objects.active = o
    for step in range(6):
        if tris <= target:
            break
        d = o.modifiers.new("dec", "DECIMATE")
        d.decimate_type = "COLLAPSE"
        d.ratio = max(0.01, target / tris * (0.97 ** step))
        d.use_collapse_triangulate = True
        bpy.ops.object.modifier_apply(modifier=d.name)
        tris = sum(len(p.vertices) - 2 for p in o.data.polygons)
    if o.data.has_custom_normals:
        bpy.ops.mesh.customdata_custom_splitnormals_clear()
    for p in o.data.polygons:
        p.use_smooth = True
    report.append((name, tris))
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", export_yup=True, export_apply=True)
print("PARTS", report)
