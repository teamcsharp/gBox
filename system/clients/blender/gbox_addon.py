"""gBox add-on for Blender: paste whatever was copied in gBox, and the gBox Live Link (edit collection characters, send them
back as variant characters, see them in the running game).

Installed and enabled automatically by `gbox setup` on any node where Blender is found; server URL and token are
read from gbox_addon.json beside this file (or the add-on preferences, or env GBOX_SERVER / GBOX_TOKEN).
In the 3D viewport: Ctrl+Shift+V or the sidebar tab "gBox".
- image -> textured plane (pixel-exact: Closest filtering, alpha), 1 px = 1 cm, provenance in custom props
- gltf  -> imported scene objects
- text  -> a Text datablock
"Send to gBox" stores the selection (or the gBox character being edited) in the gBox collection as a character
(characters op=add, gbox.blender_roundtrip): a gBox character with its skeleton unchanged -> a variant of it (rig roles
kept, objects parented to bones = attachments with their own textures); bones changed -> a new character derived from
it; anything else -> a new character, its rig recognised (Mixamo, Rigify, VRoid/VRM, UE mannequin, biped, Blender
metarig) or, without an armature, auto-rigged. "Copy to gBox clipboard" only puts the GLB on the clipboard.
"Auto-paste" imports each new gBox copy as soon as it happens. A character pasted from gBox (Ctrl+Shift+V, or a plain
Ctrl+V after gBox's "Copy to Blender") keeps its role names on the bones and is adopted into gBox/<slug> on send.

gBox Live Link (sidebar > gBox > gBox Live Link):
  Connect      reads the collection (previews) and the running sessions from the gBox server
  Pull         imports a character into the collection "gBox/<slug>" (armature, weights, textures: the round-trip GLB)
               with its gBox metadata as custom properties (collection + armature: gbox_slug, gbox_base, gbox_roles;
               bones: gbox_role; meshes: gbox_part=body, attachments gbox_prop / gbox_bone)
  edit         reshape the head, scale the head bone (pose mode: carried through as the head scale), add hats / props
               (any object in that collection; bound to its "gbox_bone" property's bone or the nearest bone on send,
               or pick one with Bind), paint / swap textures, change materials
  Send back    exports the collection (GLB with extras; painted images packed, node-only materials baked) and stores it
               in gBox as a variant (characters op=add base=<slug>): base rig roles, props mapped to their bones
  Use in game  characters op=use on a running gBox session (built + launched where a writer exists)
  Live         on every save (Ctrl+S; saves within DEBOUNCE_S coalesce into one push) or Push: re-sends the variant
               (the first save creates it) and live_link puts it into the game showing it - the session picked with
               Use in game, else whichever running game shows this character or its original (live_link finds it):
               building -> validating -> reloading -> live ✓, or the blocking reason, in the status box
"""
bl_info = {"name": "gBox", "author": "gBox", "version": (0, 3, 0), "blender": (3, 6, 0),
           "location": "View3D > Sidebar > gBox, Ctrl+Shift+V", "description": "Paste assets copied in gBox; gBox Live Link",
           "category": "Import-Export"}

import json
import os
import tempfile
import threading
import time
import urllib.parse
import urllib.request

import bpy
from bpy.app.handlers import persistent
from mathutils import Matrix, Vector

CFG = os.path.join(os.path.dirname(__file__), "gbox_addon.json")
_state = {"last_seq": None}
LIVE = {"status": "", "busy": False, "chars": [], "sessions": [], "pending": [], "connected": "", "last": {}}
_previews = {"pc": None}
_items = {"chars": [], "sessions": []}
DEBOUNCE_S = 1.5                                              # saves closer together than this: one live push


# ---------------------------------------------------------------- pure helpers (no bpy: tested without Blender)

class Debounce:
    """Ctrl+S pressed several times in a row -> one push, `wait` seconds after the last save."""

    def __init__(self, wait=DEBOUNCE_S):
        self.wait, self.at = wait, None

    def hit(self, now):
        self.at = now

    def due(self, now):
        return self.at is not None and now - self.at >= self.wait

    def left(self, now):
        return None if self.at is None else max(0.0, self.wait - (now - self.at))

    def clear(self):
        self.at = None


_save_wait = Debounce()


def glb_json(path):
    """The glTF json of a .glb / .gltf file."""
    with open(path, "rb") as f:
        d = f.read()
    if d[:4] == b"glTF":
        import struct
        n = struct.unpack_from("<I", d, 12)[0]
        return json.loads(d[20:20 + n])
    return json.loads(d)


def gbox_tags(gl):
    """gBox metadata of a round-trip GLB (gbox.blender_roundtrip.tag) -> {info, bones {bone: role},
    objects {node: {gbox_prop, gbox_bone, gbox_part}}} ({} when it has none)."""
    info = next((sc["extras"]["gbox"] for sc in gl.get("scenes") or [] if isinstance(sc.get("extras"), dict)
                 and isinstance(sc["extras"].get("gbox"), dict)), None)
    bones, objs = {}, {}
    for n in gl.get("nodes") or []:
        e = n.get("extras") if isinstance(n.get("extras"), dict) else {}
        if e.get("gbox_role"):
            bones[n.get("name")] = e["gbox_role"]
        keep = {k: v for k, v in e.items() if k in ("gbox_prop", "gbox_bone", "gbox_part")}
        if "mesh" in n and keep:
            objs[n.get("name")] = keep
    return {"info": info, "bones": bones, "objects": objs} if (info or bones or objs) else {}


def add_input(name, artifact, base="", replace="", props=(), roles=None, scale=None, auto_rig=True, derived_ok=True):
    """characters op=add input of a send (the control plane decides variant / derived / new, gbox.blender_roundtrip)."""
    return {"op": "add", "character": name, "artifact": artifact, "base": base or "", "replace": replace or "",
            "props": [{"object": p["object"], "bone": p["bone"]} for p in props or []], "rig_roles": dict(roles or {}),
            "scale": dict(scale or {}), "auto_rig": bool(auto_rig), "derived_ok": bool(derived_ok)}


def describe_add(r):
    """One status line for a characters op=add result."""
    e = r.get("entry") or {}
    mode = r.get("mode") or ("variant" if r.get("variant_of") else "new")
    props = ", ".join(f"{p.get('node')}→{p.get('bone')}" for p in r.get("props") or []) or "no attachments"
    rig = r.get("rig") or {}
    how = {"variant": f"variant of {r.get('variant_of')}", "derived": f"new character derived from {r.get('derived_from')}",
           "new": f"new character ({rig.get('rig') or 'no'} rig{', auto-rigged' if rig.get('rig') == 'auto' else ''})"}[mode]
    warn = f" ⚠ {r['note']}" if r.get("note") else ""
    return f"✓ {e.get('name')} ({e.get('slug')}): {how}; {props}{warn}"


