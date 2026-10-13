"""007 - Nightfire (USA) GameCube (GO7E69) -- reader-stage probes for on-foot characters (#1377).

Works on a decompressed EDL level (`nightfire_analysis.level_index`). Findings pinned on the owned build
(level 07000001, Nightfire.elf sha256 ef49ce2b...3367):

HT_Skin (pack type 3, LE): a skeleton, not a mesh.
  +0x00 u32 self hash, +0x04 3x f32 scale, +0x10 five header bytes, +0x13 = attachment count
  +0x15 parent table, one byte per bone: 0xFF root, else (byte & 0x7F) = parent index (< own index)
  bind records: n_bones x 28 B (f32 pos[3], f32 quat[4] xyzw), root = identity (w = -1.0)
  then attachment records: att x 36 B (u32 id, u32 bone, f32 pos[3], f32 quat[4]), zero padding to 16
  Bondcombat 0x05000007: 73 bones, 60 attachments (4320 B); the 2144 B skins are the same 73-bone rig, 0 att.

Character models are 0x01 objects of pack type 2 (BE): header 00000000 1400000e <hash>, texture table,
`60000017` texture chunks (name + GX data), then one node chunk per mesh, tag `b000000c 0000000f name[]`
followed by u32 fields: [0] ?, [1] index-stream u16 count, [2] vertex count, [3] second vertex set count,
[4] matrix groups (22 on humans), [5] 239, [6] 0x8a0 ... and pointer fields at [22..34]. The pointers are
NOT file offsets; their per-object base differs. Within one object the deltas are exact, e.g. pointer[25]
(vertex array) -> pointer[27] spans n_verts*12 + 0x20 B.

Vertex arrays live in the level's `GC EXTRA STATIC` entry (pack type 13): blocks separated by 0xFA runs,
12 B per vertex = s16 pos[3] + s16 normal[3] (normal / 16384 is unit length). `vertex_block` finds the
object's block as the unique 0xFA-delimited block of exactly n_verts*12 B (verified unique for the Bond model
0x01000075 'bond_generic_head_g' 1278 verts, 0x0100007a 1220, 0x01000092 1037). Position scale is not yet
proven (s16/8192 gives a 1.92 m figure). Face/strip streams (u16, value < n_verts) sit in `GC EXTRA DISCARD`
(type 14); the strip-length table and the bone-weight blocks are the open reader work.
"""
from __future__ import annotations

import json
import math
import re
import struct
from pathlib import Path

from .nightfire_inventory import pack_index

NODE_TAG = b"\xb0\x00\x00\x0c"
FA_RUN = re.compile(rb"\xfa{8,}")


def skin_skeleton(payload: bytes) -> dict:
    """Parse an HT_Skin payload into parents, bind pose and attachment points (validated, raises on misfit)."""
    if len(payload) < 0x64:
        raise ValueError("skin payload too short")
    h, sx, sy, sz = struct.unpack_from("<I3f", payload, 0)
    att = payload[0x13]
    for n in range(1, 128):
        par = list(payload[0x15:0x15 + n])
        if len(par) < n or par[0] != 0xFF or any((p & 0x7F) >= i for i, p in enumerate(par) if i):
            break
        for bind in range((0x15 + n + 3) & ~3, (0x15 + n + 3 & ~3) + 16, 4):
            end = bind + 28 * n + 36 * att
            if end > len(payload) or len(payload) - end >= 32 or any(payload[end:]):
                continue
            bones = [struct.unpack_from("<7f", payload, bind + 28 * i) for i in range(n)]
            if not all(abs(math.sqrt(sum(q * q for q in b[3:])) - 1.0) < 1e-3 for b in bones):
                continue
            if any(abs(c) > 1e-6 for c in bones[0][:6]):
                continue
            atts = []
            for k in range(att):
                o = bind + 28 * n + 36 * k
                aid, bone = struct.unpack_from("<2I", payload, o)
                if bone >= n:
                    break
                atts.append({"id": aid, "bone": bone, "pos": list(struct.unpack_from("<3f", payload, o + 8)),
                             "quat": list(struct.unpack_from("<4f", payload, o + 20))})
            else:
                return {"hash": f"{h:#010x}", "scale": [sx, sy, sz], "head": list(payload[0x10:0x15]),
                        "bones": n, "bind_offset": bind,
                        "parents": [-1 if p == 0xFF else p & 0x7F for p in par],
                        "parent_flags": [p >> 7 if p != 0xFF else 0 for p in par],
                        "bind": [{"pos": list(b[:3]), "quat": list(b[3:])} for b in bones],
                        "attachments": atts}
    raise ValueError("no consistent bone count / bind layout for this skin")


