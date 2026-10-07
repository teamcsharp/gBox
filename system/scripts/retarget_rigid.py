"""Blender headless retarget: rigid-limb source character (e.g. SM64 Mario from gbox.sm64_mario) onto a target skeleton
(e.g. RE4 GC Leon from gbox.re4gc_models), then export a glTF binary (.glb) skinned to the TARGET bones only.

  blender --background --factory-startup --python scripts/retarget_rigid.py -- target.gltf source.gltf map.json out.glb

map.json:
  {"scale": 3.0,                         # source units -> target units (applied after the target's glTF scale)
   "anchor": ["j01", "b017"],            # source joint placed on target joint (torso/head ride with it)
   "parts": {"j01": {"bone": "b017"},                                  # rigid, no rotation, anchored
             "j05": {"bone": "b013", "from": ["j05", "j06"], "to": ["b013", "b014"]},  # limb: align + stretch
             "j07": {"bone": "b016", "follow": "j06", "at": "b016"},  # leaf: j06's rotation (no stretch), at bone
             "j03": {"bone": "b004", "scale_mul": 0.75, "pivot": "j03"},  # anchored, scaled about its joint
             "j11": {"bone": "b004", "from": ["j11", "@c:j11"], "to": ["b004", "b064"], "attach": "j01"}}}  # aligned, stays on j01
("to_offset": [dx, dy, dz] moves a limb's target start, in the target's Blender space (Z up);
 "follow" rules take "scale_mul"/"pivot" too: the leaf rides its parent's rotation, scaled about its own joint;
 a rigid part with "at": <target joint> sits its pivot (default: its own joint) on that joint instead of riding the
 anchor, and its "scale_mul" may be [kx, ky, kz] in Blender space (Z up), e.g. to fit a tall torso onto a short one.)
Every source vertex goes to the source joint with its largest weight; that joint's rule moves it, and the vertex is
weighted 100% to the rule's target bone. Limbs: rotate the source segment direction onto the target segment, stretch
along it to the target length, uniform scale across it; translate the segment start onto the target joint.
"""
import json
import sys

import bpy
from mathutils import Matrix, Vector

argv = sys.argv[sys.argv.index("--") + 1:]
tgt_path, src_path, map_path, out_path = argv[:4]
cfg = json.load(open(map_path))

bpy.ops.wm.read_factory_settings(use_empty=True)


def import_gltf(p):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=p)
    new = [o for o in bpy.data.objects if o not in before]
    arm = next(o for o in new if o.type == "ARMATURE")
    meshes = [o for o in new if o.type == "MESH" and o.find_armature() == arm]
    for o in new:                                          # bone-shape helper meshes etc.
        if o.type == "MESH" and o not in meshes:
            bpy.data.objects.remove(o)
    return arm, meshes


t_arm, t_meshes = import_gltf(tgt_path)
for o in t_meshes:
    bpy.data.objects.remove(o)                             # keep only the target skeleton
s_arm, s_meshes = import_gltf(src_path)
src = s_meshes[0]

T = {b.name: t_arm.matrix_world @ b.head_local for b in t_arm.data.bones}
S = {b.name: s_arm.matrix_world @ b.head_local for b in s_arm.data.bones}
scale = cfg["scale"]
a_src, a_tgt = cfg["anchor"]
parts = cfg["parts"]


def _src_point(n):
    """A source joint, or "@c:<joint>" = centroid of that joint's vertices (for leaves like feet: no child joint)."""
    if n.startswith("@c:"):
        g = src.vertex_groups[n[3:]].index
        pts = [src.matrix_world @ v.co for v in src.data.vertices
               if v.groups and max(v.groups, key=lambda x: x.weight).group == g]
        return sum(pts, Vector()) / len(pts)
    return S[n]


def limb_matrix(rule, stretch=True):
    sa, sb = _src_point(rule["from"][0]), _src_point(rule["from"][1])
    ta, tb = T[rule["to"][0]], T[rule["to"][1]]
    if "to_offset" in rule:                                # move the segment start (e.g. a hip up to the pelvis line)
        ta = ta + Vector(rule["to_offset"])
    ds, dt = (sb - sa), (tb - ta)
    rot = ds.normalized().rotation_difference(dt.normalized()).to_matrix().to_4x4()
    k = dt.length / (ds.length * scale) if ds.length > 1e-6 and stretch and not rule.get("no_stretch") else 1.0
    if "max_stretch" in cfg:
        k = min(k, cfg["max_stretch"])
    # stretch along the target direction: S = I*scale + (k-1)*scale * d d^T
    d = dt.normalized()
    st = Matrix.Diagonal((scale, scale, scale, 1.0))
    for i in range(3):
        for j in range(3):
            st[i][j] += (k - 1) * scale * d[i] * d[j]
    return Matrix.Translation(ta) @ st @ rot @ Matrix.Translation(-sa)


