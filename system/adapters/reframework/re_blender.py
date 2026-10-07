"""RE Engine mesh <-> glTF inside Blender, driven by gbox/re4r.py (runs headless: blender -b --factory-startup --python
re_blender.py -- job.json). Needs RE Mesh Editor (NSACloud, GPL-3.0) on BLENDER_USER_SCRIPTS; gBox loads it from its own
runtime folder, so the operator's Blender setup is never changed.

job.json {"mode": "info" | "export" | "build", "cache": <texture cache dir>, ...}
  tex     {"tex": original .tex (streaming copy preferred), "png": new image, "outs": [paths], "texconv": exe}
  info    {"meshes": [paths]}                                   -> vertex/bounds per mesh (which parts are head/hair/body)
  export  {"meshes": [paths], "out": x.glb, "max_tex": 2048}     -> one rigged glTF (merged armature, albedo textures)
  build   {"meshes": [original path], "edited": x.glb, "original": y.glb, "out": z.mesh.221108797}
          the edited glTF (a Blender variant / collection entry) back into the game's mesh format:
            same topology as the original export -> per-vertex offsets are carried over (sculpt/scale/move edits)
            different topology                    -> the edited mesh replaces the part (weights from its vertex groups)
          `scale`/`offset` in the job apply a plain transform instead (used by tests).
Writes the result JSON next to job.json (job.result.json).
"""
import json
import os
import sys

import addon_utils
import bpy
import mathutils

job_path = sys.argv[sys.argv.index("--") + 1]
job = json.load(open(job_path))
res = {"ok": False}


def setup():
    addon_utils.enable("RE_Mesh_Editor", default_set=True, persistent=True)
    p = bpy.context.preferences.addons["RE_Mesh_Editor"].preferences
    p.showConsole = False                                  # console_toggle crashes Blender in background mode
    p.textureCachePath = job["cache"]
    os.makedirs(job["cache"], exist_ok=True)


def import_meshes(paths, materials=True, all_lods=False, tag=False):
    """tag: name objects "<mesh stem>:<RE name>" (parts share names like Group_0_Sub_0; glTF needs them unique)."""
    arm = None
    for p in paths:
        seen = set(bpy.data.objects)
        d, f = os.path.split(p)
        kw = dict(files=[{"name": f}], directory=d, clearScene=arm is None, loadMaterials=materials, loadMDFData=False,
                  importShadowMeshes=all_lods, importBlendShapes=False, importAllLODs=all_lods)
        if arm is not None:
            kw["mergeArmature"] = arm.data.name
        r = bpy.ops.re_mesh.importfile(**kw)
        if "FINISHED" not in r:
            raise RuntimeError(f"RE Mesh Editor could not import {p}")
        if arm is None:
            arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
        if tag:
            stem = f.split(".mesh")[0]
            for o in set(bpy.data.objects) - seen:
                if o.type == "MESH":
                    o.name = f"{stem}:{o.name}"
    return arm


def mesh_objs(coll_name=None):
    out = []
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        if coll_name and not any(c.name == coll_name or coll_name in [p.name for p in c.users_collection]
                                 for c in o.users_collection):
            continue
        out.append(o)
    return out


def bounds(objs):
    mn, mx = [1e9] * 3, [-1e9] * 3
    for o in objs:
        for v in o.data.vertices:
            w = o.matrix_world @ v.co
            for i in range(3):
                mn[i], mx[i] = min(mn[i], w[i]), max(mx[i], w[i])
    return [round(x, 3) for x in mn], [round(x, 3) for x in mx]


def info():
    out = {}
    for p in job["meshes"]:
        import_meshes([p], materials=False)
        objs = mesh_objs()
        mn, mx = bounds(objs)
        out[os.path.basename(p)] = {"objects": len(objs), "vertices": sum(len(o.data.vertices) for o in objs),
                                    "min": mn, "max": mx, "materials": sorted({o.name.split("__", 1)[-1] for o in objs})}
    res.update(ok=True, meshes=out)