def object_nodes(payload: bytes) -> list[dict]:
    """Mesh node chunks of a 0x01 object (BE): name, the 40 u32 fields after the name."""
    if payload[:8] != b"\0\0\0\0\x14\0\0\x0e":
        raise ValueError("not a 0x01 object payload")
    out = []
    for m in re.finditer(re.escape(NODE_TAG), payload):
        o = m.start()
        if o + 0x1C + 160 > len(payload) or payload[o + 4:o + 8] != b"\0\0\0\x0f":
            continue
        name = payload[o + 8:o + 0x1C].split(b"\0")[0].decode("latin-1")
        f = list(struct.unpack_from(">40I", payload, o + 0x1C))
        out.append({"offset": o, "name": name, "fields": f, "n_index": f[1], "n_verts": f[2],
                    "n_verts2": f[3], "groups": f[4], "pointers": f[22:35]})
    return out


def fa_blocks(static: bytes) -> list[tuple[int, int]]:
    """(offset, size) of the data blocks between 0xFA padding runs of a GC EXTRA STATIC entry."""
    runs = [(m.start(), m.end()) for m in FA_RUN.finditer(static)]
    return [(b, (runs[i + 1][0] if i + 1 < len(runs) else len(static)) - b) for i, (_, b) in enumerate(runs)]


def vertex_block(static: bytes, n_verts: int) -> int:
    """Offset of the unique 0xFA-delimited block holding exactly n_verts 12-byte vertices."""
    hits = [o for o, n in fa_blocks(static) if n == 12 * n_verts]
    if len(hits) != 1:
        raise ValueError(f"{len(hits)} candidate vertex blocks for {n_verts} verts")
    return hits[0]


def vertices(static: bytes, offset: int, n_verts: int) -> list[tuple]:
    """Raw (x, y, z, nx, ny, nz) s16 records; normals are /16384."""
    return [struct.unpack_from(">6h", static, offset + 12 * i) for i in range(n_verts)]


def normal_stats(verts: list[tuple]) -> dict:
    lens = [math.sqrt(v[3] ** 2 + v[4] ** 2 + v[5] ** 2) / 16384.0 for v in verts]
    return {"min": min(lens), "max": max(lens), "mean": sum(lens) / len(lens)}


def _map_pointers(node: dict, static_entry: dict, level_data: bytes) -> tuple[int, list[int]]:
    """Turn the 13 runtime pointers in a mesh node into file offsets in the level data.

    The vertex-array pointer (local index 3 = fields[25]) points into the GC EXTRA STATIC
    region.  Using the unique 0xFA-delimited vertex block for n_verts we recover the runtime
    base, then every pointer p maps to file offset p + K where K = static.offset - base.
    """
    static = level_data[static_entry["offset"]:static_entry["offset"] + static_entry["size"]]
    voff = vertex_block(static, node["n_verts"])
    ptrs = node["pointers"]
    base = ptrs[3] - voff
    K = static_entry["offset"] - base
    return K, [(p + K if p else 0) for p in ptrs]


def object_mesh(level_data: bytes, object_name: str = "01000075") -> dict:
    """Decode one 0x01 object mesh: positions, normals and a first triangle list.

    The index stream is currently treated as one long triangle strip with degenerate vertices
    skipped.  This yields a solid editable mesh for Bond's head/torso (object 0x01000075); the
    true strip-length/material-group table is still being matched.
    """
    idx = pack_index(level_data)
    entries = idx["entries"]
    by = {e["name"].lower(): e for e in entries}
    obj = by[object_name.lower()]
    nodes = object_nodes(level_data[obj["offset"]:obj["offset"] + obj["size"]])
    if not nodes:
        raise ValueError(f"{object_name}: no mesh node found")
    node = nodes[0]
    static_e = next(e for e in entries if e["type"] == 13)
    discard_e = next(e for e in entries if e["type"] == 14)
    static = level_data[static_e["offset"]:static_e["offset"] + static_e["size"]]
    discard = level_data[discard_e["offset"]:discard_e["offset"] + discard_e["size"]]
    voff = vertex_block(static, node["n_verts"])
    verts = vertices(static, voff, node["n_verts"])
    K, mapped = _map_pointers(node, static_e, level_data)
    if mapped[2] and mapped[4]:
        i0, i1 = mapped[2] - discard_e["offset"], mapped[4] - discard_e["offset"]
        indices = struct.unpack(f">{(i1 - i0) // 2}H", discard[i0:i1])
    else:
        raise ValueError(f"{object_name}: index-stream pointers are null")
    faces = []
    for a, b, c in zip(indices, indices[1:], indices[2:]):
        if a != b and b != c and a != c:
            faces.append((a, b, c))
    return {
        "object": obj, "node": node,
        "positions": verts, "scale": 1 / 8192.0,
        "faces": faces,
        "vertex_block_offset": voff,
        "runtime_base": node["pointers"][3] - voff,
        "mapped_pointers": mapped,
    }