# ---------------------------------------------------------------- server

def _cfg():
    try:
        with open(CFG) as f:
            c = json.load(f)
    except OSError:
        c = {}
    try:
        p = bpy.context.preferences.addons[__name__].preferences
        c.update({k: v for k, v in (("server", p.server), ("token", p.token)) if v})
    except Exception:                                         # no prefs (background / not registered as add-on)
        pass
    c.update({k: os.environ[e] for k, e in (("server", "GBOX_SERVER"), ("token", "GBOX_TOKEN")) if os.environ.get(e)})
    return c


def _req(method, path, body=None, ctype="application/json", raw=False, timeout=60):
    c = _cfg()
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode()
    req = urllib.request.Request(c.get("server", "http://127.0.0.1:8765").rstrip("/") + path, data=body, method=method,
                                 headers={"Authorization": "Bearer " + c.get("token", ""), "Content-Type": ctype})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return data if raw else json.loads(data)


def _get(path, raw=False):
    return _req("GET", path, raw=raw, timeout=30)


def _post(path, body: bytes, ctype="application/json"):
    return _req("POST", path, body, ctype, timeout=120)


def _job(body, label="", limit=3600):
    """Submit a gBox job and wait; LIVE['status'] follows its progress messages."""
    j = _req("POST", "/api/jobs", body)
    t0 = time.time()
    while j.get("state") in ("queued", "running") and time.time() - t0 < limit:
        time.sleep(1.0)
        j = _req("GET", f"/api/jobs/{j['id']}")
        msg = (j.get("progress") or {}).get("msg")
        if msg:
            LIVE["status"] = (label + ": " if label else "") + msg
    if j.get("state") != "succeeded":
        raise RuntimeError(f"{body.get('tool')} {j.get('state')}: {j.get('error')}")
    return (j.get("output") or {}).get("result", j.get("output"))


# ---------------------------------------------------------------- clipboard paste / send

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
        path = os.path.join(tmp, "asset.glb" if data[:4] == b"glTF" else "asset.gltf")
        with open(path, "wb") as f:
            f.write(data)
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=path)
        created = [o for o in bpy.data.objects if o not in before]
        try:
            tags = gbox_tags(glb_json(path))
        except Exception:                                     # not ours / unreadable: a plain import
            tags = {}
        if tags:                                              # a gBox character: role names on bones, its own collection
            apply_tags(created, tags)
            if tags.get("info"):
                adopt(created, tags["info"], context)
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
    bl_label = "Paste from gBox"
    bl_description = "Import the latest item copied in gBox"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            item = _get("/api/clipboard")
            if not item.get("sha256"):
                self.report({"WARNING"}, "gBox clipboard is empty")
                return {"CANCELLED"}
            made = _paste(item, context)
            self.report({"INFO"}, f"gBox: pasted {item['kind']} '{item['name']}' ({len(made)} objects)")
            return {"FINISHED"}
        except Exception as e:                                # network/server problems surface in the UI
            self.report({"ERROR"}, f"gBox paste failed: {e}")
            return {"CANCELLED"}


class GBOX_OT_send(bpy.types.Operator):
    bl_idname = "gbox.send"
    bl_label = "Copy to gBox clipboard"
    bl_description = ("Export the selected objects (or the whole scene) as GLB and put it on the gBox clipboard only "
                      "(Send to gBox stores it in the collection)")

    def execute(self, context):
        try:
            path = os.path.join(tempfile.mkdtemp(prefix="gbox_"), "edited.glb")
            sel = bool(context.selected_objects)
            try:
                bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=sel, export_extras=True)
            except TypeError:
                bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=sel)
            with open(path, "rb") as f:
                data = f.read()
            name = (context.active_object.name if context.active_object else "blender_model")
            q = urllib.parse.urlencode({"name": name + ".glb", "media_type": "model/gltf-binary",
                                        "provenance": json.dumps({"from": "blender", "blend": bpy.data.filepath})})
            ref = _post("/api/artifacts?" + q, data, "application/octet-stream")
            item = _post("/api/clipboard", json.dumps({"kind": "gltf", "name": name, "artifact": ref["sha256"],
                                                        "meta": {"from": "blender"}}).encode())
            _state["last_seq"] = item.get("seq")                # don't auto-paste our own copy back
            self.report({"INFO"}, f"gBox: sent '{name}' ({len(data) // 1024} KB{'' if sel else ', whole scene'})")
            return {"FINISHED"}
        except Exception as e:
            self.report({"ERROR"}, f"gBox send failed: {e}")
            return {"CANCELLED"}


# ---------------------------------------------------------------- Live Link: collection, pull

def connect():
    """Collection list + previews (downloaded to a temp folder, loaded as Blender previews)."""
    import bpy.utils.previews
    chars = [c for c in _get("/api/characters") if c.get("kind", "character") == "character"]
    if _previews["pc"] is None:
        _previews["pc"] = bpy.utils.previews.new()
    pc = _previews["pc"]
    d = os.path.join(tempfile.gettempdir(), "gbox_previews")
    os.makedirs(d, exist_ok=True)
    items = []
    for i, c in enumerate(sorted(chars, key=lambda c: (c.get("variant_of") or c["slug"], bool(c.get("variant_of")), c["name"]))):
        key = f"{c['slug']}@{int(c.get('added') or 0)}"
        if key not in pc:
            f = os.path.join(d, f"{c['slug']}_{int(c.get('added') or 0)}.png")
            try:
                with open(f, "wb") as fh:
                    fh.write(_get(f"/api/characters/{c['slug']}/preview", raw=True))
                pc.load(key, f, "IMAGE")
            except Exception:
                pass
        icon = pc[key].icon_id if key in pc else 0
        label = ("↳ " if c.get("variant_of") else "") + c["name"]
        items.append((c["slug"], label, (c.get("source") or {}).get("game_title", ""), icon, i))
    _items["chars"] = items
    LIVE["chars"] = chars
    LIVE["connected"] = f"{len(chars)} characters"
    return chars


def _layer_coll(lc, name):
    if lc.collection.name == name:
        return lc
    for ch in lc.children:
        r = _layer_coll(ch, name)
        if r:
            return r
    return None


def _fetch_model(slug, d):
    """The round-trip GLB (armature, weights, textures, role names, props as extras); an older server: the model."""
    try:
        data = _get(f"/api/characters/{slug}/blender", raw=True)
    except Exception:
        data = _get(f"/api/characters/{slug}/model", raw=True)
    if data[:4] == b"glTF":
        p = os.path.join(d, slug + ".glb")
    else:                                                     # .gltf: fetch external buffers / images beside it
        gl = json.loads(data)
        for coll in ("buffers", "images"):
            for it in gl.get(coll, []):
                u = it.get("uri")
                if u and not u.startswith("data:"):
                    f = os.path.join(d, urllib.parse.unquote(u))
                    os.makedirs(os.path.dirname(f), exist_ok=True)
                    with open(f, "wb") as fh:
                        fh.write(_get(f"/api/characters/{slug}/file/{u}", raw=True))
        p = os.path.join(d, slug + ".gltf")
    with open(p, "wb") as f:
        f.write(data)
    return p