def simple_materials(max_tex):
    """RE shader graphs -> Principled BSDF with the albedo map, so glTF keeps the colours (the exporter only reads
    Principled inputs). Albedo images are copied, scaled to max_tex and stored as PNG."""
    done = {}
    for m in bpy.data.materials:
        if not m.use_nodes:
            continue
        albd, base = None, None
        for n in m.node_tree.nodes:
            if n.type == "TEX_IMAGE" and n.image and "ALBD" in n.image.name.upper() and n.image.size[0] > 1 \
                    and n.name != "BaseShiftMap" and albd is None:     # hair ALBD is a shift map, coloured by BaseColor
                albd = n.image
            if n.type == "GROUP" and n.name.startswith("BaseColor") and "Color" in n.inputs:
                base = tuple(n.inputs["Color"].default_value)
        nt = m.node_tree
        nt.nodes.clear()
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        outn = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(bsdf.outputs[0], outn.inputs[0])
        bsdf.inputs["Roughness"].default_value = 0.7
        if albd is None:                                   # material colour parameter, else a dark neutral
            bsdf.inputs["Base Color"].default_value = base or (0.15, 0.15, 0.15, 1)
            continue
        if albd.name not in done:
            img = albd.copy()
            img.name = os.path.splitext(albd.name)[0]
            w, h = img.size
            if max(w, h) > max_tex:
                f = max_tex / max(w, h)
                img.scale(max(1, int(w * f)), max(1, int(h * f)))
            img.file_format = "PNG"
            img.alpha_mode = "NONE"                         # RE albedo alpha is a mask, not opacity
            done[albd.name] = img
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = done[albd.name]
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    return sorted(i.name for i in done.values())


def export():
    arm = import_meshes(job["meshes"], materials=True, tag=True)
    imgs = simple_materials(job.get("max_tex", 2048))
    for o in list(bpy.data.objects):                       # MDF material objects / empties are editor-only
        if o.type not in ("MESH", "ARMATURE"):
            bpy.data.objects.remove(o)
    objs = mesh_objs()
    mn, mx = bounds(objs)
    bpy.ops.export_scene.gltf(filepath=job["out"], export_format="GLB", export_skins=True, export_animations=False,
                              export_morph=False, export_image_format=job.get("image_format", "JPEG"),
                              export_extras=True, use_selection=False,
                              export_yup=True, export_apply=False)
    res.update(ok=True, out=job["out"], objects=len(objs), vertices=sum(len(o.data.vertices) for o in objs),
               bones=len(arm.data.bones), textures=imgs, min=mn, max=mx)


def _world_verts(o):
    mw = o.matrix_world
    return [mw @ v.co for v in o.data.vertices]


def _same_points(a, b, tol=1e-4) -> bool:
    """Same surface: every edited point sits on an original one and (almost) every original point is still there
    (the glTF importer drops loose vertices and re-splits seams, so counts differ on untouched parts)."""
    from mathutils.kdtree import KDTree

    def tree(pts):
        t = KDTree(len(pts))
        for i, p in enumerate(pts):
            t.insert(p, i)
        t.balance()
        return t
    if not a or not b:
        return False
    ta, tb = tree(a), tree(b)
    if any(tb.find(p)[2] > tol for p in a):
        return False
    missing = sum(ta.find(p)[2] > tol for p in b)
    return missing <= 0.005 * len(b)