def export_glb(level_data: bytes, out_path: str, object_name: str = "01000075",
               skin_name: str = "05000007") -> Path:
    """Export a Nightfire object + its HT_Skin skeleton as a glTF 2.0 .glb.

    The mesh is currently unweighted (inverse bind matrices are identity) so the skeleton is
    present for editing but does not yet deform the mesh.  The position scale is fixed at
    s16/8192, validated against the Bondcombat bind-pose extents.  glTF is built directly as
    JSON+binary to avoid a heavy dependency.
    """
    import numpy as np
    from .nightfire_inventory import pack_index

    mesh = object_mesh(level_data, object_name)
    idx = pack_index(level_data)
    by = {e["name"].lower(): e for e in idx["entries"]}
    skin_e = by[skin_name.lower()]
    skin = skin_skeleton(level_data[skin_e["offset"]:skin_e["offset"] + skin_e["size"]])

    pos = np.array([[v[0] * mesh["scale"], v[1] * mesh["scale"], v[2] * mesh["scale"]]
                    for v in mesh["positions"]], dtype=np.float32)
    nrm = np.array([[v[3] / 16384.0, v[4] / 16384.0, v[5] / 16384.0]
                    for v in mesh["positions"]], dtype=np.float32)
    faces = np.array(mesh["faces"], dtype=np.uint16)

    pos_b, nrm_b, idx_b = pos.tobytes(), nrm.tobytes(), faces.tobytes()
    blob = bytearray(pos_b + nrm_b + idx_b)
    n_bones = skin["bones"]
    ibm = np.tile(np.eye(4, dtype=np.float32), (n_bones, 1, 1)).tobytes()
    ibm_off = len(blob)
    blob += bytearray(ibm)
    while len(blob) % 4:
        blob.append(0)

    bvs = [
        {"buffer": 0, "byteOffset": 0, "byteLength": len(pos_b), "target": 34962},
        {"buffer": 0, "byteOffset": len(pos_b), "byteLength": len(nrm_b), "target": 34962},
        {"buffer": 0, "byteOffset": len(pos_b) + len(nrm_b), "byteLength": len(idx_b), "target": 34963},
        {"buffer": 0, "byteOffset": ibm_off, "byteLength": len(ibm), "target": 34962},
    ]
    accs = [
        {"bufferView": 0, "componentType": 5126, "count": len(pos), "type": "VEC3",
         "max": pos.max(axis=0).tolist(), "min": pos.min(axis=0).tolist()},
        {"bufferView": 1, "componentType": 5126, "count": len(nrm), "type": "VEC3"},
        {"bufferView": 2, "componentType": 5123, "count": len(faces) * 3, "type": "SCALAR"},
        {"bufferView": 3, "componentType": 5126, "count": n_bones, "type": "MAT4"},
    ]
    material = {"pbrMetallicRoughness": {
        "baseColorFactor": [0.8, 0.6, 0.5, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.8}}
    mesh_obj = {"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1},
                                 "indices": 2, "mode": 4, "material": 0}]}

    joint_nodes = []
    for i, b in enumerate(skin["bind"]):
        p, q = b["pos"], b["quat"]
        joint_nodes.append({"name": f"bone_{i:02d}", "translation": [float(x) for x in p],
                          "rotation": [float(q[0]), float(q[1]), float(q[2]), float(q[3])]})
    for i, par in enumerate(skin["parents"]):
        if par >= 0:
            joint_nodes[par].setdefault("children", []).append(i)

    root_idx = len(joint_nodes)
    skel_root = {"name": f"{skin_name}_root", "children": list(range(n_bones))}
    mesh_node = {"name": mesh["node"]["name"], "mesh": 0, "skin": 0}
    model_root = {"name": f"Nightfire_{object_name}", "children": [root_idx, root_idx + 1]}

    gltf = {
        "asset": {"version": "2.0", "generator": "gbox.nightfire_model"},
        "scene": 0,
        "scenes": [{"nodes": [len(joint_nodes) + 2]}],
        "nodes": joint_nodes + [skel_root, mesh_node, model_root],
        "meshes": [mesh_obj],
        "skins": [{"joints": list(range(n_bones)), "inverseBindMatrices": 3, "skeleton": root_idx}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": bvs,
        "accessors": accs,
        "materials": [material],
    }

    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    blob += b"\0" * (-len(blob) % 4)
    out = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(blob)) \
        + struct.pack("<II", len(js), 0x4E4F534A) + js \
        + struct.pack("<II", len(blob), 0x004E4942) + blob

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_bytes(out)
    return Path(out_path)


def write_obj(path, verts: list[tuple], scale: float = 1 / 8192.0) -> None:
    """Point cloud + normals OBJ preview (no faces yet -- the strip stream is not decoded)."""
    with open(path, "w") as fh:
        for v in verts:
            fh.write(f"v {v[0] * scale:.5f} {v[1] * scale:.5f} {v[2] * scale:.5f}\n")
        for v in verts:
            fh.write(f"vn {v[3] / 16384:.5f} {v[4] / 16384:.5f} {v[5] / 16384:.5f}\n")