def apply_tags(objs, tags):
    """Custom properties from a round-trip GLB's extras (the importer usually sets them itself; names can differ)."""
    info = tags.get("info") or {}
    for o in objs:
        if o.type == "ARMATURE":
            if info:
                o["gbox_slug"] = info.get("slug") or ""
                o["gbox_base"] = info.get("base") or info.get("slug") or ""
                o["gbox_name"] = info.get("name") or ""
                o["gbox_roles"] = json.dumps(info.get("roles") or {})
            roles = tags.get("bones") or {}
            if not roles and info.get("roles"):
                roles = {b: r for r, b in info["roles"].items()}
            for b in o.data.bones:
                if roles.get(b.name):
                    b["gbox_role"] = roles[b.name]
        for k, v in ((tags.get("objects") or {}).get(o.name) or {}).items():
            o[k] = v


def adopt(objs, info, context=None):
    """Objects of one gBox character -> its own collection gBox/<slug> with the Live Link properties (Pull does this;
    a Ctrl+Shift+V / Ctrl+V paste of a gBox character too, on paste or on send)."""
    context = context or bpy.context
    slug = info.get("slug") or info.get("base") or "character"
    coll = bpy.data.collections.new(f"gBox/{slug}")
    context.scene.collection.children.link(coll)
    shapes = {pb.custom_shape for o in objs if o.type == "ARMATURE" for pb in o.pose.bones if pb.custom_shape}
    for o in objs:
        if o in shapes:                                       # the importer's bone-display shapes aren't part of it
            continue
        if coll not in o.users_collection:
            coll.objects.link(o)
        for c in list(o.users_collection):
            if c != coll:
                c.objects.unlink(o)
    variant = bool(info.get("variant_of"))
    coll["gbox_slug"] = slug
    coll["gbox_base"] = info.get("base") or info.get("variant_of") or slug
    coll["gbox_variant"] = slug if variant else ""
    coll["gbox_variant_name"] = (info.get("name") or "") if variant else ""
    coll["gbox_name"] = info.get("name") or slug
    coll["gbox_roles"] = json.dumps(info.get("roles") or {})
    coll["gbox_server"] = _cfg().get("server", "")
    for o in objs:
        if o.type == "MESH" and _skinned(o) and not o.get("gbox_prop"):
            o["gbox_part"] = "body"
    lc = _layer_coll(context.view_layer.layer_collection, coll.name)
    if lc is not None:
        context.view_layer.active_layer_collection = lc
    context.scene["gbox_last_coll"] = coll.name
    return coll


def adopt_selection(context=None):
    """No gBox collection, but the active object belongs to a pasted gBox character (armature gbox_slug): adopt it."""
    context = context or bpy.context
    ob = getattr(context, "active_object", None)
    arm = ob if ob is not None and ob.type == "ARMATURE" else (
        ob.parent if ob is not None and ob.parent is not None and ob.parent.type == "ARMATURE" else None)
    if arm is None or not arm.get("gbox_slug"):
        return None
    try:
        roles = json.loads(arm.get("gbox_roles") or "{}")
    except ValueError:
        roles = {}
    base = arm.get("gbox_base") or arm["gbox_slug"]
    info = {"slug": arm["gbox_slug"], "base": base, "name": arm.get("gbox_name") or "", "roles": roles,
            "variant_of": base if base != arm["gbox_slug"] else ""}
    return adopt([arm, *arm.children_recursive], info, context)


def pull(slug, context=None):
    """Character -> collection gBox/<slug> with armature, weights, materials, textures and the gBox metadata."""
    context = context or bpy.context
    meta = _get(f"/api/characters/{slug}")
    path = _fetch_model(slug, tempfile.mkdtemp(prefix="gbox_pull_"))
    if context.object and context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    try:
        tags = gbox_tags(glb_json(path))
    except Exception:                                         # an older server's plain model
        tags = {}
    roles = (meta.get("rig") or {}).get("roles") or {}
    info = {"slug": slug, "base": meta.get("variant_of") or slug, "variant_of": meta.get("variant_of") or "",
            "name": meta["name"], "roles": roles}
    apply_tags(new, {**tags, "info": info})
    coll = adopt(new, info, context)
    for im in bpy.data.images:                                # textures live in the .blend (paint, re-export)
        if im.source == "FILE" and not im.packed_file and im.has_data:
            try:
                im.pack()
            except Exception:
                pass
    props = [o.name for o in coll.all_objects if o.get("gbox_prop")]
    LIVE["status"] = (f"pulled {meta['name']} into {coll.name} ({len(new)} objects, {len(roles)} role bones"
                      + (f", attachments {', '.join(props)}" if props else "") + ")")
    return coll


def target_coll(context=None):
    """The gBox collection being edited: the active collection, the active object's, or the last pulled one."""
    context = context or bpy.context
    c = getattr(context, "collection", None)
    if c is not None and "gbox_slug" in c:
        return c
    ob = getattr(context, "active_object", None)
    for o in (ob, getattr(ob, "parent", None)):
        for c in (o.users_collection if o else ()):
            if "gbox_slug" in c:
                return c
    return bpy.data.collections.get(context.scene.get("gbox_last_coll", ""))


def edited_coll(context=None):
    """target_coll, or the pasted gBox character the active object belongs to (adopted into gBox/<slug> now)."""
    context = context or bpy.context
    ob = getattr(context, "active_object", None)
    if ob is not None and not any("gbox_slug" in c for o in (ob, ob.parent) if o for c in o.users_collection):
        adopted = adopt_selection(context)
        if adopted is not None:
            return adopted
    return target_coll(context)


def _armature(coll):
    return next((o for o in coll.all_objects if o.type == "ARMATURE"), None)


# ---------------------------------------------------------------- Live Link: props, textures, export

def _seg_dist(p, a, b):
    ab = b - a
    t = 0.0 if ab.length_squared < 1e-12 else max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
    return (a + ab * t - p).length


def nearest_bone(arm, ob):
    pts = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
    cen = sum(pts, Vector()) / len(pts)
    best, bd = None, 1e30
    for pb in arm.pose.bones:
        d = _seg_dist(cen, arm.matrix_world @ pb.head, arm.matrix_world @ pb.tail)
        if d < bd:
            best, bd = pb.name, d
    return best


def _skinned(ob):
    return any(m.type == "ARMATURE" for m in getattr(ob, "modifiers", []))


