"""Runs inside Blender: blender --background --python gbox_bridge.py -- model.gltf out.blend report.json unit_scale_m

Imports a gBox UAP (already converted to glTF by the worker) or a collection character's round-trip GLB
(/api/characters/<slug>/blender), applies game-unit scale, tags objects with gBox provenance - and, for a character,
the Live Link properties the add-on uses (armature gbox_slug / gbox_base / gbox_roles, bones gbox_role, attachments
gbox_prop / gbox_bone) - saves a .blend and writes a JSON report of created objects back for validation.
Status: written against the bpy 4.x API; not yet run (Blender not installed on the build host).
"""
import json
import struct
import sys

import bpy

gltf, blend, report, scale = sys.argv[sys.argv.index("--") + 1:][:4]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=gltf)
with open(gltf, "rb") as f:
    raw = f.read()
gl = json.loads(raw[20:20 + struct.unpack_from("<I", raw, 12)[0]]) if raw[:4] == b"glTF" else json.loads(raw)
meta = gl.get("extras", {}).get("gbox", {}) or gl.get("asset", {}).get("extras", {}).get("gbox", {})
char = next((sc["extras"]["gbox"] for sc in gl.get("scenes") or [] if isinstance(sc.get("extras"), dict)
             and isinstance(sc["extras"].get("gbox"), dict)), None)
bone_role = {n.get("name"): n["extras"]["gbox_role"] for n in gl.get("nodes") or []
             if isinstance(n.get("extras"), dict) and n["extras"].get("gbox_role")}

for ob in bpy.context.scene.objects:
    ob["gbox_source"] = json.dumps(meta.get("source", {}))
    if ob.parent is None:
        ob.scale = [s * float(scale) for s in ob.scale]   # game units -> metres
    if ob.type == "ARMATURE" and char:
        ob["gbox_slug"], ob["gbox_base"] = char.get("slug") or "", char.get("base") or char.get("slug") or ""
        ob["gbox_name"], ob["gbox_roles"] = char.get("name") or "", json.dumps(char.get("roles") or {})
        for b in ob.data.bones:
            if bone_role.get(b.name):
                b["gbox_role"] = bone_role[b.name]

objs = []
for ob in bpy.context.scene.objects:
    o = {"name": ob.name, "type": ob.type, "session_uid": ob.session_uid}
    if ob.type == "MESH":
        o |= {"vertices": len(ob.data.vertices), "polygons": len(ob.data.polygons),
              "materials": [m.name for m in ob.data.materials if m]}
    if ob.type == "ARMATURE":
        o |= {"bones": len(ob.data.bones), "role_bones": sum(1 for b in ob.data.bones if "gbox_role" in b)}
    objs.append(o)

bpy.ops.wm.save_as_mainfile(filepath=blend)
json.dump({"objects": objs, "actions": [a.name for a in bpy.data.actions], "character": (char or {}).get("slug")},
          open(report, "w"))
