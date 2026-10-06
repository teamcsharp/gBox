"""Runs inside Blender: blender --background --python gbox_bridge.py -- model.gltf out.blend report.json unit_scale_m

Imports a G-Box UAP (already converted to glTF by the worker), applies game-unit scale, tags objects with
G-Box provenance, saves a .blend and writes a JSON report of created objects back for validation.
Status: written against the bpy 4.x API; not yet run (Blender not installed on the build host).
"""
import json
import sys

import bpy

gltf, blend, report, scale = sys.argv[sys.argv.index("--") + 1:][:4]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=gltf)
meta = json.load(open(gltf)).get("extras", {}).get("gbox", {})

for ob in bpy.context.scene.objects:
    ob["gbox_source"] = json.dumps(meta.get("source", {}))
    if ob.parent is None:
        ob.scale = [s * float(scale) for s in ob.scale]   # game units -> metres

objs = []
for ob in bpy.context.scene.objects:
    o = {"name": ob.name, "type": ob.type, "session_uid": ob.session_uid}
    if ob.type == "MESH":
        o |= {"vertices": len(ob.data.vertices), "polygons": len(ob.data.polygons),
              "materials": [m.name for m in ob.data.materials if m]}
    if ob.type == "ARMATURE":
        o |= {"bones": len(ob.data.bones)}
    objs.append(o)

bpy.ops.wm.save_as_mainfile(filepath=blend)
json.dump({"objects": objs, "actions": [a.name for a in bpy.data.actions]}, open(report, "w"))
