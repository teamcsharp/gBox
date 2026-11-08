"""A donor BIN that keeps its skinning, so a band transfer can use the donor's own bones.

The first converter (`glb_to_donor_bin`) flattened a `.glb` to a triangle soup: no weights, so `band_affine` had to band it by height,
which put a thin slice of surface in each band and only read at blends high enough to hang the stage (measured in round 102). Keeping the
joints fixes that: each vertex carries the joint that drives it, so the donor bands **by bone** exactly like a pack does, and the
transfer has real parts to match against.

The BIN only needs the donor's skeleton and per-vertex joint indices - its geometry is the source model's, and the template pack supplies
the container's header and material table.
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox import characters
from gbox import re4gc_inventory as INV
from gbox import re4hd_models as R

TEMPLATE_PACK = os.path.join(os.path.expanduser("~/gBox_alt/switch/romfs"),
                             "010099A00BC1E000/bio4/em/em16.udas")


def skinned_soup(path: str):
    """(positions (N,3), triangles (M,3), joint index per vertex (N,), joint parents, joint positions).

    Every mesh that carries JOINTS_0 contributes its vertices with the joint that dominates them; a mesh without skinning contributes
    with joint 0, so a mixed model still converts.
    """
    gl, acc, _image, world = characters._load(path)
    joints: list[int] = []
    for skin in gl.get("skins", []):
        for joint in skin.get("joints", []):
            if joint not in joints:
                joints.append(joint)
    index_of = {node: i for i, node in enumerate(joints)}

    parent_of_node = {}
    for node_index, node in enumerate(gl.get("nodes") or []):
        for child in node.get("children") or []:
            parent_of_node[child] = node_index

    positions, triangles, joint_of_vertex = [], [], []
    for node_index, node in enumerate(gl.get("nodes") or []):
        if "mesh" not in node:
            continue
        skin = gl["skins"][node["skin"]] if "skin" in node else None
        for primitive in gl["meshes"][node["mesh"]]["primitives"]:
            attributes = primitive["attributes"]
            if "POSITION" not in attributes:
                continue
            P = acc(attributes["POSITION"]).astype(np.float64)
            if skin is not None and "JOINTS_0" in attributes and "WEIGHTS_0" in attributes:
                J = acc(attributes["JOINTS_0"]).astype(int)
                W = acc(attributes["WEIGHTS_0"]).astype(float)
                local = J[np.arange(len(P)), W.argmax(1)]
                mapped = np.array([index_of.get(int(skin["joints"][k]), 0) if k < len(skin["joints"]) else 0
                                   for k in local], np.int64)
            else:
                mapped = np.zeros(len(P), np.int64)
            base = sum(len(p) for p in positions)
            positions.append(P)
            joint_of_vertex.append(mapped)
            if "indices" in primitive:
                indices = acc(primitive["indices"]).astype(np.int64).reshape(-1, 3)
            else:
                indices = np.arange(len(P), dtype=np.int64).reshape(-1, 3)
            triangles.append(indices + base)

    if not positions:
        raise ValueError(f"{path}: no mesh with positions")
    points = np.concatenate(positions)
    tris = np.concatenate(triangles)
    joint_ids = np.concatenate(joint_of_vertex)

    parents = [index_of.get(parent_of_node.get(node), -1) for node in joints]
    # world positions of the joints, from the node world matrices the loader already computed
    joint_positions = [np.asarray(world[node])[:3, 3].astype(float) for node in joints]
    return points, tris, joint_ids, parents, joint_positions


def donor_bin(path: str, template_pack: str = TEMPLATE_PACK) -> bytes:
    """A donor BIN with the .glb's geometry *and* its skeleton, ready for a bone-banded transfer."""
    data = open(template_pack, "rb").read()
    slot = INV.bin_slots(data, endian="<")[0]
    template = R.bin_read(data[slot["offset"]:slot["offset"] + slot["size"]])

    points, tris, joint_ids, parents, joint_positions = skinned_soup(path)
    bones, weights = [], []
    for index, (parent, position) in enumerate(zip(parents, joint_positions)):
        origin = np.zeros(3) if parent < 0 else joint_positions[parent]
        local = np.asarray(position, float) - origin
        bones.append({"id": index, "parent": 0xFF if parent < 0 else parent,
                      "x": float(local[0]), "y": float(local[1]), "z": float(local[2])})
        weights.append((index, 0, 0, 1, 100, 0, 0, 0))
    # The BIN's weight table is the template's: a 60-joint donor does not fit an 8-record one. Bucket the joints into as many
    # records as the template allows, keeping hierarchy order, so the donor still carries a *rig* rather than a single bone.
    limit = max(1, len(template.weights or []) or 8)
    if len(weights) > limit:
        bucket = np.minimum((joint_ids * limit) // max(1, len(weights)), limit - 1)
        # a record is (bone0, bone1, bone2, count, w0, w1, w2, pad): one bone at 100%
        weights = [(int(b), 0, 0, 1, 100, 0, 0, 0) for b in range(limit)]
        joint_ids = bucket
    return R.bin_from(template, pos=points.astype(np.float32), tris=tris.astype(np.int64),
                      bones=bones, weights=weights, weight_idx=joint_ids.astype(np.int64))


if __name__ == "__main__":
    glb = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/donor_skinned.bin"
    blob = donor_bin(glb)
    open(out, "wb").write(blob)
    mesh = R.bin_read(blob)
    print(f"{glb} -> {out}: {len(blob)} bytes, {len(mesh.pos)} vertices, {len(mesh.tris)} triangles, "
          f"{len(mesh.bones)} bones, weights {len(mesh.weights or [])}")
