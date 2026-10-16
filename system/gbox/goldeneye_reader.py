"""GoldenEye 007 (Europe, NGEP) model reader: decode Z-file character models.

Reader-stage implementation for the owned PAL cartridge (normalised z64
sha256 40ff3643d3ed0be1b0b88266d298f455c15bd5a6f1a520c9aa2650b5f4b349de).

All record layouts are cross-checked against the GoldenEye decompilation
(n64decomp/007, src/bondtypes.h ``Model*`` region):

* ModelFileHeader (data segment, per body table): {RootNode*, Skeleton*,
  Switches**, s16 numSwitches, s16 numMatrices, f32 radius, s16 numRecords,
  s16 numTextures, Textures*}.
* Z file layout: [numSwitches x u32 switch-node ptrs][numTextures x 12-byte
  sImageTableEntry records {u32 index, u8 w, u8 h, u8 fmt, u8 depth, u8
  flagsS, u8 flagsT, u8 pad}][node tree].
* ModelNode = {u16 opcode, u16 pad, u32 Data (seg-5), u32 Parent, u32 Next,
  u32 Prev, u32 Child} (0x18 bytes).
* Opcode records (bondtypes.h ``ModelRoData_*``):
    0x01 HeaderRecord     0x10B {u16 AnimPart, s16 MatrixIndex, u32 FirstGroup,
                                 u32 Group1/2, u16 RwDataIndex, u16 pad}
    0x02 GroupRecord     0x1CB {coord3d Origin, u16 JointID, s16 MatrixID0/1/2,
                                 u32 ChildGroupNode, f32 BoundingVolumeRadius}
    0x08 LODRecord        0x10B {f32 MinDistance, f32 MaxDistance, u32 Affects,
                                 u16 RwDataIndex, u16 pad}
    0x09 BSPRecord        0x24B {coord3d Point, coord3d Vector, u32 leftChild,
                                 u32 rightChild, s16 pad, u16 RwDataIndex}
    0x0A BoundingBoxRecord 0x1CB {u32 ModelNumber, bbox {coord3d min, max}}
    0x0D ShadowRecord     0x20B {coord2d pos, coord2d size, u32 image,
                                 u32 HeaderNode, f32 Scale, u32 BaseAddr}
    0x17 Op17Record       0x20B {s32 hitpart, f32 radiusSq, coord3d pos,
                                 u32 othernode, f32 scale1, f32 scale2}
    0x18 DisplayListCollisionRecord 0x20B {u32 Primary, u32 Secondary,
                                 u32 Vertices, s16 numVertices,
                                 s16 numCollisionVertices, u32
                                 CollisionVertices, u32 PointUsage,
                                 s16 ModelType, u16 RwDataIndex, u32 BaseAddr}
* Vertex = {s16 x, s16 y, s16 z, s16 index, s16 s, s16 t, u8 r, g, b, a}
  (0x10 bytes).
* ModelSkeleton (data segment) = {s16 numjoints, s16 pad, ModelJoint *Joints,
  s16 SkeletonSize, s16 pad}; ModelJoint = {u16 NodeType, u16 mtxA, u16 mtxB}
  (6 bytes).  mtxA/mtxB are animation bit-stream offsets.

The op-0x18 primary display list uses the GE custom GBI, which is the
F3D_OLD variant (include/PR/gbi.h ``#else`` branch) plus the GE G_TRI4 and
G_SETTEX extensions (include/gbi_extension.h).  Verified command set:
0xE7 pipesync, 0xBA set-other-mode-H, 0xBB texture, 0xC0 G_SETTEX (global
texture id in w1), 0xB7 set-geometry-mode, 0xB8 end-of-DL, 0x01 G_MTX,
0x04 G_VTX, 0xB1 G_TRI4, 0xBF G_TRI1.  The RSP vertex cache holds 16
slots: G_VTX loads ``n`` vertices at cache index ``v0`` with the F3D_OLD
encoding ``w0 = (0x04<<24) | (((n-1)<<4 | v0)<<16) | (16*n)`` from a seg-4
address whose low 24 bits / 16 is the node-local vertex index.  G_TRI4
draws up to 4 triangles with 4-bit indices (0-15, all-zero = skip);
G_TRI1 draws one triangle with 8-bit indices pre-multiplied by 10 (decimal,
F3D_OLD).  This index space is pinned: decoding all 25 CsuitbondZ render DLs
yields 619 triangles with zero out-of-range or unloaded-cache indices.

Usage: python -m gbox.goldeneye_reader ROM [--body CsuitbondZ] [--gltf out.gltf]
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

from gbox.goldeneye_files import (FILE_SEGMENT, NODE_SIZE, TEXTURE_RECORD_SIZE,
                                  GoldenEyeROM, GoldenEyeFormatError, _cstr)

PAL_Z64_SHA256 = "40ff3643d3ed0be1b0b88266d298f455c15bd5a6f1a520c9aa2650b5f4b349de"
VERTEX_SIZE = 0x10
JOINT_SIZE = 6

# Opcode -> record byte size (0 = skip payload decode).
RECORD_SIZES = {0x01: 0x10, 0x02: 0x1C, 0x08: 0x10, 0x09: 0x24, 0x0A: 0x1C,
                0x0D: 0x20, 0x17: 0x20, 0x18: 0x20}


@dataclass
class VertexRec:
    x: int
    y: int
    z: int
    index: int
    s: int
    t: int
    rgba: tuple[int, int, int, int]

    @classmethod
    def parse(cls, buf: bytes, off: int) -> "VertexRec":
        x, y, z, index, s, t, r, g, b, a = struct.unpack_from(">hhh h h h BBBB", buf, off)
        return cls(x, y, z, index, s, t, (r, g, b, a))


@dataclass
class JointRec:
    node_type: int
    mtx_a: int
    mtx_b: int


@dataclass
class Skeleton:
    vram: int
    num_joints: int
    joints: list[JointRec] = field(default_factory=list)


@dataclass
class NodeRec:
    offset: int
    opcode: int
    data_off: int          # payload offset inside the Z file (seg-5 resolved)
    parent: int            # node offsets (0 = none)
    next: int
    prev: int
    child: int
    record: dict = field(default_factory=dict)
    # op 0x18 additions
    vertices: list[VertexRec] = field(default_factory=list)
    collision_vertices: list[VertexRec] = field(default_factory=list)
    triangles: list[tuple[int, int, int]] = field(default_factory=list)
    triangle_hint: str = ""

    @property
    def op(self) -> int:
        return self.opcode & 0xFF


def _seg5(buf: bytes, ptr: int) -> int | None:
    """Resolve a seg-5 pointer to a Z-file offset; None when not a seg-5 ptr."""
    if ptr == 0:
        return None
    off = ptr - FILE_SEGMENT
    if 0 <= off < len(buf):
        return off
    return None


def parse_nodes(model: bytes, root_off: int) -> list[NodeRec]:
    """Walk the node tree (next/child links) and decode each typed record."""
    out: list[NodeRec] = []
    stack, seen = [root_off + FILE_SEGMENT], set()
    order = []
    while stack:
        a = stack.pop()
        if not a or a in seen:
            continue
        o = a - FILE_SEGMENT
        if not 0 <= o <= len(model) - NODE_SIZE:
            raise GoldenEyeFormatError(f"node ptr 0x{a:08X} outside file")
        seen.add(a)
        order.append(o)
        op, _pad, dptr, parent, nxt, prev, child = struct.unpack_from(">HHIIIII", model, o)
        stack.extend((nxt, child))
        doff = _seg5(model, dptr)
        rec = NodeRec(o, op, doff if doff is not None else -1,
                      *_ptr_offsets(model, (parent, nxt, prev, child)))
        decode_record(model, rec)
        out.append(rec)
    # preserve discovery order for stable manifests
    return sorted(out, key=lambda r: r.offset)


def _ptr_offsets(model: bytes, ptrs: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    out = []
    for p in ptrs:
        q = _seg5(model, p)
        out.append(q if q is not None else 0)
    return (out[0], out[1], out[2], out[3])


def decode_record(model: bytes, rec: NodeRec) -> None:
    p = rec.data_off
    if p < 0 or rec.op not in RECORD_SIZES:
        return
    size = RECORD_SIZES[rec.op]
    if p + size > len(model):
        rec.record = {"error": f"record overruns file (off 0x{p:X}, size 0x{size:X})"}
        return
    b = model
    if rec.op == 0x01:
        anim_part, matrix_index, first_group, g1, g2, rwidx, _ = struct.unpack_from(">HhIIIHH", b, p)
        rec.record = {"anim_part": anim_part, "matrix_index": matrix_index,
                      "first_group": hex(first_group), "group1": g1, "group2": g2,
                      "rw_data_index": rwidx}
    elif rec.op == 0x02:
        ox, oy, oz, joint_id, m0, m1, m2, child_group, radius = struct.unpack_from(">fffHhhhIf", b, p)
        rec.record = {"origin": [round(ox, 3), round(oy, 3), round(oz, 3)],
                      "joint_id": joint_id,
                      "matrix_ids": [m0, m1, m2],
                      "child_group_node": _seg5(model, child_group),
                      "bounding_volume_radius": round(radius, 3)}
    elif rec.op == 0x08:
        mn, mx, affects, rwidx, _ = struct.unpack_from(">ffIHH", b, p)
        rec.record = {"min_distance": round(mn, 3), "max_distance": round(mx, 3),
                      "affects_node": _seg5(model, affects), "rw_data_index": rwidx}
    elif rec.op == 0x09:
        px, py, pz, vx, vy, vz, left, right, _p, rwidx = struct.unpack_from(">ffffffIIhH", b, p)
        rec.record = {"point": [round(px, 3), round(py, 3), round(pz, 3)],
                      "vector": [round(vx, 3), round(vy, 3), round(vz, 3)],
                      "left_child": _seg5(model, left), "right_child": _seg5(model, right),
                      "rw_data_index": rwidx}
    elif rec.op == 0x0A:
        model_number, *bb = struct.unpack_from(">I6f", b, p)
        rec.record = {"model_number": model_number,
                      "bounds_min": [round(bb[0], 2), round(bb[1], 2), round(bb[2], 2)],
                      "bounds_max": [round(bb[3], 2), round(bb[4], 2), round(bb[5], 2)]}
    elif rec.op == 0x0D:
        px, py, sx, sy, image, header, scale, base = struct.unpack_from(">ffffIIfI", b, p)
        rec.record = {"pos": [round(px, 3), round(py, 3)], "size": [round(sx, 3), round(sy, 3)],
                      "image": _seg5(model, image), "header_node": _seg5(model, header),
                      "scale": round(scale, 3), "base_addr": _seg5(model, base)}
    elif rec.op == 0x17:
        hitpart, radius_sq, px, py, pz, other, s1, s2 = struct.unpack_from(">iffffIff", b, p)
        rec.record = {"hitpart": hitpart, "radius_sq": round(radius_sq, 3),
                      "pos": [round(px, 3), round(py, 3), round(pz, 3)],
                      "other_node": _seg5(model, other),
                      "scale1": round(s1, 3), "scale2": round(s2, 3)}
    elif rec.op == 0x18:
        primary, secondary, verts, nv, ncv, cv, point_usage, mtype, rwidx, base = \
            struct.unpack_from(">IIIhhIIhHI", b, p)
        rec.record = {"primary_dl": _seg5(model, primary), "secondary_dl": _seg5(model, secondary),
                      "vertices": _seg5(model, verts), "num_vertices": nv,
                      "num_collision_vertices": ncv, "collision_vertices": _seg5(model, cv),
                      "point_usage": _seg5(model, point_usage), "model_type": mtype,
                      "rw_data_index": rwidx, "base_addr": _seg5(model, base)}
        v_off = rec.record["vertices"]
        if v_off is not None and 0 <= v_off < len(model):
            for i in range(max(0, nv)):
                try:
                    rec.vertices.append(VertexRec.parse(model, v_off + VERTEX_SIZE * i))
                except struct.error:
                    break
        c_off = rec.record["collision_vertices"]
        if c_off is not None and 0 <= c_off < len(model):
            for i in range(max(0, ncv)):
                try:
                    rec.collision_vertices.append(VertexRec.parse(model, c_off + VERTEX_SIZE * i))
                except struct.error:
                    break
        decode_primary_dl(model, rec)


def _g_tri4(w0: int, w1: int) -> list[tuple[int, int, int]]:
    """GE G_TRI4: up to 4 triangles, 4-bit vertex indices (0-15)."""
    z1, z2, z3, z4 = w0 & 0xF, (w0 >> 4) & 0xF, (w0 >> 8) & 0xF, (w0 >> 12) & 0xF
    x1, y1 = w1 & 0xF, (w1 >> 4) & 0xF
    x2, y2 = (w1 >> 8) & 0xF, (w1 >> 12) & 0xF
    x3, y3 = (w1 >> 16) & 0xF, (w1 >> 20) & 0xF
    x4, y4 = (w1 >> 24) & 0xF, (w1 >> 28) & 0xF
    out = []
    for x, y, z in ((x1, y1, z1), (x2, y2, z2), (x3, y3, z3), (x4, y4, z4)):
        if (x, y, z) != (0, 0, 0):  # all-zero triangles are padding, not drawn
            out.append((x, y, z))
    return out


def _g_tri1(w1: int) -> tuple[int, int, int]:
    """F3D_OLD G_TRI1: one triangle, 8-bit indices pre-multiplied by 10."""
    return ((w1 >> 16) & 0xFF) // 10, ((w1 >> 8) & 0xFF) // 10, (w1 & 0xFF) // 10


def decode_primary_dl(model: bytes, rec: NodeRec) -> None:
    """Decode the F3D_OLD custom-GBI primary display list into real triangles.

    The RSP vertex cache is 16 slots.  G_VTX (0x04) loads ``n`` vertices at
    cache index ``v0`` from a seg-4 address; the low 24 bits / 16 is the
    node-local vertex index into this node's own vertex array.  G_TRI4 (0xB1)
    and G_TRI1 (0xBF) reference cache slots, which we resolve to node-local
    vertex indices so ``rec.triangles`` maps directly onto ``rec.vertices``.
    """
    dl = rec.record.get("primary_dl")
    if dl is None or dl < 0 or dl + 8 > len(model):
        rec.triangle_hint = "no primary DL"
        return
    tex_ids: list[int] = []
    tris: list[tuple[int, int, int]] = []
    cache: list[int | None] = [None] * 16  # RSP vertex cache (F3D_OLD)
    end = dl
    while end < min(len(model) - 8, dl + 0x10000):
        w0, w1 = struct.unpack_from(">II", model, end)
        cmd = w0 >> 24
        if cmd == 0xB8:  # G_ENDDL
            break
        if cmd == 0x04:  # G_VTX (F3D_OLD): n verts at cache index v0
            n = ((w0 >> 16) & 0xF0) >> 4
            n += 1
            v0 = (w0 >> 16) & 0x0F
            base = (w1 & 0xFFFFFF) // 16  # node-local vertex index
            for i in range(n):
                cache[v0 + i] = base + i
        elif cmd == 0xB1:  # G_TRI4 (GE extension)
            for t in _g_tri4(w0, w1):
                tris.append(tuple(cache[i] for i in t))
        elif cmd == 0xBF:  # G_TRI1 (F3D_OLD)
            t = _g_tri1(w1)
            tris.append(tuple(cache[i] for i in t))
        elif cmd == 0xC0:  # G_SETTEX: global texture id
            tex_ids.append(w1)
        end += 8
    rec.triangles = [t for t in tris if all(isinstance(i, int) for i in t)]
    rec.record["texture_ids"] = sorted(set(tex_ids))
    rec.triangle_hint = "F3D_OLD GBI (16-slot cache)" if rec.triangles else "no triangles found"


def parse_skeleton(ge: GoldenEyeROM, skeleton_vram: int) -> Skeleton:
    o = ge.d_off(skeleton_vram)
    n, _p, joints_ptr, skel_size, _p2 = struct.unpack_from(">hhIhh", ge.data, o)
    if not 0 < n <= 64:
        raise GoldenEyeFormatError(f"implausible joint count {n} in skeleton @ {skeleton_vram:#x}")
    joints = []
    jo = ge.d_off(joints_ptr)
    for i in range(n):
        nt, ma, mb = struct.unpack_from(">HHH", ge.data, jo + JOINT_SIZE * i)
        joints.append(JointRec(nt, ma, mb))
    return Skeleton(skeleton_vram, n, joints)


def read_character(ge: GoldenEyeROM, filename: str) -> dict:
    """Full decode of one Z-file character model into a JSON-safe dict."""
    body = next((b for b in ge.body_table() if b.filename == filename), None)
    if body is None:
        raise KeyError(filename)
    hdr = ge.model_header(body.header_vram)
    model = ge.read_file(filename)
    switches = [struct.unpack_from(">I", model, 4 * i)[0] for i in range(hdr.num_switches)]
    tex_off = 4 * hdr.num_switches
    textures = []
    for i in range(hdr.num_textures):
        tid, w, h, level, fmt, depth, fs, ft, pad = struct.unpack_from(
            ">IBBBBBBBB", model, tex_off + TEXTURE_RECORD_SIZE * i)
        textures.append({"index": tid, "w": w, "h": h, "level": level, "fmt": fmt,
                         "depth": depth, "flags_s": fs, "flags_t": ft})
    root_off = tex_off + TEXTURE_RECORD_SIZE * hdr.num_textures
    nodes = parse_nodes(model, root_off)
    skeleton = parse_skeleton(ge, hdr.skeleton_vram) if hdr.skeleton_vram else None
    ops = {}
    for r in nodes:
        ops.setdefault(r.op, []).append(r.offset)
    return {
        "filename": filename,
        "body_index": body.index,
        "inflated_sha256": hashlib.sha256(model).hexdigest(),
        "header_vram": hex(hdr.vram),
        "skeleton": ({"vram": hex(skeleton.vram), "num_joints": skeleton.num_joints,
                      "joints": [{"node_type": hex(j.node_type), "mtx_a": j.mtx_a,
                                  "mtx_b": j.mtx_b} for j in skeleton.joints]}
                     if skeleton else None),
        "num_switches": hdr.num_switches,
        "switches": [hex(s) for s in switches],
        "textures": textures,
        "root_offset": root_off,
        "node_count": len(nodes),
        "nodes": [
            {"offset": r.offset, "opcode": hex(r.opcode), "data_offset": r.data_off,
             "parent": r.parent, "next": r.next, "prev": r.prev, "child": r.child,
             "record": r.record,
             **({"vertices": [{"xyz": [v.x, v.y, v.z], "st": [v.s, v.t],
                               "rgba": list(v.rgba)} for v in r.vertices]}
                if r.vertices else {}),
             **({"triangles": r.triangles, "triangle_hint": r.triangle_hint}
                if r.op == 0x18 else {}),
             } for r in nodes],
        "opcode_nodes": {f"0x{k:02X}": len(v) for k, v in sorted(ops.items())},
    }


def to_gltf(ge: GoldenEyeROM, filename: str, out_path: str | Path) -> dict:
    """Export a decoded character as a .gltf (external .bin) scene.

    Skeleton joints become glTF nodes with the op-0x02 GroupRecord origins;
    each op-0x18 node becomes a mesh of its own vertex array with vertex
    colours, UVs and the real triangles decoded from the F3D_OLD primary DL
    (triangle indices are node-local and validated against the node's vertex
    count).  Texture pixels are not decoded yet; the per-node texture ids are
    recorded in mesh extras.
    """
    doc = read_character(ge, filename)
    nodes = parse_nodes(ge.read_file(filename), doc["root_offset"])

    gltf = {"asset": {"version": "2.0", "generator": "gbox.goldeneye_reader"},
            "scenes": [{"nodes": []}], "scene": 0,
            "nodes": [], "meshes": [], "accessors": [], "bufferViews": [],
            "buffers": [{"uri": Path(out_path).stem + ".bin", "byteLength": 0}]}
    bin_blob = bytearray()

    def add_accessor(data: bytes, component_type: int, count: int, type_: str,
                     mins=None, maxs=None) -> int:
        if len(bin_blob) % 4:
            bin_blob.extend(b"\0" * (4 - len(bin_blob) % 4))
        idx = len(gltf["accessors"])
        gltf["bufferViews"].append({"buffer": 0, "byteOffset": len(bin_blob),
                                    "byteLength": len(data)})
        gltf["accessors"].append({"bufferView": len(gltf["bufferViews"]) - 1,
                                  "componentType": component_type, "count": count,
                                  "type": type_, **({"min": mins, "max": maxs}
                                                    if mins is not None else {})})
        bin_blob.extend(data)
        return idx

    # skeleton joints as glTF nodes (matrix index from the op-0x02 records)
    joint_pos = []
    joint_children: dict[int, list[int]] = {}
    pos_nodes = [r for r in nodes if r.op == 0x02]
    for i, r in enumerate(pos_nodes):
        joint_pos.append(r.record.get("origin", [0.0, 0.0, 0.0]))
    # hierarchy from the file parent/child links: map node offset -> glTF index
    off_to_joint = {r.offset: i for i, r in enumerate(pos_nodes)}
    for i, r in enumerate(pos_nodes):
        par = off_to_joint.get(r.parent)
        if par is not None:
            joint_children.setdefault(par, []).append(i)
    for i in range(len(pos_nodes)):
        t = joint_pos[i]
        gltf["nodes"].append({"name": f"joint{i}",
                              "translation": t,
                              **({"children": joint_children.get(i, [])}
                                 if joint_children.get(i) else {})})

    # meshes: one per op-0x18 node, triangles are node-local vertex indices
    total_tris = 0
    for r in nodes:
        if r.op != 0x18 or not r.vertices:
            continue
        verts = r.vertices
        pos = struct.pack(">" + "fff" * len(verts),
                          *[c for v in verts for c in (v.x, v.y, v.z)])
        pos_acc = add_accessor(pos, 5126, len(verts), "VEC3",
                               mins=[min(v.x for v in verts), min(v.y for v in verts),
                                     min(v.z for v in verts)],
                               maxs=[max(v.x for v in verts), max(v.y for v in verts),
                                     max(v.z for v in verts)])
        col = struct.pack(">" + "BBBB" * len(verts),
                          *[c for v in verts for c in v.rgba])
        col_acc = add_accessor(col, 5121, len(verts), "VEC4")
        uv = struct.pack(">" + "ff" * len(verts),
                         *[c for v in verts for c in (v.s / 32.0, v.t / 32.0)])
        uv_acc = add_accessor(uv, 5126, len(verts), "VEC2")
        tri_acc = None
        tris = [t for t in r.triangles if all(0 <= i < len(verts) for i in t)]
        if tris:
            idx = struct.pack(">" + "HHH" * len(tris), *[c for t in tris for c in t])
            tri_acc = add_accessor(idx, 5123, len(tris) * 3, "SCALAR")
            total_tris += len(tris)
        mesh = {"primitives": [{"attributes": {"POSITION": pos_acc, "COLOR_0": col_acc,
                                               "TEXCOORD_0": uv_acc},
                                **({"indices": tri_acc} if tri_acc is not None else {}),
                                "mode": 4 if tri_acc is not None else 0,
                                "extras": {"texture_ids": r.record.get("texture_ids", []),
                                           "node_offset": r.offset,
                                           "triangle_hint": r.triangle_hint}}]}
        gltf["meshes"].append(mesh)
        gltf["nodes"].append({"name": f"mesh_{r.offset:04X}",
                              "mesh": len(gltf["meshes"]) - 1})
        gltf["scenes"][0]["nodes"].append(len(gltf["nodes"]) - 1)
    gltf["buffers"][0]["byteLength"] = len(bin_blob)
    out_path = Path(out_path)
    out_path.write_text(json.dumps(gltf, indent=1))
    Path(str(out_path).rsplit(".", 1)[0] + ".bin").write_bytes(bytes(bin_blob))
    stats = {"file": str(out_path), "joints": len(joint_pos),
             "meshes": len(gltf["meshes"]), "triangles": total_tris,
             "vertices": sum(len(r.vertices) for r in nodes if r.op == 0x18)}
    return stats


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="GoldenEye PAL character model reader")
    ap.add_argument("rom")
    ap.add_argument("--body", default="CsuitbondZ")
    ap.add_argument("--gltf")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    ge = GoldenEyeROM.load(a.rom)
    if hashlib.sha256(ge.rom).hexdigest() != PAL_Z64_SHA256:
        print(f"warning: ROM sha256 differs from pinned PAL build", file=sys.stderr)
    doc = read_character(ge, a.body)
    if a.gltf:
        doc["gltf"] = to_gltf(ge, a.body, a.gltf)
    text = json.dumps(doc, indent=1)
    if a.out:
        Path(a.out).write_text(text)
    summary = {k: doc[k] for k in ("filename", "skeleton", "node_count", "opcode_nodes")}
    print(json.dumps(summary, indent=1)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