mats = {}
for name, rule in parts.items():
    if "to" in rule and "attach" not in rule:
        mats[name] = limb_matrix(rule)
for name, rule in parts.items():
    if "to" in rule and "attach" in rule:             # aligned like a limb, but its start stays where the parent part
        m = limb_matrix(rule)                          # ("attach") carries it (no jump onto the target joint)
        here = m @ _src_point(rule["from"][0])
        there = mats[rule["attach"]] @ _src_point(rule["from"][0])
        mats[name] = Matrix.Translation(there - here) @ m
for name, rule in parts.items():
    if "follow" in rule:
        f = limb_matrix(parts[rule["follow"]], stretch=False)   # leaf: parent's rotation, no stretch
        if "at" in rule:                                   # place the leaf's joint on a target joint
            here = f @ S[name]
            mats[name] = Matrix.Translation(T[rule["at"]] - here) @ f
        else:
            mats[name] = f
        if "scale_mul" in rule:                            # e.g. a smaller head riding on the torso
            k, pv = rule["scale_mul"], _src_point(rule.get("pivot", name))
            mats[name] = mats[name] @ Matrix.Translation(pv) @ Matrix.Diagonal((k, k, k, 1.0)) @ Matrix.Translation(-pv)
    elif "to" not in rule:                                 # anchored rigid (torso/head)
        if "at" in rule:                                   # its own anchor: pivot (default: its joint) onto a target joint
            pv = S[rule.get("pivot", name)]
            mats[name] = Matrix.Translation(T[rule["at"]]) @ Matrix.Diagonal((scale, scale, scale, 1.0)) @ Matrix.Translation(-pv)
        else:
            mats[name] = Matrix.Translation(T[a_tgt]) @ Matrix.Diagonal((scale, scale, scale, 1.0)) @ Matrix.Translation(-S[a_src])
        if "scale_mul" in rule:                            # e.g. a smaller head, scaled about its own joint
            k, pv = rule["scale_mul"], S[rule.get("pivot", name)]
            k = list(k) if isinstance(k, (list, tuple)) else [k, k, k]   # [x, y, z] in Blender space (Z up): squash a part
            mats[name] = mats[name] @ Matrix.Translation(pv) @ Matrix.Diagonal((*k, 1.0)) @ Matrix.Translation(-pv)

# evaluate the source in its bind pose, move every vertex by its joint's rule
src.modifiers.clear()
me = src.data
gname = {g.index: g.name for g in src.vertex_groups}
owner = []
for v in me.vertices:
    best = max(v.groups, key=lambda g: g.weight, default=None)
    owner.append(gname[best.group] if best else a_src)
missing = sorted({o for o in owner if o not in mats})
if missing:
    print("RETARGET WARNING: no rule for", missing, "-> anchored")
    for o in missing:
        mats[o] = mats.get(a_src) or Matrix.Identity(4)
mw = src.matrix_world
inv = mw.inverted()
for v, o in zip(me.vertices, owner):
    v.co = inv @ (mats[o] @ (mw @ v.co))
me.update()
# normals follow (glTF exporter recomputes from mesh); vertex groups -> target bones
for g in list(src.vertex_groups):
    src.vertex_groups.remove(g)
groups = {}
for i, o in enumerate(owner):
    bone = parts.get(o, parts.get(a_src))["bone"]
    if bone not in groups:
        groups[bone] = src.vertex_groups.new(name=bone)
    groups[bone].add([i], 1.0, "REPLACE")
src.parent = t_arm
src.matrix_parent_inverse = t_arm.matrix_world.inverted()
mod = src.modifiers.new("Armature", "ARMATURE")
mod.object = t_arm
bpy.data.objects.remove(s_arm)
bpy.ops.object.select_all(action="DESELECT")
t_arm.select_set(True)
src.select_set(True)
bpy.context.view_layer.objects.active = t_arm
bpy.ops.export_scene.gltf(filepath=out_path, export_format="GLB", use_selection=True, export_skins=True,
                          export_animations=False, export_yup=True, export_apply=False)
print("RETARGETED", out_path, len(me.vertices), "verts", sorted(groups))
