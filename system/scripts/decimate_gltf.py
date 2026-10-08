"""Blender headless: reduce a skinned glTF's triangle count (edge-collapse decimate) and export a .glb, keeping the
skin (vertex groups), UVs and materials. Used by gbox/re4gc_enemies.py to fit characters into RE4's file budgets.

  blender --background --factory-startup --python scripts/decimate_gltf.py -- in.gltf out.glb <ratio | target_tris>

ratio <= 1 is a fraction of the triangles, > 1 a target triangle count.
"""
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
src, out, amount = argv[0], argv[1], float(argv[2])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
meshes = [o for o in bpy.data.objects if o.type == "MESH" and o.find_armature() == arm]
for o in [o for o in bpy.data.objects if o.type == "MESH" and o not in meshes]:
    bpy.data.objects.remove(o)
tris = sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in meshes)
ratio = amount if amount <= 1 else min(1.0, amount / max(tris, 1))
before = tris
for o in meshes:
    bpy.context.view_layer.objects.active = o
    for m in list(o.modifiers):                    # the armature deform is re-added after decimating the rest mesh
        o.modifiers.remove(m)
    if ratio < 0.999:
        # glTF splits vertices at UV and normal seams. Collapse sees those
        # copies as disconnected triangles and deletes faces instead of
        # simplifying the surface. Weld positions first; UVs remain on loops.
        span = max((max(v.co[k] for v in o.data.vertices) - min(v.co[k] for v in o.data.vertices)
                    for k in range(3)), default=0.0)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.remove_doubles(threshold=max(span * 1e-7, 1e-9))
        bpy.ops.object.mode_set(mode="OBJECT")
        d = o.modifiers.new("dec", "DECIMATE")
        d.decimate_type = "COLLAPSE"
        d.ratio = ratio
        d.use_collapse_triangulate = True
        bpy.ops.object.modifier_apply(modifier=d.name)
        if o.data.has_custom_normals:                 # collapsed faces lose the custom normals: smooth shading
            bpy.ops.mesh.customdata_custom_splitnormals_clear()
        for p in o.data.polygons:                     # shared vertex normals keep GX triangle strips long
            p.use_smooth = True
    a = o.modifiers.new("Armature", "ARMATURE")
    a.object = arm
after = sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in meshes)
bpy.ops.object.select_all(action="DESELECT")
arm.select_set(True)
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", use_selection=True, export_skins=True,
                          export_animations=False, export_yup=True, export_apply=False)
print("DECIMATED", before, "->", after, "tris", out)