def bind(ob, arm, bone):
    """Parent ob to the bone, keeping where it is (Blender bone parenting = the glTF node child of that joint)."""
    mw = ob.matrix_world.copy()
    ob.parent = arm
    ob.parent_type = "BONE"
    ob.parent_bone = bone
    ob.matrix_parent_inverse = Matrix.Identity(4)
    bpy.context.view_layer.update()
    ob.matrix_world = mw
    ob["gbox_bone"] = bone
    ob["gbox_prop"] = True                                    # glTF extras: every writer carries it rigidly on that bone
    if "gbox_part" in ob:
        del ob["gbox_part"]


def bone_roles(arm):
    """{role: bone} from the bones' gbox_role properties (Pull / paste set them; rename-proof), else the armature's."""
    roles = {}
    for b in arm.data.bones:
        r = b.get("gbox_role")
        if r and r not in roles:
            roles[r] = b.name
    if not roles:
        try:
            roles = {r: n for r, n in json.loads(arm.get("gbox_roles") or "{}").items() if arm.data.bones.get(n)}
        except ValueError:
            roles = {}
    return roles


def bind_props(coll, arm):
    """Every object in the collection that isn't the body: bound to its gbox_bone or the nearest bone -> [{object, bone}]."""
    objs = set(coll.all_objects)
    shapes = {pb.custom_shape for pb in arm.pose.bones if pb.custom_shape}
    out = []
    for ob in coll.all_objects:
        if (ob is arm or ob.type not in {"MESH", "CURVE", "SURFACE", "META", "FONT"} or _skinned(ob) or ob in shapes
                or not ob.visible_get()):
            continue
        if ob.get("gbox_part") == "body":                    # the character's own rigid parts (N64 / PS1 limbs)
            continue
        if ob.parent is arm and ob.parent_type == "BONE":
            ob["gbox_bone"], ob["gbox_prop"] = ob.parent_bone, True
            out.append({"object": ob.name, "bone": ob.parent_bone, "how": "bone parent"})
            continue
        if ob.parent is not None and ob.parent in objs and ob.parent is not arm:
            continue                                          # rides the prop it's parented to
        want = ob.get("gbox_bone")
        bone = want if want and arm.data.bones.get(want) else nearest_bone(arm, ob)
        bind(ob, arm, bone)
        out.append({"object": ob.name, "bone": bone, "how": "gbox_bone" if want == bone else "nearest bone"})
    return out


def _bsdf(mat):
    if not mat or not mat.use_nodes:
        return None
    out = next((n for n in mat.node_tree.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None)
    if not out or not out.inputs["Surface"].is_linked:
        return None
    n = out.inputs["Surface"].links[0].from_node
    return n if n.type == "BSDF_PRINCIPLED" else None


def _exportable(mat):
    """Can the glTF exporter write this material as is (constant colour, image, image x colour)?"""
    if not mat or not mat.use_nodes:
        return True
    b = _bsdf(mat)
    if b is None:
        return False
    bc = b.inputs["Base Color"]
    if not bc.is_linked:
        return True
    n = bc.links[0].from_node
    if n.type == "TEX_IMAGE":
        return True
    if n.type in ("MIX", "MIX_RGB"):                          # the glTF importer's own "image x factor" layout
        ins = [i for i in n.inputs if i.type == "RGBA"]
        linked = [i for i in ins if i.is_linked]
        return len(linked) <= 1 and all(i.links[0].from_node.type == "TEX_IMAGE" for i in linked)
    return False


def prepare_textures(coll, size=256):
    """Painted / generated images packed (the export takes the current pixels); materials the exporter can't express
    (procedural nodes) baked to an image (Cycles diffuse colour) and swapped in for the export -> (report, restore)."""
    mats = {s.material for o in coll.all_objects if o.type == "MESH" for s in o.material_slots if s.material}
    packed = 0
    for m in mats:
        for n in (m.node_tree.nodes if m.use_nodes else []):
            im = getattr(n, "image", None)
            if im is not None and (im.is_dirty or im.source == "GENERATED" or not im.packed_file):
                try:
                    im.pack()
                    packed += 1
                except Exception:
                    pass
    swaps, made, notes, baked = [], [], [], []
    bad = [m for m in mats if not _exportable(m)]
    if bad:
        scn = bpy.context.scene
        eng = scn.render.engine
        try:
            scn.render.engine = "CYCLES"
            for m in bad:
                users = [o for o in coll.all_objects if o.type == "MESH" and any(s.material == m for s in o.material_slots)]
                if not all(o.data.uv_layers for o in users):
                    notes.append(f"{m.name}: no UVs, not baked (exports its base colour)")
                    continue
                img = bpy.data.images.new(f"{m.name}_gbox_bake", size, size)
                nm = m.copy()
                nm.name = m.name + "_gbox_bake"
                made.append(nm)
                tn = nm.node_tree.nodes.new("ShaderNodeTexImage")
                tn.image = img
                nm.node_tree.nodes.active = tn
                for o in users:
                    for s in o.material_slots:
                        if s.material == m:
                            swaps.append((s, m))
                            s.material = nm
                others = {s.material for o in users for s in o.material_slots if s.material not in (nm, None)}
                tmp = []
                for om in others:                             # Cycles bakes every material of the object: the others
                    if om.use_nodes:                          # get a throwaway target
                        t = om.node_tree.nodes.new("ShaderNodeTexImage")
                        t.image = bpy.data.images.new("gbox_tmp", 4, 4)
                        om.node_tree.nodes.active = t
                        tmp.append((om, t))
                bpy.ops.object.select_all(action="DESELECT")
                for o in users:
                    o.select_set(True)
                bpy.context.view_layer.objects.active = users[0]
                try:
                    bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, margin=4)
                finally:
                    for om, t in tmp:
                        bpy.data.images.remove(t.image)
                        om.node_tree.nodes.remove(t)
                img.pack()
                nt = nm.node_tree                             # the baked copy: image -> Principled base colour
                for n in list(nt.nodes):
                    if n.name != tn.name:                     # (bpy wrappers aren't identical objects: compare names)
                        nt.nodes.remove(n)
                b = nt.nodes.new("ShaderNodeBsdfPrincipled")
                o_ = nt.nodes.new("ShaderNodeOutputMaterial")
                nt.links.new(tn.outputs["Color"], b.inputs["Base Color"])
                nt.links.new(b.outputs["BSDF"], o_.inputs["Surface"])
                baked.append(m.name)
        except Exception as e:                                # a failed bake still exports (base colour only)
            notes.append(f"bake failed: {e}")
        finally:
            scn.render.engine = eng

    def restore():
        for s, m in swaps:
            s.material = m
        for nm in made:
            bpy.data.materials.remove(nm)
    return {"packed": packed, "baked": baked, "notes": notes}, restore


