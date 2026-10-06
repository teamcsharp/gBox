"""G-Box add-on for Blender: paste whatever was copied in G-Box (sprite/tile selections, frames, 3D assets).

Installed and enabled automatically by `gbox setup` on any node where Blender is found; server URL and token are
read from gbox_addon.json beside this file. In the 3D viewport: Ctrl+Shift+V or the sidebar tab "G-Box".
- image -> textured plane (pixel-exact: Closest filtering, alpha), 1 px = 1 cm, provenance in custom props
- gltf  -> imported scene objects
- text  -> a Text datablock
"Auto-paste" imports each new G-Box copy as soon as it happens.
"""
bl_info = {"name": "G-Box", "author": "G-Box", "version": (0, 1, 0), "blender": (3, 6, 0),
           "location": "View3D > Sidebar > G-Box, Ctrl+Shift+V", "description": "Paste assets copied in G-Box",
           "category": "Import-Export"}

import base64
import json
import os
import tempfile
import urllib.request

import bpy

CFG = os.path.join(os.path.dirname(__file__), "gbox_addon.json")
_state = {"last_seq": None}


def _cfg():
    try:
        with open(CFG) as f:
            return json.load(f)
    except OSError:
        return {}


def _get(path, raw=False):
    c = _cfg()
    req = urllib.request.Request(c.get("server", "http://127.0.0.1:8765").rstrip("/") + path,
                                 headers={"Authorization": "Bearer " + c.get("token", "")})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = r.read()
    return data if raw else json.loads(data)


def _paste(item, context):
    data = _get(f"/api/artifacts/{item['sha256']}", raw=True)
    name = item.get("name") or "gbox"
    tmp = tempfile.mkdtemp(prefix="gbox_")
    created = []
    if item["kind"] == "image":
        path = os.path.join(tmp, name if name.endswith(".png") else name + ".png")
        with open(path, "wb") as f:
            f.write(data)
        img = bpy.data.images.load(path)
        img.pack()                                            # keep it inside the .blend
        w, h = img.size
        bpy.ops.mesh.primitive_plane_add(size=1, location=context.scene.cursor.location)
        ob = context.active_object
        ob.name = name
        ob.scale = (w / 100.0, h / 100.0, 1)                  # 1 px = 1 cm
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        nt = mat.node_tree
        bsdf = nt.nodes.get("Principled BSDF")
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image, tex.interpolation = img, "Closest"         # pixel art stays crisp
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
        if hasattr(mat, "blend_method"):
            mat.blend_method = "BLEND"
        ob.data.materials.append(mat)
        created = [ob]
    elif item["kind"] == "gltf":
        path = os.path.join(tmp, "asset.gltf")
        with open(path, "wb") as f:
            f.write(data)
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=path)
        created = [o for o in bpy.data.objects if o not in before]
    else:
        txt = bpy.data.texts.new(name)
        txt.write(data.decode("utf-8", "replace") if item["kind"] == "text" else data.hex(" "))
    for ob in created:
        ob["gbox_source"] = json.dumps(item.get("meta", {}))
        ob["gbox_sha256"] = item["sha256"]
    _state["last_seq"] = item["seq"]
    return created


class GBOX_OT_paste(bpy.types.Operator):
    bl_idname = "gbox.paste"
    bl_label = "Paste from G-Box"
    bl_description = "Import the latest item copied in G-Box"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            item = _get("/api/clipboard")
            if not item.get("sha256"):
                self.report({"WARNING"}, "G-Box clipboard is empty")
                return {"CANCELLED"}
            made = _paste(item, context)
            self.report({"INFO"}, f"G-Box: pasted {item['kind']} '{item['name']}' ({len(made)} objects)")
            return {"FINISHED"}
        except Exception as e:                                # network/server problems surface in the UI
            self.report({"ERROR"}, f"G-Box paste failed: {e}")
            return {"CANCELLED"}


def _auto_tick():
    scene = bpy.context.scene
    if not getattr(scene, "gbox_auto_paste", False):
        return 1.0
    try:
        item = _get("/api/clipboard")
        if item.get("sha256") and _state["last_seq"] is not None and item["seq"] != _state["last_seq"]:
            _paste(item, bpy.context)
        _state["last_seq"] = item.get("seq", 0)
    except Exception:
        pass
    return 1.0


class GBOX_PT_panel(bpy.types.Panel):
    bl_label = "G-Box"
    bl_space_type, bl_region_type, bl_category = "VIEW_3D", "UI", "G-Box"

    def draw(self, context):
        col = self.layout.column()
        col.operator("gbox.paste", icon="PASTEDOWN")
        col.prop(context.scene, "gbox_auto_paste")
        col.label(text=_cfg().get("server", "not configured"))


_keymaps = []


def register():
    bpy.utils.register_class(GBOX_OT_paste)
    bpy.utils.register_class(GBOX_PT_panel)
    bpy.types.Scene.gbox_auto_paste = bpy.props.BoolProperty(name="Auto-paste new copies", default=False)
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name="3D View", space_type="VIEW_3D")
        _keymaps.append((km, km.keymap_items.new("gbox.paste", "V", "PRESS", ctrl=True, shift=True)))
    bpy.app.timers.register(_auto_tick, first_interval=2.0, persistent=True)


def unregister():
    for km, kmi in _keymaps:
        km.keymap_items.remove(kmi)
    _keymaps.clear()
    if bpy.app.timers.is_registered(_auto_tick):
        bpy.app.timers.unregister(_auto_tick)
    del bpy.types.Scene.gbox_auto_paste
    bpy.utils.unregister_class(GBOX_PT_panel)
    bpy.utils.unregister_class(GBOX_OT_paste)