def build():
    # scale edits keep every LOD (and shadow mesh) so distant views match; a glTF edit carries LOD0 only.
    # Blend shapes are not written back (RE Mesh Editor can't export them yet): faces keep their bone animation.
    arm = import_meshes(job["meshes"], materials=False, all_lods=job.get("scale") is not None)
    stem = os.path.basename(job["meshes"][0]).split(".mesh")[0]
    coll = bpy.data.collections.get(f"{stem}.mesh")
    re_objs = [o for o in mesh_objs() if o.parent == arm]
    changed = 0
    if job.get("scale") or job.get("offset"):              # plain transform (tests / simple variants)
        s, off = job.get("scale", 1.0), mathutils.Vector(job.get("offset", [0, 0, 0]))
        names = job.get("only")                            # material-name filter, e.g. ["Shirts_Mat"]
        sel = [o for o in re_objs if not names or o.name.split("__", 1)[-1] in names]
        if job.get("pivot") is not None:
            piv = mathutils.Vector(job["pivot"])
        else:                                              # bottom centre of the part (a head grows from the neck)
            mn, mx = bounds(sel)
            piv = mathutils.Vector(((mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, mn[2]))
        for o in sel:
            inv = o.matrix_world.inverted()
            for v in o.data.vertices:
                d = o.matrix_world @ v.co - piv
                d = mathutils.Vector((d.x * s, d.y * s, d.z)) if job.get("xy_only") else d * s
                v.co = inv @ (piv + d + off)
            changed += 1
        res["pivot"] = list(piv)
    else:
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=job["original"])
        orig = {o.name.split(".")[0]: o for o in set(bpy.data.objects) - before if o.type == "MESH"}
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=job["edited"])
        edit = {o.name.split(".")[0]: o for o in set(bpy.data.objects) - before if o.type == "MESH"}
        res["edited_objects"], res["original_objects"] = len(edit), len(orig)
        from mathutils.kdtree import KDTree
        replaced, moved = [], []
        for o in re_objs:
            key = f"{stem}:{o.name}"
            e, g = edit.get(key), orig.get(key)
            if e is None:
                continue
            ev, gv = _world_verts(e), (_world_verts(g) if g else None)
            if gv is not None and _same_points(ev, gv):   # untouched (a glTF round trip may re-split vertices)
                continue
            if gv is not None and len(ev) == len(gv):
                kd = KDTree(len(gv))
                for i, p in enumerate(gv):
                    kd.insert(p, i)
                kd.balance()
                inv = o.matrix_world.inverted()
                n = 0
                for v in o.data.vertices:
                    w = o.matrix_world @ v.co
                    _, i, dist = kd.find(w)
                    d = ev[i] - gv[i]
                    if d.length > 1e-6:
                        n += 1
                    v.co = inv @ (w + d)
                if n:
                    moved.append(o.name)
            else:                                           # new topology: the edited part replaces this one
                new = e.copy()
                new.data = e.data.copy()
                for c in new.users_collection:
                    c.objects.unlink(new)
                o.users_collection[0].objects.link(new)
                new.parent = arm
                new.matrix_world = e.matrix_world.copy()
                new.modifiers.clear()
                mod = new.modifiers.new("Armature", "ARMATURE")
                mod.object = arm
                name = o.name
                bpy.data.objects.remove(o)
                new.name = name
                replaced.append(name)
        for o in list(orig.values()) + [x for x in edit.values() if x.name in bpy.data.objects and x.parent != arm]:
            if o.name in bpy.data.objects and o.parent != arm:
                bpy.data.objects.remove(o)
        for o in list(bpy.data.objects):                    # importer armatures
            if o.type == "ARMATURE" and o != arm:
                bpy.data.objects.remove(o)
        changed = len(moved) + len(replaced)
        res.update(moved=moved, replaced=replaced)
    os.makedirs(os.path.dirname(job["out"]), exist_ok=True)
    r = bpy.ops.re_mesh.exportfile(filepath=job["out"], targetCollection=coll.name, exportAllLODs=True, exportBlendShapes=False,
                                   autoSolveRepeatedUVs=True, preserveSharpEdges=False, rotate90=True,
                                   useBlenderMaterialName=False, preserveBoneMatrices=True)
    if "FINISHED" not in r or not os.path.isfile(job["out"]):
        raise RuntimeError("RE Mesh Editor export failed (see the Blender log)")
    res.update(ok=True, out=job["out"], changed_parts=changed, size=os.path.getsize(job["out"]))


def tex():
    """PNG -> .tex in the original's DXGI format with a full mip chain (texconv.exe, then RE Mesh Editor's DDSToTex)."""
    import subprocess
    import tempfile
    from RE_Mesh_Editor.modules.dds.file_dds import getDDSHeader
    from RE_Mesh_Editor.modules.ddsconv.directx.dxgi_format import DXGI_FORMAT
    from RE_Mesh_Editor.modules.tex.re_tex_utils import DDSToTex, convertTexFileToDDS
    tmp = tempfile.mkdtemp(prefix="gbox_tex_")
    ref = os.path.join(tmp, "orig.dds")
    convertTexFileToDDS(job["tex"], ref)
    h = getDDSHeader(ref)
    fmt = DXGI_FORMAT(h.dx10Header.dxgiFormat).name if h.dx10Header else "BC7_UNORM_SRGB"
    src = os.path.join(tmp, "new.png")
    img = bpy.data.images.load(job["png"])
    if tuple(img.size) != (h.dwWidth, h.dwHeight):           # the material expects the original size
        img.scale(h.dwWidth, h.dwHeight)
    img.filepath_raw, img.file_format = src, "PNG"
    img.save()
    p = subprocess.run([job["texconv"], "-nologo", "-y", "-f", fmt, "-m", "0", "-o", tmp, src],   # full mip chain
                       capture_output=True, text=True)
    dds = os.path.join(tmp, "new.dds")
    if not os.path.isfile(dds):
        raise RuntimeError(f"texconv failed: {p.stdout[-400:]} {p.stderr[-400:]}")
    outs = job["outs"]                                     # base + streaming paths get the same full texture
    for o in outs:
        os.makedirs(os.path.dirname(o), exist_ok=True)
        DDSToTex([dds], int(job["tex"].rsplit(".", 1)[1]), o)
    res.update(ok=True, outs=outs, format=fmt, size=[h.dwWidth, h.dwHeight], bytes=os.path.getsize(outs[0]))


try:
    setup()
    {"info": info, "export": export, "build": build, "tex": tex}[job["mode"]]()
except Exception as e:                                     # noqa: BLE001 - reported to gBox
    import traceback
    res.update(ok=False, error=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-2000:])
json.dump(res, open(os.path.splitext(job_path)[0] + ".result.json", "w"), indent=1)