def head_scale(coll, arm):
    """Pose-mode scale of the head-role bone -> {"head": k} (the writers scale the head about its base)."""
    roles = json.loads(coll.get("gbox_roles", "{}"))
    pb = arm.pose.bones.get(roles.get("head", ""))
    if not pb:
        return {}
    k = (pb.scale.x + pb.scale.y + pb.scale.z) / 3.0
    return {"head": round(k, 3)} if abs(k - 1.0) > 0.01 else {}


def export_collection(coll, arm, path):
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    _clear_scene_gbox()
    arm["gbox_slug"] = coll.get("gbox_variant") or coll.get("gbox_slug") or ""   # names its original in the file
    arm["gbox_base"] = coll.get("gbox_base") or ""
    bpy.ops.object.select_all(action="DESELECT")
    shapes = {pb.custom_shape for pb in arm.pose.bones if pb.custom_shape}
    for o in coll.all_objects:
        if o.visible_get() and o not in shapes:
            o.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    kw = dict(filepath=path, export_format="GLB", use_selection=True, export_animations=False, export_skins=True,
              export_apply=True, export_yup=True, export_extras=True)   # extras: gbox_role / gbox_prop / gbox_slug
    try:
        bpy.ops.export_scene.gltf(**kw)
    except TypeError:                                         # an exporter without one of the options
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True)
    with open(path, "rb") as f:
        return f.read()


def export_payload(coll, name, replace=""):
    """Main-thread half of a send: bind props, pack / bake textures, export the GLB."""
    arm = _armature(coll)
    if not arm:
        raise RuntimeError(f"{coll.name} has no armature (pull the character again)")
    props = bind_props(coll, arm)
    tex, restore = prepare_textures(coll)
    try:
        data = export_collection(coll, arm, os.path.join(tempfile.mkdtemp(prefix="gbox_send_"), "variant.glb"))
    finally:
        restore()
    return {"coll": coll.name, "name": name, "base": coll["gbox_base"], "replace": replace, "props": props,
            "scale": head_scale(coll, arm), "textures": tex, "glb": data, "blend": bpy.data.filepath,
            "roles": bone_roles(arm)}


def _clear_scene_gbox():
    """A pulled GLB's scene extras land on the Blender scene as "gbox": never export them with another model (the
    control plane would take that character for its original)."""
    sc = bpy.context.scene
    if "gbox" in sc.keys():
        del sc["gbox"]


def selection_payload(context, name, auto_rig=True):
    """Main-thread half of Send to gBox for a model that isn't a gBox character (made in Blender): the selection (or
    everything visible) + its armature and the armature's children; objects parented to a bone are attachments."""
    sel = list(context.selected_objects) or [o for o in context.view_layer.objects if o.visible_get()]
    arm = next((o for o in sel if o.type == "ARMATURE"), None)
    arm = arm or next((o.parent for o in sel if o.parent is not None and o.parent.type == "ARMATURE"), None)
    arm = arm or next((m.object for o in sel for m in getattr(o, "modifiers", []) if m.type == "ARMATURE" and m.object), None)
    objs, props, roles = set(sel), [], {}
    if arm is not None:
        objs |= {arm, *arm.children_recursive}
        for o in arm.children_recursive:
            if o.type == "MESH" and o.parent is arm and o.parent_type == "BONE" and not _skinned(o):
                o["gbox_bone"], o["gbox_prop"] = o.parent_bone, True
                props.append({"object": o.name, "bone": o.parent_bone})
        roles = bone_roles(arm)
    if context.object and context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        if o.visible_get():
            o.select_set(True)
    if arm is not None:
        context.view_layer.objects.active = arm
    _clear_scene_gbox()
    path = os.path.join(tempfile.mkdtemp(prefix="gbox_send_"), "model.glb")
    kw = dict(filepath=path, export_format="GLB", use_selection=True, export_animations=False, export_skins=True,
              export_apply=True, export_yup=True, export_extras=True)
    try:
        bpy.ops.export_scene.gltf(**kw)
    except TypeError:
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True)
    with open(path, "rb") as f:
        data = f.read()
    return {"name": name, "glb": data, "base": (arm.get("gbox_base") or "") if arm is not None else "", "replace": "",
            "props": props, "roles": roles, "scale": {}, "auto_rig": auto_rig, "arm": arm.name if arm is not None else "",
            "blend": bpy.data.filepath}


def send_character(p):
    """Network half of Send to gBox (any thread): upload, characters op=add; the control plane decides variant /
    derived / new (gbox.blender_roundtrip) and answers with the entry, its roles and attachments."""
    q = urllib.parse.urlencode({"name": f"{p['name']}.glb", "media_type": "model/gltf-binary",
                                "provenance": json.dumps({"from": "blender send", "base": p.get("base", ""),
                                                          "blend": p.get("blend", "")})})
    LIVE["status"] = f"uploading {len(p['glb']) // 1024} KB"
    ref = _req("POST", "/api/artifacts?" + q, p["glb"], "application/octet-stream", timeout=300)
    r = _job({"tool": "characters", "require_os": "linux",
              "input": add_input(p["name"], ref["sha256"], p.get("base"), p.get("replace"), p.get("props"), p.get("roles"),
                                 p.get("scale"), p.get("auto_rig", True), True)}, "storing")
    e = r.get("entry") or {}
    mode = r.get("mode") or "variant"
    if p.get("coll"):
        LIVE["pending"].append(("variant" if mode == "variant" else "derived", p["coll"], e.get("slug"), e.get("name")))
    elif p.get("arm"):
        LIVE["pending"].append(("armature", p["arm"], e.get("slug"), e.get("name")))
    LIVE["result"] = r
    LIVE["status"] = describe_add(r)
    return r


def upload_variant(p):
    """Network half of a send (any thread): upload the GLB, characters op=add base=<slug> on the control plane."""
    q = urllib.parse.urlencode({"name": f"{p['name']}.glb", "media_type": "model/gltf-binary",
                                "provenance": json.dumps({"from": "blender live link", "base": p["base"], "blend": p.get("blend", "")})})
    LIVE["status"] = f"uploading {len(p['glb']) // 1024} KB"
    ref = _req("POST", "/api/artifacts?" + q, p["glb"], "application/octet-stream", timeout=300)
    r = _job({"tool": "characters", "require_os": "linux",
              "input": {"op": "add", "character": p["name"], "artifact": ref["sha256"], "base": p["base"],
                        "replace": p["replace"], "props": [{"object": x["object"], "bone": x["bone"]} for x in p["props"]],
                        "scale": p["scale"]}}, "storing")
    e = r.get("entry") or {}
    LIVE["pending"].append(("variant", p["coll"], e.get("slug"), e.get("name")))
    props = ", ".join(f"{x['node']}→{x['role']}" for x in r.get("props") or []) or "no props"
    LIVE["status"] = f"✓ variant {e.get('name')} ({e.get('slug')}): {props}" + (f", head ×{p['scale']['head']}" if p["scale"] else "")
    return r


