"""Blender headless: reduce a skinned glTF's triangle count (edge-collapse decimate) and export a .glb, keeping the
skin (vertex groups), UVs and materials. Used by gbox/re4gc_enemies.py to fit characters into RE4's file budgets.

  blender --background --factory-startup --python scripts/decimate_gltf.py -- in.gltf out.glb <ratio | target_tris>

ratio <= 1 is a fraction of the triangles, > 1 a target triangle count.
"""
import sys

import bmesh
import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
src, out, amount = argv[0], argv[1], float(argv[2])
# Optional 4th arg: comma-separated vertex-group name substrings to PROTECT from the collapse
# (head/face bones). Vertices in a matching group keep their faces while the body absorbs the
# reduction, so a character forced into a tiny slot still keeps a recognisable face.
protect = [p.strip().lower() for p in argv[3].split(",") if p.strip()] if len(argv) > 3 else []
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
meshes = [o for o in bpy.data.objects if o.type == "MESH" and o.find_armature() == arm]
for o in [o for o in bpy.data.objects if o.type == "MESH" and o not in meshes]:
    bpy.data.objects.remove(o)
tris = sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in meshes)
ratio = amount if amount <= 1 else min(1.0, amount / max(tris, 1))
before = tris
STALL = 1.15                                       # a collapse ending this far above its target stopped early


def _tris(me) -> int:
    return sum(len(p.vertices) - 2 for p in me.polygons)


def _weld(me) -> int:
    """Weld the vertex copies glTF makes at UV and normal seams, one material (glTF primitive) at a time: collapse
    sees unwelded copies as disconnected triangles and deletes faces instead of simplifying the surface. Vertices of
    different primitives are never merged: layered parts (a jacket over a shirt, eyelashes, double-sided cloth)
    share positions, and welding them makes edges with 3+ faces, which the collapse never touches. RE6 Leon's
    17162 triangles stopped at 4449 whatever the target (#1292). Edges still non-manifold are split again.
    -> how many non-manifold edges were split."""
    span = max((max(v.co[k] for v in me.vertices) - min(v.co[k] for v in me.vertices) for k in range(3)), default=0.0)
    bm = bmesh.new()
    bm.from_mesh(me)
    owner = {}
    for f in bm.faces:
        for v in f.verts:
            owner[v] = f.material_index if owner.get(v, f.material_index) == f.material_index else -1
    for mi in sorted(set(owner.values()) - {-1}):
        vs = [v for v, m in owner.items() if m == mi and v.is_valid]
        if vs:
            bmesh.ops.remove_doubles(bm, verts=vs, dist=max(span * 1e-7, 1e-9))
    bad = [e for e in bm.edges if len(e.link_faces) > 2]
    if bad:
        bmesh.ops.split_edges(bm, edges=bad)
    bm.to_mesh(me)
    bm.free()
    me.update()
    return len(bad)


def _collapse(o, r: float, vg: str = "") -> None:
    bpy.context.view_layer.objects.active = o
    d = o.modifiers.new("dec", "DECIMATE")
    d.decimate_type = "COLLAPSE"
    d.ratio = r
    d.use_collapse_triangulate = True
    if vg:
        # Blender's collapse keeps low-weight vertices and collapses high-weight ones first
        # (verified against Blender 4.0.2): the protect group tags head/face verts 0 and body 1.
        d.vertex_group = vg
        d.vertex_group_factor = 1.0
    bpy.ops.object.modifier_apply(modifier=d.name)


def _protect_group(o, substrings: list[str]) -> bool:
    """Tag head/face vertices 0.5 and everything else 1.0 in a 'protect' vertex group. Blender's collapse
    removes high-weight vertices first (verified against 4.0.2), so the face collapses at half the body's
    priority: the face keeps ~2x the triangles a uniform cut would leave, while the body absorbs the rest.
    Returns False when no group matches, so callers fall back to the plain uniform collapse."""
    if not substrings:
        return False
    weights = {}                                   # 'name' = 0.5 (half the body's priority); 'name:0.15' = its own
    for s in substrings:
        name, _, w = s.partition(":")
        try:
            weights[name] = min(1.0, max(0.0, float(w))) if w else 0.5
        except ValueError:
            weights[name] = 0.5
    keep = {}
    for g in o.vertex_groups:
        hit = [w for name, w in weights.items() if name and name in g.name.lower()]
        if hit:
            keep[g.index] = min(hit)
    if not keep:
        return False
    vg = o.vertex_groups.new(name="protect")
    for v in o.data.vertices:
        w = min((keep[g.group] for g in v.groups if g.group in keep and g.weight > 0), default=1.0)
        vg.add([v.index], w, "REPLACE")
    return True


for o in meshes:
    bpy.context.view_layer.objects.active = o
    for m in list(o.modifiers):                    # the armature deform is re-added after decimating the rest mesh
        o.modifiers.remove(m)
    if ratio < 0.999:
        n0 = _tris(o.data)
        protect_vg = _protect_group(o, protect)    # added before the copy so the retry mesh also carries it
        raw = o.data.copy()
        split = _weld(o.data)
        _collapse(o, ratio, "protect" if protect_vg else "")
        got, how = _tris(o.data), "welded"
        if got > max(n0 * ratio * STALL, n0 * ratio + 50):  # still stalled: the unwelded mesh always gets there
            welded, o.data = o.data, raw
            bpy.data.meshes.remove(welded)
            _collapse(o, ratio, "protect" if protect_vg else "")
            how = f"unwelded (the welded collapse stopped at {got})"
        else:
            bpy.data.meshes.remove(raw)
        print("DECIMATE_MESH", o.name, n0, "->", _tris(o.data), how, "split_nonmanifold", split, flush=True)
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
