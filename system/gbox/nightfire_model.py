"""007 - Nightfire (USA) GameCube (GO7E69) -- reader-stage probes for on-foot characters (#1377).

Works on a decompressed EDL level (`nightfire_analysis.level_index`). Findings pinned on the owned build
(level 07000001, Nightfire.elf sha256 ef49ce2b...3367):

HT_Skin (pack type 3, LE): a skeleton, not a mesh.
  +0x00 u32 self hash, +0x04 3x f32 scale, +0x10 five header bytes, +0x13 = attachment count
  +0x15 parent table, one byte per bone: 0xFF root, else (byte & 0x7F) = parent index (< own index)
  bind records: n_bones x 28 B (f32 pos[3], f32 quat[4] xyzw), root = identity (w = -1.0)
  then attachment records: att x 36 B (u32 id, u32 bone, f32 pos[3], f32 quat[4]), zero padding to 16
  Bondcombat 0x05000007: 73 bones, 60 attachments (4320 B); the 2144 B skins are the same 73-bone rig, 0 att.

Character models are 0x01 objects of pack type 2 (BE): header 00000000 1400000e <hash>, u32 texture
count + 12-B records (u16 id, u16 w-1, u16 h-1, u16 0x0100, 0xFFFFFFFF; Bond: 7, pixel data is NOT inside
the object -- no `60000017` chunk), then one node chunk per mesh, tag `b000000c 0000000f name[]`
followed by 40 u32 fields: [0] material groups, [1] index-stream u16 count, [2] vertex count,
[3] degenerate (strip-restart) triangle count, [4] 22 on humans, ... and 13 runtime pointers at [22..34].
The pointers are not file offsets: `_map_pointers` recovers the per-object runtime base from the vertex
array, which is the unique 0xFA-delimited block of exactly n_verts*12 B in `GC EXTRA STATIC` (type 13).
Pointer slots (indices into fields[22:35]) decoded by `node_tables` and validated on Bond 0x01000075:
  0  material groups, 20 B each: u16 flags<<12|strips, u16 triangle slots, u16 materials
     (1-2 texture ids, 0xFFFF-terminated; flag 0x2000 = two-texture group, e.g. grunt)        (DISCARD)
  1  u16 triangle count per strip; a strip of n triangles consumes n+2 stream entries      (DISCARD)
  2  u16 position index stream, fields[1] entries; GX strips are clockwise                 (DISCARD)
  3  vertices: s16 pos[3] (/8192) + s16 normal[3] (/16384)                                 (STATIC)
  4  u16 texcoord index stream, parallel to slot 2 (GX indexed TEX0)                       (DISCARD)
  5  s16 uv[2] table (/32768), max(texcoord index) + 1 entries                             (STATIC)
  8  u16 weight pair per vertex (/16384)                                                   (STATIC)
  9/10 (u16 bone, u16 count) influence runs over the vertex array in order; both tables carry the same
     counts; bone_b 255 = rigid run (weights exactly 16384/0)                              (STATIC)
  11 sparse s16 deltas (facial morph data, not decoded), 12 u16 list (not decoded).
Bond: 7 groups / 127 strips use all 3392 entries -> 2449 triangles + 689 degenerate (= fields[3]);
96 runs = 61 blended (415 verts) + 35 rigid (863 verts); 1141 UVs. The HT_Skin bind records are INVERSE
bind transforms (world -> bone, all 73 Bondcombat rotations identity): bone origins (-t) span the mesh
extents and rigid runs sit on their own bone, so `export_glb` writes a skinned glTF with 2-bone weights.
Textures (`60000017` chunks) are not decoded yet.
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


POS_SCALE = 1 / 8192.0    # s16 positions (GX frac 13), validated against the HT_Skin bind extents
NRM_SCALE = 1 / 16384.0   # s16 normals (frac 14), unit length
UV_SCALE = 1 / 32768.0    # s16 texcoords (frac 15); the table peaks at 32767
WEIGHT_ONE = 16384        # u16 blend weights; pairs sum to 16383..16384
NO_BONE = 255             # second-bone slot of a rigid influence run
SLOT_GROUPS, SLOT_STRIPS, SLOT_POS_IDX, SLOT_VERTS, SLOT_UV_IDX, SLOT_UVS = 0, 1, 2, 3, 4, 5
SLOT_WEIGHTS, SLOT_BONE_A, SLOT_BONE_B = 8, 9, 10


def run_weights(runs: list[tuple], raw_w, name: str = "node") -> tuple[list, list]:
    """Per-vertex (bone_a, bone_b) joints and normalised weights from the influence runs (in order)."""
    joints, weights, v = [], [], 0
    for a, b, c in runs:
        for _ in range(c):
            wa, wb = raw_w[2 * v], raw_w[2 * v + 1]
            if b == NO_BONE:
                if (wa, wb) != (WEIGHT_ONE, 0):
                    raise ValueError(f"{name}: rigid vertex {v} carries blend weights {wa}/{wb}")
                joints.append((a, 0))
                weights.append((1.0, 0.0))
            else:
                if abs(wa + wb - WEIGHT_ONE) > 2:
                    raise ValueError(f"{name}: vertex {v} weights sum to {wa + wb}")
                joints.append((a, b))
                weights.append((wa / (wa + wb), wb / (wa + wb)))
            v += 1
    return joints, weights


def strip_triangles(groups: list[dict], strip_tris: list[int], pos_idx) -> tuple[list, int]:
    """(group, c0, c1, c2) stream-corner triangles, counter-clockwise, and the degenerate count.

    A strip of n triangles consumes n+2 stream entries; GX front faces are clockwise.
    """
    tris, degenerate, o, k = [], 0, 0, 0
    for gi, g in enumerate(groups):
        for _ in range(g["strips"]):
            n = strip_tris[k]
            k += 1
            for t in range(n):
                i0 = o + t
                if len({pos_idx[i0], pos_idx[i0 + 1], pos_idx[i0 + 2]}) < 3:
                    degenerate += 1
                    continue
                tris.append((gi, i0, i0 + 2, i0 + 1) if t % 2 == 0 else (gi, i0, i0 + 1, i0 + 2))
            o += n + 2
    return tris, degenerate


def node_tables(level_data: bytes, node: dict, static_e: dict) -> dict:
    """Decode the GX tables of one skinned mesh node (layout in the module docstring); raises on misfit."""
    _, P = _map_pointers(node, static_e, level_data)
    f = node["fields"]
    name = node["name"]
    n_groups, n_index, n_verts = f[0], f[1], f[2]
    for slot in (SLOT_GROUPS, SLOT_STRIPS, SLOT_POS_IDX, SLOT_VERTS, SLOT_UV_IDX, SLOT_UVS,
                 SLOT_WEIGHTS, SLOT_BONE_A, SLOT_BONE_B):
        if not P[slot]:
            raise ValueError(f"{name}: pointer slot {slot} is null")
    groups = []
    for g in range(n_groups):
        rec = struct.unpack_from(">10H", level_data, P[SLOT_GROUPS] + 20 * g)
        mats = []
        for m in rec[2:]:
            if m == 0xFFFF:
                break
            mats.append(m)
        if not mats:
            raise ValueError(f"{name}: material group {g} lists no material")
        # high nibble of the strip count = flags (0x2000 two-texture material, 0x1000 seen with it)
        groups.append({"strips": rec[0] & 0x0FFF, "flags": rec[0] >> 12, "tri_slots": rec[1],
                       "material": mats[0], "materials": mats})
    n_strips = sum(g["strips"] for g in groups)
    strip_tris = list(struct.unpack_from(f">{n_strips}H", level_data, P[SLOT_STRIPS]))
    k = 0
    for g in groups:
        if sum(strip_tris[k:k + g["strips"]]) != g["tri_slots"]:
            raise ValueError(f"{name}: strip triangle counts do not match the group total")
        k += g["strips"]
    if sum(strip_tris) + 2 * n_strips != n_index:
        raise ValueError(f"{name}: strips use {sum(strip_tris) + 2 * n_strips} of {n_index} indices")
    pos_idx = struct.unpack_from(f">{n_index}H", level_data, P[SLOT_POS_IDX])
    uv_idx = struct.unpack_from(f">{n_index}H", level_data, P[SLOT_UV_IDX])
    if max(pos_idx) >= n_verts:
        raise ValueError(f"{name}: position index out of range")
    n_uv = max(uv_idx) + 1
    raw_uv = struct.unpack_from(f">{2 * n_uv}h", level_data, P[SLOT_UVS])
    raw_w = struct.unpack_from(f">{2 * n_verts}H", level_data, P[SLOT_WEIGHTS])
    runs, total, o = [], 0, 0
    while total < n_verts:
        a, ca = struct.unpack_from(">2H", level_data, P[SLOT_BONE_A] + o)
        b, cb = struct.unpack_from(">2H", level_data, P[SLOT_BONE_B] + o)
        if ca != cb or not ca:
            raise ValueError(f"{name}: influence run {len(runs)} counts differ ({ca}/{cb})")
        runs.append((a, b, ca))
        total += ca
        o += 4
    if total != n_verts:
        raise ValueError(f"{name}: influence runs cover {total} of {n_verts} vertices")
    joints, weights = run_weights(runs, raw_w, name)
    tris, degenerate = strip_triangles(groups, strip_tris, pos_idx)
    return {"groups": groups, "strip_tris": strip_tris, "pos_idx": pos_idx, "uv_idx": uv_idx,
            "uvs": [(raw_uv[2 * i] * UV_SCALE, raw_uv[2 * i + 1] * UV_SCALE) for i in range(n_uv)],
            "verts": vertices(level_data, P[SLOT_VERTS], n_verts), "runs": runs,
            "joints": joints, "weights": weights, "tris": tris, "degenerate": degenerate,
            "degenerate_header": f[3], "mapped_pointers": P}


def object_mesh(level_data: bytes, object_name: str = "01000075", node_index: int = 0) -> dict:
    """Decode one 0x01 object mesh node: vertices, CCW triangles, UVs and 2-bone skin weights."""
    entries = pack_index(level_data)["entries"]
    by = {e["name"].lower(): e for e in entries}
    obj = by[object_name.lower()]
    nodes = object_nodes(level_data[obj["offset"]:obj["offset"] + obj["size"]])
    if len(nodes) <= node_index:
        raise ValueError(f"{object_name}: no mesh node {node_index}")
    node = nodes[node_index]
    static_e = next(e for e in entries if e["type"] == 13)
    static = level_data[static_e["offset"]:static_e["offset"] + static_e["size"]]
    voff = vertex_block(static, node["n_verts"])
    tab = node_tables(level_data, node, static_e)
    pi = tab["pos_idx"]
    return {
        "object": obj, "node": node, "tables": tab,
        "positions": tab["verts"], "scale": POS_SCALE,
        "faces": [(pi[a], pi[b], pi[c]) for _, a, b, c in tab["tris"]],
        "vertex_block_offset": voff,
        "runtime_base": node["pointers"][3] - voff,
        "mapped_pointers": tab["mapped_pointers"],
    }


def _quat_matrix(q):
    import numpy as np
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def _matrix_quat(m) -> list[float]:
    """Rotation matrix -> glTF quaternion [x, y, z, w] with w >= 0."""
    t = m[0][0] + m[1][1] + m[2][2]
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        q = [(m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s, 0.25 * s]
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2
        q = [0.25 * s, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s, (m[2][1] - m[1][2]) / s]
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2
        q = [(m[0][1] + m[1][0]) / s, 0.25 * s, (m[1][2] + m[2][1]) / s, (m[0][2] - m[2][0]) / s]
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2
        q = [(m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, 0.25 * s, (m[1][0] - m[0][1]) / s]
    if q[3] < 0:
        q = [-c for c in q]
    return [float(c) for c in q]


def skeleton_matrices(skin: dict):
    """(inverse bind, world bind, local) 4x4 matrices per bone.

    HT_Skin bind records are inverse bind transforms (world -> bone, p' = R(q) p + t): on Bondcombat
    every rotation is identity and the origins -t span the mesh, with each rigid run on its own bone.
    """
    import numpy as np
    ibm = []
    for b in skin["bind"]:
        m = np.eye(4)
        m[:3, :3] = _quat_matrix(b["quat"])
        m[:3, 3] = b["pos"]
        ibm.append(m)
    world = [np.linalg.inv(m) for m in ibm]
    local = [world[i] if par < 0 else ibm[par] @ world[i] for i, par in enumerate(skin["parents"])]
    return ibm, world, local


def rig_report(mesh: dict, skin: dict) -> dict:
    """Checks that the decoded skin binds the mesh: run/bone proximity, edge lengths, winding."""
    import numpy as np
    tab = mesh["tables"]
    V = np.array(tab["verts"], dtype=np.float64)
    P, N = V[:, :3] * POS_SCALE, V[:, 3:] * NRM_SCALE
    _, world, _ = skeleton_matrices(skin)
    origins = np.array([w[:3, 3] for w in world])
    near, start, dist = [], 0, []
    for a, b, c in tab["runs"]:
        if b == NO_BONE:
            d = np.linalg.norm(origins - P[start:start + c].mean(0), axis=1)
            near.append(int((d < d[a]).sum()))
            dist.append(float(d[a]))
        start += c
    F = np.array(mesh["faces"])
    e = np.concatenate([np.linalg.norm(P[F[:, i]] - P[F[:, (i + 1) % 3]], axis=1) for i in range(3)])
    fn = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    agree = float(((fn * N[F].sum(1)).sum(1) > 0).mean())
    used = sorted({j for a, b, _ in tab["runs"] for j in (a, b) if j != NO_BONE})
    return {"faces": len(F), "degenerate": tab["degenerate"], "degenerate_header": tab["degenerate_header"],
            "vertices": len(P), "uvs": len(tab["uvs"]), "groups": len(tab["groups"]),
            "runs": len(tab["runs"]), "rigid_runs": len(near),
            "blended_vertices": sum(c for _, b, c in tab["runs"] if b != NO_BONE),
            "bones_used": used, "max_bone": max(used), "skin_bones": skin["bones"],
            "rigid_run_own_bone_nearest": sum(1 for n in near if n == 0) / max(1, len(near)),
            "rigid_run_own_bone_top4": sum(1 for n in near if n <= 3) / max(1, len(near)),
            "rigid_run_median_dist_m": float(np.median(dist)) if dist else None,
            "edge_median_m": float(np.median(e)), "edge_max_m": float(e.max()),
            "winding_agrees_with_normals": agree,
            "bone_origin_bbox": [origins.min(0).tolist(), origins.max(0).tolist()],
            "mesh_bbox": [P.min(0).tolist(), P.max(0).tolist()]}


def export_glb(level_data: bytes, out_path: str, object_name: str = "01000075",
               skin_name: str = "05000007") -> Path:
    """Export a Nightfire object node + its HT_Skin as a skinned glTF 2.0 .glb.

    One primitive per material group, vertices split per (position, texcoord) corner, JOINTS_0/WEIGHTS_0
    from the influence runs and inverse bind matrices from the HT_Skin records.  Textures are not
    decoded yet, so materials are flat colours named after the native material index.
    """
    import numpy as np

    mesh = object_mesh(level_data, object_name)
    tab = mesh["tables"]
    entries = pack_index(level_data)["entries"]
    skin_e = next(e for e in entries if e["name"].lower() == skin_name.lower())
    skin = skin_skeleton(level_data[skin_e["offset"]:skin_e["offset"] + skin_e["size"]])
    n_bones = skin["bones"]
    if max(j for jj in tab["joints"] for j in jj) >= n_bones:
        raise ValueError(f"{object_name}: influence bone outside the {n_bones}-bone skin {skin_name}")
    ibm, world, local = skeleton_matrices(skin)

    corner_of, corners = {}, []
    prim_idx = [[] for _ in tab["groups"]]
    for gi, *cs in tab["tris"]:
        for c in cs:
            key = (tab["pos_idx"][c], tab["uv_idx"][c])
            if key not in corner_of:
                corner_of[key] = len(corners)
                corners.append(key)
            prim_idx[gi].append(corner_of[key])
    V = np.array(tab["verts"], dtype=np.float64)
    pi = np.array([c[0] for c in corners])
    pos = (V[pi, :3] * POS_SCALE).astype(np.float32)
    nrm = V[pi, 3:] * NRM_SCALE
    nrm = (nrm / np.linalg.norm(nrm, axis=1, keepdims=True)).astype(np.float32)
    uv = np.array([tab["uvs"][c[1]] for c in corners], dtype=np.float32)
    jnt = np.zeros((len(corners), 4), dtype=np.uint8)
    wgt = np.zeros((len(corners), 4), dtype=np.float32)
    jnt[:, :2] = np.array(tab["joints"])[pi]
    wgt[:, :2] = np.array(tab["weights"])[pi]
    itype, ict = (np.uint16, 5123) if len(corners) < 65536 else (np.uint32, 5125)

    blob, views, accs = bytearray(), [], []

    def add(arr, comp, typ, target=None, minmax=False):
        while len(blob) % 4:
            blob.append(0)
        b = np.ascontiguousarray(arr).tobytes()
        view = {"buffer": 0, "byteOffset": len(blob), "byteLength": len(b)}
        if target:
            view["target"] = target
        views.append(view)
        blob.extend(b)
        acc = {"bufferView": len(views) - 1, "componentType": comp,
               "count": int(arr.shape[0]), "type": typ}
        if minmax:
            acc["max"], acc["min"] = arr.max(axis=0).tolist(), arr.min(axis=0).tolist()
        accs.append(acc)
        return len(accs) - 1

    attrs = {"POSITION": add(pos, 5126, "VEC3", 34962, True), "NORMAL": add(nrm, 5126, "VEC3", 34962),
             "TEXCOORD_0": add(uv, 5126, "VEC2", 34962), "JOINTS_0": add(jnt, 5121, "VEC4", 34962),
             "WEIGHTS_0": add(wgt, 5126, "VEC4", 34962)}
    ibm_acc = add(np.array([m.T for m in ibm], dtype=np.float32).reshape(n_bones, 16), 5126, "MAT4")
    prims, materials = [], []
    for gi, g in enumerate(tab["groups"]):
        if not prim_idx[gi]:
            continue
        hue = (g["material"] * 0.618) % 1.0
        materials.append({"name": f"{object_name}_mat{g['material']}", "pbrMetallicRoughness": {
            "baseColorFactor": [0.55 + 0.4 * hue, 0.5, 0.95 - 0.4 * hue, 1.0],
            "metallicFactor": 0.0, "roughnessFactor": 0.85}})
        prims.append({"attributes": attrs, "indices": add(np.array(prim_idx[gi], dtype=itype), ict,
                                                          "SCALAR", 34963),
                      "mode": 4, "material": len(materials) - 1})

    nodes = []
    for i in range(n_bones):
        nodes.append({"name": f"bone_{i:02d}", "translation": [float(x) for x in local[i][:3, 3]],
                      "rotation": _matrix_quat(local[i][:3, :3])})
    roots = []
    for i, par in enumerate(skin["parents"]):
        if par >= 0:
            nodes[par].setdefault("children", []).append(i)
        else:
            roots.append(i)
    nodes.append({"name": mesh["node"]["name"], "mesh": 0, "skin": 0})
    nodes.append({"name": f"Nightfire_{object_name}", "children": roots + [n_bones]})
    gltf = {
        "asset": {"version": "2.0", "generator": "gbox.nightfire_model",
                  "extras": {"object": object_name, "skin": skin_name, "node": mesh["node"]["name"],
                             "triangles": len(tab["tris"]), "native_vertices": len(V),
                             "uvs": len(tab["uvs"]), "textures": "not decoded"}},
        "scene": 0, "scenes": [{"nodes": [n_bones + 1]}],
        "nodes": nodes, "meshes": [{"name": mesh["node"]["name"], "primitives": prims}],
        "skins": [{"joints": list(range(n_bones)), "inverseBindMatrices": ibm_acc, "skeleton": roots[0]}],
        "materials": materials, "accessors": accs, "bufferViews": views,
        "buffers": [{"byteLength": 0}],
    }
    while len(blob) % 4:
        blob.append(0)
    gltf["buffers"][0]["byteLength"] = len(blob)
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    out = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(blob)) \
        + struct.pack("<II", len(js), 0x4E4F534A) + js \
        + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_bytes(out)
    return Path(out_path)


def write_obj(path, verts: list[tuple], scale: float = 1 / 8192.0) -> None:
    """Point cloud + normals OBJ preview."""
    with open(path, "w") as fh:
        for v in verts:
            fh.write(f"v {v[0] * scale:.5f} {v[1] * scale:.5f} {v[2] * scale:.5f}\n")
        for v in verts:
            fh.write(f"vn {v[3] / 16384:.5f} {v[4] / 16384:.5f} {v[5] / 16384:.5f}\n")