def sessions():
    ss = [s for s in _get("/api/sessions") if s.get("state") == "running"]
    try:
        ws = {w["id"]: w["name"] for w in _get("/api/workers")}
    except Exception:
        ws = {}
    _items["sessions"] = [(s["session_id"], f"{s.get('title') or s.get('game_title') or s['game_id']}"
                           f"{' [' + s['mod'] + ']' if s.get('mod') else ''} on {ws.get(s['session_id'].split('-')[0], '?')}",
                           s.get("adapter") or "", i) for i, s in enumerate(ss)]
    LIVE["sessions"] = ss
    return ss


def use_in_game(slug, sid):
    r = _job({"tool": "characters", "input": {"op": "use", "character": slug, "session_id": sid}}, "use")
    s = next((x for x in LIVE["sessions"] if x["session_id"] == sid), {})
    LIVE["last"] = {"session": (r.get("launch") or {}).get("session_id") or sid, "game_id": s.get("game_id") or r.get("game_id"),
                    "slug": slug}
    if r.get("status") == "missing":
        m = r.get("missing") or {}
        LIVE["status"] = f"no writer for {r.get('game')}: needs {m.get('format', '?')} ({m.get('have', '')})"
    else:
        LIVE["status"] = f"{r.get('status')}: {r.get('message') or r.get('mod')}"
    return r


def push(payload, target="", game_id=""):
    """Live push: store the re-sent variant, then live_link (build -> validate -> reload -> frame check)."""
    r = upload_variant(payload)
    slug = (r.get("entry") or {}).get("slug")
    # no target picked (Use in game): live_link finds the running game showing this character or its original
    res = _job({"tool": "live_link", "require_os": "linux",
                "input": {"op": "push", "character": slug, "target": target, "game_id": game_id, "auto_target": True}}, "live")
    if res.get("session_id"):
        LIVE["last"]["session"] = res["session_id"]
        LIVE["last"]["game_id"] = res.get("game_id") or LIVE["last"].get("game_id")
    st = res.get("status")
    LIVE["result"] = res
    LIVE["last_push"] = time.time()
    att = (res.get("attachments") or {}).get("message")
    LIVE["status"] = (("live ✓ " + res.get("message", "").replace("live ✓ ", "")) if st == "live"
                      else f"✓ {slug} updated: {res.get('message')}" if st == "stored" else f"{st}: {res.get('message')}") \
        + (f" | {att}" if att else "")
    return res


def _bg(label, fn, *a):
    if LIVE["busy"]:
        return False
    LIVE["busy"], LIVE["status"] = True, label + "…"

    def run():
        try:
            fn(*a)
        except Exception as e:
            LIVE["status"] = f"✗ {label}: {e}"
        finally:
            LIVE["busy"] = False
    threading.Thread(target=run, daemon=True).start()
    return True


# ---------------------------------------------------------------- Live Link: operators

class GBOX_OT_connect(bpy.types.Operator):
    bl_idname = "gbox.live_connect"
    bl_label = "Connect"
    bl_description = "Read gBox's character collection (with previews) and the running sessions"

    def execute(self, context):
        try:
            connect()
            sessions()
            self.report({"INFO"}, f"gBox: {LIVE['connected']}, {len(LIVE['sessions'])} running sessions")
            return {"FINISHED"}
        except Exception as e:
            self.report({"ERROR"}, f"gBox: can't reach {_cfg().get('server')}: {e}")
            return {"CANCELLED"}


class GBOX_OT_pull(bpy.types.Operator):
    bl_idname = "gbox.live_pull"
    bl_label = "Pull into Blender"
    bl_description = "Import the character into a collection gBox/<slug> (armature, materials, textures, gBox metadata)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        slug = context.scene.gbox_char
        if not slug:
            self.report({"WARNING"}, "Connect and pick a character first")
            return {"CANCELLED"}
        try:
            coll = pull(slug, context)
            self.report({"INFO"}, LIVE["status"])
            context.scene.gbox_variant_name = coll.get("gbox_variant_name") or f"{coll['gbox_name']} – variant"
            return {"FINISHED"}
        except Exception as e:
            self.report({"ERROR"}, f"gBox pull failed: {e}")
            return {"CANCELLED"}


class GBOX_OT_bind(bpy.types.Operator):
    bl_idname = "gbox.live_bind"
    bl_label = "Bind selected to bone"
    bl_description = "Parent the selected objects (hats, props) to the chosen bone; the bone is stored as gbox_bone"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        coll = target_coll(context)
        arm = coll and _armature(coll)
        bone = context.scene.gbox_bind_bone
        if not arm or not arm.data.bones.get(bone):
            self.report({"WARNING"}, "pick a bone of the pulled character")
            return {"CANCELLED"}
        n = 0
        for ob in context.selected_objects:
            if ob is not arm and not _skinned(ob):
                if coll not in ob.users_collection:
                    coll.objects.link(ob)
                    for c in list(ob.users_collection):
                        if c != coll:
                            c.objects.unlink(ob)
                bind(ob, arm, bone)
                n += 1
        self.report({"INFO"}, f"bound {n} object(s) to {bone}")
        return {"FINISHED"}


class GBOX_OT_send_variant(bpy.types.Operator):
    bl_idname = "gbox.live_send"
    bl_label = "Send back as variant"
    bl_description = ("Export the gBox collection (props bound to bones, textures packed / baked) and store it in gBox as a "
                      "variant of the pulled character")
    name: bpy.props.StringProperty(name="Variant name", default="")
    update: bpy.props.BoolProperty(name="Update the existing variant", default=False)

    def invoke(self, context, event):
        coll = target_coll(context)
        if not coll:
            self.report({"WARNING"}, "pull a character first")
            return {"CANCELLED"}
        self.name = context.scene.gbox_variant_name or f"{coll.get('gbox_name')} – variant"
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        coll = target_coll(context)
        if not coll:
            return {"CANCELLED"}
        try:
            p = export_payload(coll, self.name, coll.get("gbox_variant", "") if self.update else "")
        except Exception as e:
            self.report({"ERROR"}, f"gBox export failed: {e}")
            return {"CANCELLED"}
        context.scene.gbox_variant_name = self.name
        _bg("sending", upload_variant, p)
        return {"FINISHED"}


class GBOX_OT_sessions(bpy.types.Operator):
    bl_idname = "gbox.live_sessions"
    bl_label = "Refresh sessions"

    def execute(self, context):
        try:
            sessions()
        except Exception as e:
            self.report({"ERROR"}, str(e))
        return {"FINISHED"}


