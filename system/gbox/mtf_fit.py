"""Fit a collection model's skeleton onto an MT Framework model's skeleton: roles, mapping, remapped vertices.

The correspondence problem has two solved halves that this joins together:

* `gbox.mt_model.bone_roles()` derives a target's roles from where its bones actually are (validated: Chris, height
  180.7 cm, head at y 185.1, hands at x +-88.1; Sheva 162.6 / 165.8 / +-74.7);
* the fitting convention already used for RE4 GC is `b<id>` joint names, which is what `re4gc_models.gltf_to_bin` takes and
  what `char_swap.glb_merge_joints` merges by.

This module supplies the missing middle: read a GLB's joints and their world positions, derive the same roles on the source,
pair them with the target's, and give a source-joint -> target-bone mapping that a fitted mesh can be remapped with. Bones
that no role names are paired by position after scaling the source to the target's height, which is what the profiles in
`re4gc_enemies._profiled` do for the GC skeletons.

Nothing here writes a game file: it produces the mapping and the remapped vertices, so that the writing step
(`mt_model.pack_vertices` + `replace_part`) can be tested separately.
"""
from __future__ import annotations

import math
import struct

from . import mt_model


class FitError(ValueError):
    """The pair cannot be fitted - a skeleton with no distinguishable roles, or an unreadable GLB."""


def _node_matrix(node: dict) -> list[float]:
    """A node's 4x4 matrix, from `matrix` or from its TRS, column-major as glTF stores it."""
    if isinstance(node.get("matrix"), list) and len(node["matrix"]) == 16:
        return [float(v) for v in node["matrix"]]
    t = node.get("translation") or [0.0, 0.0, 0.0]
    r = node.get("rotation") or [0.0, 0.0, 0.0, 1.0]
    s = node.get("scale") or [1.0, 1.0, 1.0]
    x, y, z, w = [float(v) for v in r]
    rot = [1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w), 0.0,
           2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w), 0.0,
           2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y), 0.0,
           0.0, 0.0, 0.0, 1.0]
    for column in range(3):
        for row in range(3):
            rot[column * 4 + row] *= float(s[column])
    rot[12], rot[13], rot[14] = float(t[0]), float(t[1]), float(t[2])
    return rot


def _mul(a: list[float], b: list[float]) -> list[float]:
    return [sum(a[r + 4 * k] * b[k + 4 * c] for k in range(4)) for c in range(4) for r in range(4)]


def joint_positions(gltf: dict) -> list[tuple[int, tuple[float, float, float]]]:
    """(node index, world position) for every joint of the first skin, composed down the node tree."""
    nodes = gltf.get("nodes") or []
    skins = gltf.get("skins") or []
    if not nodes or not skins:
        raise FitError("this GLB has no skin")
    joints = list(skins[0].get("joints") or [])
    if not joints:
        raise FitError("this GLB's skin names no joints")
    world: dict[int, list[float]] = {}
    scene = gltf.get("scenes") or [{}]
    roots = scene[0].get("nodes") or [0]
    stack = [(index, None) for index in roots]
    while stack:
        index, parent = stack.pop()
        if not 0 <= index < len(nodes):
            continue
        matrix = _node_matrix(nodes[index])
        world[index] = matrix if parent is None else _mul(world[parent], matrix)
        for child in nodes[index].get("children") or []:
            stack.append((child, index))
    return [(index, (world[index][12], world[index][13], world[index][14]))
            for index in joints if index in world]


def glb_roles(gltf: dict) -> dict:
    """The same role inference `mt_model.bone_roles` does, on a GLB's joints."""
    joints = joint_positions(gltf)
    if len(joints) < 4:
        raise FitError("too few joints to infer roles")
    highest = max(joints, key=lambda j: j[1][1])
    lowest = min(joints, key=lambda j: j[1][1])
    left = min(joints, key=lambda j: j[1][0])
    right = max(joints, key=lambda j: j[1][0])
    return {"head": highest[0], "left_hand": left[0], "right_hand": right[0],
            "lowest": lowest[0],
            "height": highest[1][1] - lowest[1][1],
            "span": right[1][0] - left[1][0],
            "positions": {index: position for index, position in joints}}


def match(source: dict, target_roles: dict, target_points: list[tuple[int, float, float, float]]) -> dict:
    """A source joint node -> target bone mapping: roles first, then nearest after scaling by height.

    `target_points` is `mt_model.ModFile.bone_world()`'s output.
    """
    if not target_points or not target_roles.get("height"):
        raise FitError("the target has no usable skeleton")
    scale = target_roles["height"] / max(source["height"], 1e-6)
    by_role = {"head": target_roles.get("head"), "left_hand": target_roles.get("left_hand"),
               "right_hand": target_roles.get("right_hand"), "lowest": target_roles.get("lowest")}
    mapping: dict[int, int] = {}
    for role, bone in by_role.items():
        joint = source.get(role)
        if joint is not None and bone is not None:
            mapping[joint] = bone
    low = min((p[2] for p in target_points), default=0.0)
    for joint, position in source["positions"].items():
        if joint in mapping:
            continue
        # scale the source into the target's frame: same height, feet on the target's floor
        point = (position[0] * scale, (position[1] - (source["positions"][source["lowest"]][1])) * scale + low,
                 position[2] * scale)
        nearest = min(target_points, key=lambda bone: (bone[1] - point[0]) ** 2 + (bone[2] - point[1]) ** 2
                                                      + (bone[3] - point[2]) ** 2)
        mapping[joint] = nearest[0]
    return mapping


def remap_vertices(prims: list[dict], mapping: dict[int, int], target_bones: int) -> list[dict]:
    """Turn skinned vertices (joint index, weight) into MTF vertices carrying the target's bone ids."""
    out = []
    for prim in prims:
        for position, normal, uv, joints, weights in zip(prim["positions"], prim["normals"], prim["uvs"],
                                                         prim["joints"], prim["weights"]):
            pairs = sorted(zip(joints, weights), key=lambda pair: -pair[1])[:4]
            bones, mass = [], []
            for joint, weight in pairs:
                if weight <= 0:
                    continue
                bones.append(int(mapping.get(joint, 0)))
                mass.append(float(weight))
            if not bones:
                bones, mass = [0], [1.0]
            out.append({"position": position, "normal": normal, "uv": uv, "bones": bones, "weights": mass,
                        "in_range": all(0 <= b < target_bones for b in bones)})
    return out