class GBOX_OT_use(bpy.types.Operator):
    bl_idname = "gbox.live_use"
    bl_label = "Use in game"
    bl_description = "characters op=use on the chosen running session: built + launched where a writer exists (SM64, RE4 GC)"

    def execute(self, context):
        coll = target_coll(context)
        slug = (coll.get("gbox_variant") or coll.get("gbox_slug")) if coll else context.scene.gbox_char
        sid = context.scene.gbox_session
        if not slug or not sid:
            self.report({"WARNING"}, "send a variant and pick a running session first")
            return {"CANCELLED"}
        _bg("use in game", use_in_game, slug, sid)
        return {"FINISHED"}


def _start_push():
    """Export the edited character and push it (the first push creates its variant; later ones update it)."""
    coll = edited_coll()
    if not coll:
        LIVE["status"] = "live: nothing to push (Pull a character, or paste one copied from gBox)"
        return
    if LIVE["busy"]:                                          # saved during a push: once more after it
        LIVE["queued"] = True
        LIVE["status"] = "live: saved again during a push - pushing the newest save after it"
        return
    variant = coll.get("gbox_variant") or ""
    name = coll.get("gbox_variant_name") or (coll["gbox_name"] if variant else f"{coll['gbox_name']} – variant")
    try:
        p = export_payload(coll, name, variant)
    except Exception as e:
        LIVE["status"] = f"✗ export: {e}"
        return
    last = LIVE.get("last") or {}
    _bg("live push", push, p, last.get("session", ""), last.get("game_id", ""))


def _debounced_push():
    """Timer: push DEBOUNCE_S after the last save (another save restarts the wait)."""
    now = time.time()
    if not _save_wait.due(now):
        left = _save_wait.left(now)
        return None if left is None else max(0.1, left)
    _save_wait.clear()
    _start_push()
    return None


class GBOX_OT_push(bpy.types.Operator):
    bl_idname = "gbox.live_push"
    bl_label = "Push"
    bl_description = "Re-send the variant and put it into the running game (build, validate, reload, frame check)"

    def execute(self, context):
        _start_push()
        return {"FINISHED"}


@persistent
def _on_save(*_a):
    if getattr(bpy.context.scene, "gbox_live", False):
        _save_wait.hit(time.time())
        if not LIVE["busy"]:
            LIVE["status"] = f"saved: live push in {DEBOUNCE_S:g} s (saving again restarts the wait)"
        if not bpy.app.timers.is_registered(_debounced_push):
            bpy.app.timers.register(_debounced_push, first_interval=DEBOUNCE_S)


class GBOX_OT_send_character(bpy.types.Operator):
    bl_idname = "gbox.send_character"
    bl_label = "Send to gBox"
    bl_description = ("Store the character in the gBox collection: a gBox character with its skeleton unchanged becomes "
                      "a variant of it (attachments parented to bones included), bones changed -> a new character "
                      "derived from it; a model made in Blender -> a new character (rig auto-detected, or auto-rigged)")
    name: bpy.props.StringProperty(name="Name", default="")
    auto_rig: bpy.props.BoolProperty(name="Auto-rig it if it has no armature", default=True)

    def invoke(self, context, event):
        coll = edited_coll(context)
        if coll:
            self.name = context.scene.gbox_variant_name or f"{coll.get('gbox_name')} – variant"
        else:
            ob = context.active_object
            self.name = (ob.parent.name if ob is not None and ob.parent is not None else ob.name) if ob is not None else "Blender character"
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        lay = self.layout
        lay.prop(self, "name")
        coll = target_coll(context)
        if not coll or not _armature(coll):
            lay.prop(self, "auto_rig")
        else:
            lay.label(text=f"a variant of {coll.get('gbox_name')} if the bones are unchanged", icon="INFO")

    def execute(self, context):
        coll = edited_coll(context)
        try:
            if coll and _armature(coll):
                p = export_payload(coll, self.name, "")
                context.scene.gbox_variant_name = self.name
            else:
                p = selection_payload(context, self.name, self.auto_rig)
        except Exception as e:
            self.report({"ERROR"}, f"gBox export failed: {e}")
            return {"CANCELLED"}
        _bg("sending", send_character, p)
        return {"FINISHED"}


# ---------------------------------------------------------------- UI

def _char_items(self, context):
    return _items["chars"] or [("", "(press Connect)", "", 0, 0)]


def _session_items(self, context):
    return _items["sessions"] or [("", "(no running session)", "", 0, 0)]


def _wrap(col, text, width=42):
    line = ""
    for w in str(text).split():
        if line and len(line) + len(w) > width:
            col.label(text=line)
            line = ""
        line += w + " "
    if line:
        col.label(text=line)


class GBOX_PT_panel(bpy.types.Panel):
    bl_label = "gBox"
    bl_space_type, bl_region_type, bl_category = "VIEW_3D", "UI", "gBox"

    def draw(self, context):
        col = self.layout.column()
        col.operator("gbox.paste", icon="PASTEDOWN")
        col.operator("gbox.send_character", icon="EXPORT")
        col.operator("gbox.send", icon="COPYDOWN")
        col.prop(context.scene, "gbox_auto_paste")
        col.label(text=_cfg().get("server", "not configured"))


class GBOX_PT_live(bpy.types.Panel):
    bl_label = "gBox Live Link"
    bl_space_type, bl_region_type, bl_category = "VIEW_3D", "UI", "gBox"

    def draw(self, context):
        sc, lay = context.scene, self.layout
        row = lay.row(align=True)
        row.label(text=_cfg().get("server", "not configured"), icon="WORLD")
        row.operator("gbox.live_connect", text="Connect" if not LIVE["connected"] else "Refresh", icon="FILE_REFRESH")
        if LIVE["connected"]:
            lay.label(text=LIVE["connected"])
            lay.template_icon_view(sc, "gbox_char", show_labels=True, scale=6.0, scale_popup=5.0)
            lay.prop(sc, "gbox_char", text="")
            lay.operator("gbox.live_pull", icon="IMPORT")
        coll = target_coll(context)
        if coll:
            box = lay.box()
            box.label(text=f"Editing {coll.get('gbox_name')} ({coll.name})", icon="OUTLINER_COLLECTION")
            if coll.get("gbox_variant"):
                box.label(text=f"variant: {coll['gbox_variant']}", icon="DUPLICATE")
            arm = _armature(coll)
            if arm:
                hs = head_scale(coll, arm)
                box.label(text=f"head scale ×{hs['head']}" if hs else "head ×1 (scale the head bone in pose mode)")
                shapes = {pb.custom_shape for pb in arm.pose.bones if pb.custom_shape}
                props = [o for o in coll.all_objects if o is not arm and o.type == "MESH" and not _skinned(o) and o not in shapes
                         and o.get("gbox_part") != "body"]
                rb = bone_roles(arm)
                box.label(text=f"{len(rb)} role bones" + (f" (hip {rb['hip']}, head {rb.get('head', '?')})" if "hip" in rb else ""),
                          icon="ARMATURE_DATA")
                for o in props[:8]:
                    on = o.parent_bone if o.parent is arm and o.parent_type == "BONE" else (o.get("gbox_bone") or "nearest bone on send")
                    box.label(text=f"{o.name} → {on}", icon="MESH_CONE")
                r = box.row(align=True)
                r.prop_search(sc, "gbox_bind_bone", arm.data, "bones", text="")
                r.operator("gbox.live_bind", text="Bind", icon="BONE_DATA")
            box.prop(sc, "gbox_variant_name", text="Name")
            box.operator("gbox.send_character", icon="EXPORT")
            r = box.row(align=True)
            r.operator("gbox.live_send", text="Send back as variant", icon="EXPORT").update = False
            if coll.get("gbox_variant"):
                r.operator("gbox.live_send", text="Update", icon="FILE_REFRESH").update = True
            r = box.row(align=True)
            r.prop(sc, "gbox_session", text="")
            r.operator("gbox.live_sessions", text="", icon="FILE_REFRESH")
            box.operator("gbox.live_use", icon="PLAY")
            r = box.row(align=True)
            r.prop(sc, "gbox_live", text="Live (on save)", toggle=True, icon="REC")
            r.operator("gbox.live_push", icon="EXPORT")
            last = LIVE.get("last") or {}
            box.label(text=f"live target: {last['session'][:24]}" if last.get("session")
                      else "live target: the running game showing it (found on push)", icon="LINKED")
            left = _save_wait.left(time.time())
            if sc.gbox_live and left is not None:
                box.label(text=f"push in {left:.1f} s", icon="TIME")
            elif LIVE.get("last_push"):
                box.label(text=f"last push {int(time.time() - LIVE['last_push'])} s ago", icon="TIME")
        else:
            lay.operator("gbox.send_character", icon="EXPORT")
        if LIVE["status"]:
            st = lay.box().column(align=True)
            st.label(text="working…" if LIVE["busy"] else "status", icon="SORTTIME" if LIVE["busy"] else "INFO")
            _wrap(st, LIVE["status"])
            for c in ((LIVE.get("result") or {}).get("checks") or [])[:7]:
                st.label(text=f"{c['check']}: {'ok' if c['ok'] else 'FAIL'}", icon="CHECKMARK" if c["ok"] else "ERROR")


class GBOX_prefs(bpy.types.AddonPreferences):
    bl_idname = __name__
    server: bpy.props.StringProperty(name="gBox server", default="", description="blank: gbox_addon.json")
    token: bpy.props.StringProperty(name="Token", default="", subtype="PASSWORD", description="blank: gbox_addon.json")

    def draw(self, context):
        self.layout.prop(self, "server")
        self.layout.prop(self, "token")


def _auto_tick():
    while LIVE["pending"]:                                    # results from worker threads, applied on the main thread
        kind, cname, slug, name = LIVE["pending"].pop(0)
        c = bpy.data.collections.get(cname)
        if kind == "variant" and c is not None and slug:
            c["gbox_variant"], c["gbox_variant_name"] = slug, name or ""
        elif kind == "derived" and c is not None and slug:   # bones changed: the collection is that new character now
            c["gbox_slug"], c["gbox_base"], c["gbox_name"] = slug, slug, name or slug
            c["gbox_variant"], c["gbox_variant_name"] = "", ""
        elif kind == "armature" and slug:                     # a model made in Blender: now a gBox character
            a = bpy.data.objects.get(cname)
            if a is not None:
                a["gbox_slug"], a["gbox_base"], a["gbox_name"] = slug, slug, name or slug
    if LIVE.get("queued") and not LIVE["busy"]:               # saved again during a push: push once more
        LIVE["queued"] = False
        _start_push()
    if LIVE["busy"] or LIVE.get("_was_busy") or _save_wait.at is not None:     # status / countdown stay current
        LIVE["_was_busy"] = LIVE["busy"]
        for w in getattr(bpy.context.window_manager, "windows", []):
            for a in w.screen.areas:
                if a.type == "VIEW_3D":
                    a.tag_redraw()
    scene = bpy.context.scene
    if not getattr(scene, "gbox_auto_paste", False):
        return 0.5
    try:
        item = _get("/api/clipboard")
        if item.get("sha256") and _state["last_seq"] is not None and item["seq"] != _state["last_seq"]:
            _paste(item, bpy.context)
        _state["last_seq"] = item.get("seq", 0)
    except Exception:
        pass
    return 1.0


_keymaps = []
CLASSES = (GBOX_prefs, GBOX_OT_paste, GBOX_OT_send, GBOX_OT_send_character, GBOX_OT_connect, GBOX_OT_pull, GBOX_OT_bind,
           GBOX_OT_send_variant, GBOX_OT_sessions, GBOX_OT_use, GBOX_OT_push, GBOX_PT_panel, GBOX_PT_live)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    S = bpy.types.Scene
    S.gbox_auto_paste = bpy.props.BoolProperty(name="Auto-paste new copies", default=False)
    S.gbox_char = bpy.props.EnumProperty(name="Character", items=_char_items)
    S.gbox_session = bpy.props.EnumProperty(name="Session", items=_session_items)
    S.gbox_variant_name = bpy.props.StringProperty(name="Variant name", default="")
    S.gbox_bind_bone = bpy.props.StringProperty(name="Bone", default="")
    S.gbox_live = bpy.props.BoolProperty(name="Live", default=False,
                                         description="Re-send the variant on every save (Ctrl+S) and update the running game")
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name="3D View", space_type="VIEW_3D")
        _keymaps.append((km, km.keymap_items.new("gbox.paste", "V", "PRESS", ctrl=True, shift=True)))
    bpy.app.timers.register(_auto_tick, first_interval=2.0, persistent=True)
    if _on_save not in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.append(_on_save)


def unregister():
    for km, kmi in _keymaps:
        km.keymap_items.remove(kmi)
    _keymaps.clear()
    if bpy.app.timers.is_registered(_auto_tick):
        bpy.app.timers.unregister(_auto_tick)
    if bpy.app.timers.is_registered(_debounced_push):
        bpy.app.timers.unregister(_debounced_push)
    if _on_save in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.remove(_on_save)
    for p in ("gbox_auto_paste", "gbox_char", "gbox_session", "gbox_variant_name", "gbox_bind_bone", "gbox_live"):
        delattr(bpy.types.Scene, p)
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
    if _previews["pc"] is not None:
        import bpy.utils.previews
        bpy.utils.previews.remove(_previews["pc"])
        _previews["pc"] = None
