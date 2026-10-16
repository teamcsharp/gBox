"""GoldenEye 007 (Europe, NGEP) model reader: decode Z-file character models.

Reader-stage implementation for the owned PAL cartridge (normalised z64
sha256 40ff3643d3ed0be1b0b88266d298f455c15bd5a6f1a520c9aa2650b5f4b349de).

All record layouts are cross-checked against the GoldenEye decompilation
(n64decomp/007, src/bondtypes.h ``Model*`` region):

* ModelFileHeader (data segment, per body table): {RootNode*, Skeleton*,
  Switches**, s16 numSwitches, s16 numMatrices, f32 radius, s16 numRecords,
  s16 numTextures, ModelFileTextures*}.
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
    0x11 Op17Record       0x20B {s32 hitpart, f32 radiusSq, coord3d pos,
                                 u32 othernode, f32 scale1, f32 scale2}
    0x12 SwitchRecord      0x08B {u32 Controls, u16 RwDataIndex, u16 pad}
    0x15 GroupSimpleRecord 0x14B {coord3d Origin, s16 Group1, u16 Group2,
                                 f32 BoundingVolumeRadius}
    0x17 HeadPlaceholderRecord 0x02B {u16 RwDataIndex}  (not Op17Record,
                                 which is 0x11 -- corrected from the decomp)
    0x18 DisplayListCollisionRecord 0x20B {Gfx* Primary, Gfx* Secondary,
                                 Vertex* Vertices, s16 numVertices,
                                 s16 numCollisionVertices, Vertex*
                                 CollisionVertices, s16* PointUsage,
                                 s16 ModelType, u16 RwDataIndex, void* BaseAddr}
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

The skeleton is exported as a proper glTF ``skins`` array: the 15 op-0x02
GroupRecords (JointID 1..15) hang off the implicit root joint 0, each
render mesh (op-0x18 node) is rigidly bound to the nearest ancestor group's
JointID, and the inverse bind matrices are the negation of the accumulated
group origins.

Two ModelFileHeader fields were previously swapped: the s16 after numSwitches
is ``numMatrices`` (21 for CsuitbondZ) and the one after radius is
``numRecords`` (0) -- now named to match bondtypes.h.  The op-0x18
``PointUsage`` s16[] (one point index per render vertex, -1 = unskinned,
0..96 = the model's transform-point pool consumed by the gspFast3D RSP
microcode) is decoded per node, and ``group_matrix_map`` pins each matrix
slot (GroupRecord MatrixID0/1/2) to its owning joint.

Texture pixels are the remaining reader item.  The model's 12-byte
sImageTableEntry records name the global ``g_Textures`` index + width/height
+ Type (G_IM_FMT) + RenderDepth (G_IM_SIZ); the global table is the
"Globalimagetable" segment (ge007.ld) -- NOT the rarezip data segment, so the
US D:80049300 does not apply -- whose 6-byte ``image_entry`` stores the
per-image byte SIZE in ``dataoffset`` and is converted to cumulative offsets
by ``image_entries_load`` (0xffff terminator); the pixel bank is the ROM
"images" segment at ``_imagesSegmentRomStart``.  ``decode_image`` implements
the RGBA16/RGBA32/I4/I8/IA/CI codec; locating the PAL table/bank offsets
remains (pin ``image_entries_load`` / ``_imagesSegmentRomStart`` via a Ghidra
xref before dumping pixels).

Usage: python -m gbox.goldeneye_reader ROM [--body CsuitbondZ] [--gltf out.gltf]
"""
from __future__ import annotations

import base64
import hashlib
import json
import struct
import sys
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from gbox.goldeneye_files import (FILE_SEGMENT, NODE_SIZE, TEXTURE_RECORD_SIZE,
                                  GoldenEyeROM, GoldenEyeFormatError, _cstr)

PAL_Z64_SHA256 = "40ff3643d3ed0be1b0b88266d298f455c15bd5a6f1a520c9aa2650b5f4b349de"
VERTEX_SIZE = 0x10
JOINT_SIZE = 6

# Opcode -> record byte size (0 = skip payload decode).  Corrected against the
# decomp bondtypes.h ModelRoData_*: opcode 0x11 is the 32-byte Op17Record, and
# opcode 0x17 is the 2-byte HeadPlaceholderRecord (u16 RwDataIndex) -- the
# reader previously mis-labelled 0x17 as Op17Record and over-read 32 bytes.
RECORD_SIZES = {0x01: 0x10, 0x02: 0x1C, 0x04: 0x14, 0x08: 0x10, 0x09: 0x24,
                0x0A: 0x1C, 0x0D: 0x20, 0x11: 0x20, 0x12: 0x08, 0x15: 0x14,
                0x17: 0x02, 0x18: 0x20}

# The 80 character body/head files of the PAL body table (deterministic for
# the owned build; order == body-table index).  Used by the characters
# DEDICATED roster so game_roster can enumerate the cast without a ROM.
ROSTER_NAMES = [
    "CcamguardZ", "CgreyguardZ", "ColiveguardZ", "CrusguardZ", "CtrevguardZ",
    "CdjbondZ", "CborisZ", "CorumovZ", "CtrevelyanZ", "CboilertrevZ",
    "CvalentinZ", "CxeniaZ", "CbaronsamediZ", "CjawsZ", "CmaydayZ",
    "CoddjobZ", "CnatalyaZ", "CarmourguardZ", "CcommguardZ", "CgreatguardZ",
    "CnavyguardZ", "CsnowguardZ", "CboilerbondZ", "CsuitbondZ", "CtimberbondZ",
    "CsnowbondZ", "CbluewomanZ", "CfattechwomanZ", "CtechwomanZ", "CjeanwomanZ",
    "CgreymanZ", "CbluemanZ", "CredmanZ", "CcardimanZ", "CcheckmanZ",
    "CtechmanZ", "CpilotZ", "Cgreatguard2Z", "CbluecamguardZ", "CmoonguardZ",
    "CmoonfemaleZ", "Csuit_lf_handZ", "CheadkarlZ", "CheadalanZ", "CheadpeteZ",
    "CheadmartinZ", "CheadmarkZ", "CheadduncanZ", "CheadshaunZ", "CheaddwayneZ",
    "CheadbZ", "CheaddaveZ", "CheadgrantZ", "CheaddesZ", "CheadchrisZ",
    "CheadleeZ", "CheadneilZ", "CheadjimZ", "CheadrobinZ", "CheadstevehZ",
    "CheadbalaclavaZ", "CheadbikeZ", "CheadgrahamZ", "CheadsteveeZ",
    "CheadjoelZ", "CheadscottZ", "CheadjoeZ", "CheadkenZ", "Cheadjoe2Z",
    "CheadmishkinZ", "CheadsallyZ", "CheadmarionZ", "CheadmandyZ", "CheadvivienZ",
    "CheadbrosnanboilerZ", "CheadbrosnansuitZ", "CheadbrosnantimberZ",
    "CheadbrosnansnowZ", "CheadbrosnanZ", "CspicebondZ",
]


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
    point_usage: list[int] = field(default_factory=list)  # s16 per render vertex

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
    elif rec.op == 0x04:
        primary, secondary, base, verts, nv, mtype = struct.unpack_from(">IIIIHB", b, p)
        rec.record = {"primary_dl": _seg5(model, primary), "secondary_dl": _seg5(model, secondary),
                      "vertices": _seg5(model, verts), "num_vertices": nv,
                      "model_type": mtype, "base_addr": _seg5(model, base)}
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
    elif rec.op == 0x11:  # Op17Record
        hitpart, radius_sq, px, py, pz, other, s1, s2 = struct.unpack_from(">iffffIff", b, p)
        rec.record = {"hitpart": hitpart, "radius_sq": round(radius_sq, 3),
                      "pos": [round(px, 3), round(py, 3), round(pz, 3)],
                      "other_node": _seg5(model, other),
                      "scale1": round(s1, 3), "scale2": round(s2, 3)}
    elif rec.op == 0x12:  # SwitchRecord
        controls, rwidx, _ = struct.unpack_from(">IHH", b, p)
        rec.record = {"controls_node": _seg5(model, controls), "rw_data_index": rwidx}
    elif rec.op == 0x15:  # GroupSimpleRecord
        ox, oy, oz, g1, g2, radius = struct.unpack_from(">fffhHf", b, p)
        rec.record = {"origin": [round(ox, 3), round(oy, 3), round(oz, 3)],
                      "group1": g1, "group2": g2, "bounding_volume_radius": round(radius, 3)}
    elif rec.op == 0x17:  # HeadPlaceholderRecord
        rwidx = struct.unpack_from(">H", b, p)[0]
        rec.record = {"rw_data_index": rwidx}
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
        pu_off = rec.record["point_usage"]
        if pu_off is not None and 0 <= pu_off < len(model) and nv > 0:
            rec.point_usage = list(struct.unpack_from(f">{nv}h", model, pu_off))
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
        elif cmd == 0xC0:  # G_SETTEX: global texture id (12-bit, gbi_extension.h)
            tex_ids.append(w1 & 0xFFF)
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
        "num_matrices": hdr.num_matrices,
        "num_records": hdr.num_records,
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
             **({"point_usage": r.point_usage} if r.point_usage else {}),
             } for r in nodes],
        "opcode_nodes": {f"0x{k:02X}": len(v) for k, v in sorted(ops.items())},
    }


# ---------------------------------------------------------------- textures / points

# The global image table ``g_Textures`` (image.h ``image_entry``) lives in the
# rarezip DATA segment (image.c: ``struct image_entry g_Textures[]`` at US
# D:80049300).  It is NOT the "Globalimagetable" linker segment (that segment is
# the odd-texture image bank: ammo/crosshair/HUD sImageTableEntry tables + DLs).
#
# Each entry is 8 bytes.  ``*((s32*)&g_Textures[i]) & 0xFFFFFF`` is the 24-bit
# ``dataoffset``: in ROM it holds the PER-IMAGE byte SIZE (image i occupies
# [_imagesSegmentRomStart + offset[i], + offset[i] + size[i]) with offset[i] the
# cumulative sum of sizes[0..i-1]); ``image_entries_load`` (initimages.c)
# rewrites it in place to the cumulative offset at startup, stopping at a
# 0xffff terminator.  word0 = {u8 hitSound:4 | u8 hitTexture:4, u24 dataoffset},
# word1 = {u8 flag3:4, flag4:4, flag5:4, flag6:4, pad}.  Verified against the
# n64decomp/007 imagelist.u.csv: the 2698 sizes and cumulative offsets match the
# US ROM's absolute image offsets byte-for-byte (PAL images segment is the same
# bytes shifted by -0x5A8).
G_TEXTURES_DATA_OFF = 0x22C30   # PAL data-segment offset of g_Textures (VRAM 0x80040E80)
G_TEXTURES_VRAM = 0x80040E80
G_TEXTURES_ENTRY_SIZE = 8       # image_entry is 8 bytes, not 6
G_TEXTURES_TERMINATOR = 0xFFFF
G_TEXTURES_COUNT = 2698         # PAL g_Textures entries before the 0xffff terminator
# PAL _imagesSegmentRomStart.  reader(4)/(5) had 0x8F7848 (off by 8): that value
# was derived from "0xFF tail (0xBE6760) - sum(sizes)", but the PAL table stops
# at 2698 entries (the 8-byte image2698 that the US imagelist.u.csv carries is
# the 0xffff terminator here), so the true start is 8 bytes earlier.  Verified
# by decoding all 14 CsuitbondZ textures: at 0x8F7840 they decode to EXACTLY
# the model-record dimensions (32x48/48x32/32x32/1x1) as zlib-paletted
# RGBA16_CI8/CI4/IA16_CI8; at 0x8F7848 every header overran its payload.
IMAGES_ROM_START = 0x8F7840

# G_IM_FMT / G_IM_SIZ for the model's 12-byte sImageTableEntry (bondtypes.h
# ModelFileTextures: Type = format, RenderDepth = size).
FMT_RGBA, FMT_YUV, FMT_CI, FMT_IA, FMT_I = 0, 1, 2, 3, 4
SIZ_4B, SIZ_8B, SIZ_16B, SIZ_32B = 0, 1, 2, 3


def image_entries_accumulate(sizes: list[int]) -> list[int]:
    """Replicate ``image_entries_load`` (initimages.c): per-image sizes -> cumulative
    offsets, appending the total as the trailing terminator entry."""
    offsets, total = [], 0
    for s in sizes:
        offsets.append(total)
        total += s
    offsets.append(total)
    return offsets


def group_matrix_map(nodes: list[NodeRec]) -> dict[int, int]:
    """Map model matrix slot -> owning joint id.

    Each op-0x02 GroupRecord carries MatrixID0/1/2 (the reader's
    ``matrix_ids``); ``process_02_position`` (model.c) builds render_pos[slot]
    from the group's origin/rotation, so slot ``m`` is the transform matrix
    owned by the group with MatrixID0/1/2 == m.  Returns {matrix_slot:
    joint_id}; slots are 0..num_matrices-1.
    """
    owner: dict[int, int] = {}
    for r in nodes:
        if r.op != 0x02:
            continue
        jid = r.record.get("joint_id")
        if jid is None:
            continue
        for m in r.record.get("matrix_ids", []):
            if isinstance(m, int) and m >= 0:
                owner.setdefault(m, jid)
    return owner


def _c16(v: int) -> int:
    """5-bit channel -> 8-bit."""
    return (v << 3) | (v >> 2)


def decode_image(pixels: bytes, width: int, height: int, fmt: int,
                 siz: int, palette: bytes | None = None) -> bytes | None:
    """Decode an N64 texture to RGBA8888 (row-major width*height*4 bytes).

    ``fmt``/``siz`` are the model texture record's Type/RenderDepth fields
    (G_IM_FMT / G_IM_SIZ).  CI textures require a 16-bit RGBA ``palette``.
    Returns None for unsupported combinations.
    """
    n = width * height
    out = bytearray(n * 4)
    if fmt == FMT_RGBA and siz == SIZ_16B:
        if len(pixels) < n * 2:
            return None
        for i in range(n):
            w = (pixels[i * 2] << 8) | pixels[i * 2 + 1]
            out[i * 4] = _c16((w >> 11) & 0x1F)
            out[i * 4 + 1] = _c16((w >> 6) & 0x1F)
            out[i * 4 + 2] = _c16((w >> 1) & 0x1F)
            out[i * 4 + 3] = 255 if (w & 1) else 0
        return bytes(out)
    if fmt == FMT_RGBA and siz == SIZ_32B:
        if len(pixels) < n * 4:
            return None
        for i in range(n):
            out[i * 4:i * 4 + 4] = pixels[i * 4:i * 4 + 4]
        return bytes(out)
    if fmt == FMT_I and siz == SIZ_8B:
        if len(pixels) < n:
            return None
        for i in range(n):
            v = pixels[i]
            out[i * 4:i * 4 + 4] = (v, v, v, 255)
        return bytes(out)
    if fmt == FMT_I and siz == SIZ_4B:
        if len(pixels) < (n + 1) // 2:
            return None
        for i in range(n):
            v = (pixels[i // 2] >> (4 if i % 2 == 0 else 0)) & 0xF
            v = (v << 4) | v
            out[i * 4:i * 4 + 4] = (v, v, v, 255)
        return bytes(out)
    if fmt == FMT_IA and siz == SIZ_16B:
        if len(pixels) < n * 2:
            return None
        for i in range(n):
            ia = (pixels[i * 2] << 8) | pixels[i * 2 + 1]
            v = ia >> 8
            out[i * 4:i * 4 + 4] = (v, v, v, ia & 0xFF)
        return bytes(out)
    if fmt == FMT_IA and siz == SIZ_8B:
        if len(pixels) < n:
            return None
        for i in range(n):
            b = pixels[i]
            i4 = (b >> 4) & 0xF
            v = (i4 << 4) | i4
            a = ((b & 0xF) << 4) | (b & 0xF)
            out[i * 4:i * 4 + 4] = (v, v, v, a)
        return bytes(out)
    if fmt == FMT_CI and palette:
        step = 1 if siz == SIZ_8B else 2  # CI8 / CI4
        shift = 4 if siz == SIZ_4B else 0
        for i in range(n):
            if siz == SIZ_8B:
                c = pixels[i]
            else:
                c = (pixels[i // 2] >> (shift if i % 2 == 0 else 0)) & 0xF
            if c * 2 + 2 <= len(palette):
                w = (palette[c * 2] << 8) | palette[c * 2 + 1]
                out[i * 4] = _c16((w >> 11) & 0x1F)
                out[i * 4 + 1] = _c16((w >> 6) & 0x1F)
                out[i * 4 + 2] = _c16((w >> 1) & 0x1F)
                out[i * 4 + 3] = 255 if (w & 1) else 0
        return bytes(out)
    return None


def g_textures(ge: GoldenEyeROM) -> list[int]:
    """Read the pinned g_Textures size table from the data segment.

    Returns the per-image byte sizes (2698 entries); the table ends at a
    0xffff dataoffset terminator (not included).
    """
    sizes: list[int] = []
    p = G_TEXTURES_DATA_OFF
    while True:
        w0 = (ge.data[p] << 24) | (ge.data[p + 1] << 16) | (ge.data[p + 2] << 8) | ge.data[p + 3]
        d = w0 & 0xFFFFFF
        if d == G_TEXTURES_TERMINATOR:
            break
        if not 1 <= d < G_TEXTURES_TERMINATOR:
            raise GoldenEyeFormatError(f"implausible image size 0x{d:X} at data offset 0x{p:X}")
        sizes.append(d)
        p += G_TEXTURES_ENTRY_SIZE
    return sizes


def image_offsets(sizes: list[int]) -> list[int]:
    """Cumulative image offsets (the runtime dataoffset) plus the trailing total."""
    return image_entries_accumulate(sizes)


def image_rom_span(sizes: list[int], index: int) -> tuple[int, int]:
    """(rom_offset, size) of image ``index`` in the images segment."""
    off = image_offsets(sizes)
    return IMAGES_ROM_START + off[index], sizes[index]


# G_IM_FMT_* style TEXFORMAT (image.h) -> decode metadata, cross-checked against
# g_TexFormat* in image.c.
TEXFORMAT_NAMES = ["RGBA32", "RGBA16", "RGB24", "RGB15", "IA16", "IA8", "IA4",
                   "I8", "I4", "RGBA16_CI8", "RGBA16_CI4", "IA16_CI8", "IA16_CI4"]
# bits per pixel (image.c g_TexFormatBitsPerPixel)
TEXFORMAT_BPP = [32, 16, 24, 15, 16, 8, 4, 8, 4, 16, 16, 16, 16]
# N64 G_IM_FMT (image.c g_TexFormatGbiMappings)
TEXFORMAT_GBI = [0, 0, 0, 0, 3, 3, 3, 4, 4, 2, 2, 2, 2]
# N64 G_IM_SIZ (image.c g_TexFormatDepths)
TEXFORMAT_DEPTH = [3, 2, 3, 2, 2, 1, 0, 1, 0, 1, 0, 1, 0]
# compression methods (image.h TEXCOMPMETHOD_*)
COMPMETHOD_NAMES = ["UNCOMPRESSED0", "UNCOMPRESSED1", "HUFFMAN", "HUFFMANPERHCHANNEL",
                    "RLE", "LOOKUP", "HUFFMANLOOKUP", "RLELOOKUP", "HUFFMANBLUR", "RLEBLUR"]


class TexBitReader:
    """Replicates ``texReadBits`` (image_bank.c): MSB-first bit stream.

    The first byte read is the most significant; ``read(k)`` returns the next
    ``k`` bits as an unsigned int.
    """

    def __init__(self, buf: bytes):
        self.buf = buf
        self.pos = 0
        self.acc = 0
        self.nbits = 0

    def read(self, k: int) -> int:
        while self.nbits < k:
            self.acc = (self.buf[self.pos] | (self.acc << 8)) & 0xFFFFFFFF
            self.pos += 1
            self.nbits += 8
        self.nbits -= k
        return (self.acc >> self.nbits) & ((1 << k) - 1)


def image_payload_header(rom: bytes, off: int) -> tuple[bool, bool, int]:
    """Parse the 1-byte image header (texLoad): (has_explicit_lods, is_zlib, lod)."""
    hdr = rom[off]
    return (bool(hdr & 0x80), bool(hdr & 0x40), hdr & 0x3F)


def tex_read_uncompressed(br: TexBitReader, width: int, height: int,
                          fmt: int) -> bytes:
    """Replicate ``texReadUncompressed`` (image.c) -> RGBA8888, tight rows."""
    n = width * height
    out = bytearray(n * 4)
    if fmt == 0:  # RGBA32
        for i in range(n):
            w = (br.read(16) << 16) | br.read(16)
            out[i * 4:i * 4 + 4] = (w >> 24) & 0xFF, (w >> 16) & 0xFF, (w >> 8) & 0xFF, w & 0xFF
    elif fmt == 1:  # RGBA16 (5/5/5/1)
        for i in range(n):
            w = br.read(16)
            out[i * 4] = _c16((w >> 11) & 0x1F)
            out[i * 4 + 1] = _c16((w >> 6) & 0x1F)
            out[i * 4 + 2] = _c16((w >> 1) & 0x1F)
            out[i * 4 + 3] = 255 if (w & 1) else 0
    elif fmt == 2:  # RGB24
        for i in range(n):
            w = br.read(24)
            out[i * 4:i * 4 + 4] = (w >> 16) & 0xFF, (w >> 8) & 0xFF, w & 0xFF, 0xFF
    elif fmt == 3:  # RGB15 (5/5/5)
        for i in range(n):
            w = br.read(15)
            out[i * 4] = _c16((w >> 10) & 0x1F)
            out[i * 4 + 1] = _c16((w >> 5) & 0x1F)
            out[i * 4 + 2] = _c16(w & 0x1F)
            out[i * 4 + 3] = 0xFF
    elif fmt == 4:  # IA16 (8-bit intensity + 8-bit alpha)
        for i in range(n):
            ia = br.read(16)
            v = ia >> 8
            out[i * 4:i * 4 + 4] = v, v, v, ia & 0xFF
    elif fmt in (5, 7):  # IA8 / I8
        for i in range(n):
            v = br.read(8)
            out[i * 4:i * 4 + 4] = v, v, v, (v if fmt == 7 else 0xFF)
    elif fmt in (6, 8):  # IA4 / I4 (nibble per pixel, high nibble first)
        for i in range(n):
            v = br.read(4)
            v = (v << 4) | v
            out[i * 4:i * 4 + 4] = v, v, v, (v if fmt == 8 else 0xFF)
    else:
        return b""  # paletted (CI) needs a palette -- handled elsewhere
    return bytes(out)


def texture_bitstream_header(rom: bytes, off: int, size: int) -> dict:
    """Decode the texInflateNonZlib header of image at ``off`` (header byte + bitstream).

    Returns format/width/height/compmethod and the per-image decode path.  Only
    the first (top) mip level is read when has_explicit_lods is unset.
    """
    explicit, is_zlib, lod = image_payload_header(rom, off)
    payload = rom[off + 1:off + size]
    br = TexBitReader(payload)
    try:
        fmt = br.read(4)
        width = br.read(8)
        height = br.read(8)
        comp = br.read(4)
    except IndexError:
        return {"error": "payload too short for bitstream header"}
    return {"has_explicit_lods": explicit, "is_zlib": is_zlib, "lod": lod,
            "format": fmt, "format_name": TEXFORMAT_NAMES[fmt] if fmt < len(TEXFORMAT_NAMES) else fmt,
            "width": width, "height": height, "compmethod": comp,
            "compmethod_name": COMPMETHOD_NAMES[comp] if comp < len(COMPMETHOD_NAMES) else comp}


def decode_model_texture(ge: GoldenEyeROM, texture_id: int) -> dict:
    """Decode one global texture (g_Textures index) to its header + RGBA8888 pixels.

    All texInflate codecs (Huffman/RLE/LOOKUP/Blur and the zlib paletted path)
    are implemented via :func:`inflate_image_pixels`.  ``pixels`` is None when the
    payload is too short for the bitstream header's dimensions (see the KNOWN
    ISSUE note above) or the codec is unknown -- never a silent partial decode.
    """
    sizes = g_textures(ge)
    if not 0 <= texture_id < len(sizes):
        raise KeyError(texture_id)
    off, size = image_rom_span(sizes, texture_id)
    explicit, is_zlib, lod = image_payload_header(ge.rom, off)
    result = inflate_image_pixels(ge.rom, off, size, is_zlib)
    base = {"texture_id": texture_id, "rom_offset": off, "size": size,
            "has_explicit_lods": explicit, "is_zlib": is_zlib, "lod": lod}
    if result is None:
        base["pixels"] = None
        base["note"] = ("bitstream header overruns the recorded payload, or the "
                        "codec is unknown (KNOWN ISSUE: image header vs byte size)")
        return base
    rgba, width, height, fmt = result
    base.update({"pixels": rgba, "pixel_bytes": len(rgba),
                 "width": width, "height": height, "format": fmt})
    return base


# ------------------------------------------------------------ texInflate codecs
# Faithful ports of n64decomp/007 src/game/image.c (texInflate{NonZlib,Zlib})
# and tools/mktex/src/libpdtex/reader.c (the reference decoder).  Each function
# mirrors the C bit-for-bit, including the u32 accumulator wrap of texReadBits
# and C-style truncating integer division in texBlur.
#
# RESOLVED (reader(6)): the "KNOWN ISSUE" from reader(4)/(5) -- bitstream
# dimensions overrunning the per-image byte size -- was NOT a header-layout
# question.  The images-segment base was 8 bytes too high (0x8F7848 instead of
# 0x8F7840).  At the corrected base every header decodes cleanly: COPYICON is
# 32x28 RGBA32 RLELOOKUP, DELICON 32x28 HUFFMANBLUR, and the 14 CsuitbondZ
# textures are all zlib-paletted (RGBA16_CI8/CI4, IA16_CI8) matching their
# model-record widths/heights exactly.  Confirmed byte-for-byte against the
# reference C decoder (mktex reader.c), which produced the same overruns at the
# old base -- i.e. the codecs below were always correct.

TEXFORMAT_NUM_CHANNELS = [4, 3, 3, 3, 2, 2, 1, 1, 1, 1, 1, 1, 1]
TEXFORMAT_HAS_1BIT_ALPHA = [0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0]
TEXFORMAT_CHANNEL_SIZES = [0x100, 0x20, 0x100, 0x20, 0x100, 0x10, 8,
                           0x100, 0x10, 0x100, 0x10, 0x100, 0x10]
# 0=RGBA16 palette, 1=IA16 palette (g_TexFormatLutModes >> G_MDSFT_TEXTLUT)
TEXFORMAT_LUT = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1]


def _cdiv(a: int, b: int) -> int:
    """C-style integer division (truncation toward zero, unlike Python //)."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def tex_get_bit_size(decimal: int) -> int:
    """Number of bits needed to index ``decimal`` distinct values (texGetBitSize)."""
    count = 0
    decimal -= 1
    while decimal > 0:
        decimal >>= 1
        count += 1
    return count


def tex_inflate_huffman(br: TexBitReader, numiterations: int, chansize: int) -> list[int]:
    """Replicate texInflateHuffman: decode ``numiterations`` channel samples."""
    frequencies = [br.read(8) for _ in range(chansize)]
    nodes = [[-1, -1] for _ in range(2048)]
    minfreq1 = minfreq2 = 9999
    minindex1 = minindex2 = 0
    for i in range(chansize):
        if frequencies[i] < minfreq1:
            if minfreq2 < minfreq1:
                minfreq1, minindex1 = frequencies[i], i
            else:
                minfreq2, minindex2 = frequencies[i], i
        elif frequencies[i] < minfreq2:
            minfreq2, minindex2 = frequencies[i], i
    done = False
    rootindex = 0
    while not done:
        s = frequencies[minindex1] + frequencies[minindex2]
        if s == 0:
            s = 1
        frequencies[minindex1] = 9999
        frequencies[minindex2] = 9999
        if nodes[minindex1][0] < 0 and nodes[minindex1][1] < 0:
            nodes[minindex1][0] = minindex1 + 10000
            rootindex = minindex1
            frequencies[minindex1] = s
            if nodes[minindex2][0] < 0 and nodes[minindex2][1] < 0:
                nodes[minindex1][1] = minindex2 + 10000
            else:
                nodes[minindex1][1] = minindex2
        elif nodes[minindex2][0] < 0 and nodes[minindex2][1] < 0:
            nodes[minindex2][0] = minindex2 + 10000
            rootindex = minindex2
            frequencies[minindex2] = s
            if nodes[minindex1][0] < 0 and nodes[minindex1][1] < 0:
                nodes[minindex2][1] = minindex1 + 10000
            else:
                nodes[minindex2][1] = minindex1
        else:
            rootindex = 0
            while nodes[rootindex][0] >= 0 or nodes[rootindex][1] >= 0 or frequencies[rootindex] < 9999:
                rootindex += 1
            frequencies[rootindex] = s
            nodes[rootindex][0] = minindex1
            nodes[rootindex][1] = minindex2
        minfreq1 = minfreq2 = 9999
        for i in range(chansize):
            if frequencies[i] < minfreq1:
                if minfreq1 > minfreq2:
                    minfreq1, minindex1 = frequencies[i], i
                else:
                    minfreq2, minindex2 = frequencies[i], i
            elif frequencies[i] < minfreq2:
                minfreq2, minindex2 = frequencies[i], i
        if minfreq1 == 9999 or minfreq2 == 9999:
            done = True
    out = []
    for _ in range(numiterations):
        iv = rootindex
        while iv < 10000:
            iv = nodes[iv][br.read(1)]
        out.append(iv - 10000)
    return out


def tex_inflate_rle(br: TexBitReader, blockstotal: int) -> list[int]:
    """Replicate texInflateRle: decode ``blockstotal`` channel samples."""
    btfieldsize = br.read(3)
    rlfieldsize = br.read(3)
    blocksize = br.read(4)
    cost = btfieldsize + rlfieldsize + blocksize + 1
    fudge = 0
    while cost > 0:
        cost -= blocksize + 1
        fudge += 1
    blocks: list[int] = []
    blocksdone = 0
    while blocksdone < blockstotal:
        if br.read(1) == 0:
            blocks.append(br.read(blocksize))
            blocksdone += 1
        else:
            start = blocksdone - br.read(btfieldsize) - 1
            run = br.read(rlfieldsize) + fudge
            for i in range(start, start + run):
                blocks.append(blocks[i])
                blocksdone += 1
            blocks.append(br.read(blocksize))
            blocksdone += 1
    return blocks


def tex_build_lookup(br: TexBitReader, bitsperpixel: int) -> tuple[int, list[int]]:
    """Replicate texBuildLookup: read an 11-bit count then that many colours."""
    numcolors = br.read(11)
    lookup: list[int] = []
    if bitsperpixel <= 16:
        for _ in range(numcolors):
            lookup.append(br.read(bitsperpixel))
    elif bitsperpixel <= 24:
        for _ in range(numcolors):
            lookup.append(br.read(bitsperpixel))
    else:
        for _ in range(numcolors):
            lookup.append((br.read(24) << 8) | br.read(bitsperpixel - 24))
    return numcolors, lookup


def tex_blur(pixels: list[int], width: int, height: int, method: int, chansize: int) -> None:
    """Replicate texBlur in place over a flat channel array (width x height)."""
    for y in range(height):
        for x in range(width):
            cur = pixels[y * width + x] + chansize * 2
            left = pixels[y * width + x - 1] if x > 0 else 0
            above = pixels[(y - 1) * width + x] if y > 0 else 0
            aboveleft = pixels[(y - 1) * width + x - 1] if x > 0 and y > 0 else 0
            if method == 0:
                pixels[y * width + x] = (cur + left) % chansize
            elif method == 1:
                pixels[y * width + x] = (cur + above) % chansize
            elif method == 2:
                pixels[y * width + x] = (cur + aboveleft) % chansize
            elif method == 3:
                pixels[y * width + x] = (cur + (left + above - aboveleft)) % chansize
            elif method == 4:
                pixels[y * width + x] = (cur + (_cdiv(above - aboveleft, 2) + left)) % chansize
            elif method == 5:
                pixels[y * width + x] = (cur + (_cdiv(left - aboveleft, 2) + above)) % chansize
            elif method == 6:
                pixels[y * width + x] = (cur + ((left + above) // 2)) % chansize


def _packed_pixel_rgba8888(format: int, value: int) -> tuple[int, int, int, int]:
    """Decode one packed TEXFORMAT pixel value to 8-bit RGBA."""
    if format == 0:  # RGBA32
        return ((value >> 24) & 0xFF, (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)
    if format == 2:  # RGB24 (alpha forced 0xff)
        return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF, 0xFF)
    if format == 1:  # RGBA16 5551
        return (_c16((value >> 11) & 0x1F), _c16((value >> 6) & 0x1F), _c16((value >> 1) & 0x1F), 255 if value & 1 else 0)
    if format == 3:  # RGB15 555
        return (_c16((value >> 10) & 0x1F), _c16((value >> 5) & 0x1F), _c16(value & 0x1F), 0xFF)
    if format == 4:  # IA16
        v = (value >> 8) & 0xFF
        return (v, v, v, value & 0xFF)
    if format == 5:  # IA8 (4/4)
        i = (value >> 4) & 0xF
        a = value & 0xF
        return ((i << 4) | i, (i << 4) | i, (i << 4) | i, (a << 4) | a)
    if format == 7:  # I8
        v = value & 0xFF
        return (v, v, v, 0xFF)
    if format == 8:  # I4
        v = value & 0xF
        v8 = (v << 4) | v
        return (v8, v8, v8, 0xFF)
    if format == 6:  # IA4 (3/1)
        i = (value >> 1) & 0x7
        a = value & 1
        i8 = (i << 5) | (i << 2) | (i >> 1)
        return (i8, i8, i8, 255 if a else 0)
    return (0, 0, 0, 0)


def tex_channels_to_pixels(scratch: list[int], width: int, height: int, format: int) -> bytes:
    """Replicate texChannelsToPixels, emitting RGBA8888 (row-major, no pad)."""
    mult = width * height
    out = bytearray(mult * 4)
    pos = 0
    for y in range(height):
        for x in range(width):
            i = y * width + x
            if format == 0:  # RGBA32
                rgba = (scratch[i], scratch[i + mult], scratch[i + 2 * mult], scratch[i + 3 * mult])
            elif format == 2:  # RGB24
                rgba = (scratch[i], scratch[i + mult], scratch[i + 2 * mult], 0xFF)
            elif format == 1:  # RGBA16
                rgba = (_c16(scratch[i]), _c16(scratch[i + mult]), _c16(scratch[i + 2 * mult]), 255 if scratch[i + 3 * mult] else 0)
            elif format == 3:  # RGB15
                rgba = (_c16(scratch[i]), _c16(scratch[i + mult]), _c16(scratch[i + 2 * mult]), 0xFF)
            elif format == 4:  # IA16
                v = scratch[i]
                rgba = (v, v, v, scratch[i + mult])
            elif format == 5:  # IA8
                i4 = scratch[i]
                a4 = scratch[i + mult]
                rgba = ((i4 << 4) | i4, (i4 << 4) | i4, (i4 << 4) | i4, (a4 << 4) | a4)
            elif format == 7:  # I8
                v = scratch[i]
                rgba = (v, v, v, 0xFF)
            elif format == 6:  # IA4 (intensity ch0, 1-bit alpha ch3)
                i3 = scratch[i]
                a1 = scratch[i + 3 * mult]
                i8 = (i3 << 5) | (i3 << 2) | (i3 >> 1)
                rgba = (i8, i8, i8, 255 if a1 else 0)
            elif format == 8:  # I4
                v = scratch[i]
                v8 = (v << 4) | v
                rgba = (v8, v8, v8, 0xFF)
            else:
                rgba = (0, 0, 0, 0)
            out[pos:pos + 4] = bytes(rgba)
            pos += 4
    return bytes(out)


def tex_inflate_lookup(br: TexBitReader, lookup: list[int], numcolours: int,
                       width: int, height: int, format: int) -> bytes:
    """Replicate texInflateLookup: index the lookup table per pixel -> RGBA8888."""
    bitspercolour = tex_get_bit_size(numcolours)
    out = bytearray(width * height * 4)
    pos = 0
    for _ in range(height):
        for _ in range(width):
            idx = br.read(bitspercolour)
            out[pos:pos + 4] = bytes(_packed_pixel_rgba8888(format, lookup[idx]))
            pos += 4
    return bytes(out)


def tex_inflate_lookup_from_buffer(src: list[int], lookup: list[int], numcolours: int,
                                   width: int, height: int, format: int) -> bytes:
    """Replicate texInflateLookupFromBuffer: indices come from ``src``, not the bitstream."""
    out = bytearray(width * height * 4)
    pos = 0
    for y in range(height):
        for x in range(width):
            idx = src[y * width + x]
            out[pos:pos + 4] = bytes(_packed_pixel_rgba8888(format, lookup[idx]))
            pos += 4
    return bytes(out)


def inflate_image_pixels(rom: bytes, off: int, size: int, is_zlib: bool) -> tuple[bytes, int, int, int] | None:
    """Decode one global image (at ``off``, ``size`` bytes) to (rgba8888, w, h, fmt).

    Returns None when the payload is too short for the header's dimensions or the
    compression method is unknown (see the KNOWN ISSUE note above: many images'
    bitstream headers overrun their recorded byte size, which this returns None
    for rather than silently emitting a partial decode).
    """
    payload = rom[off + 1:off + size]
    br = TexBitReader(payload)
    if is_zlib:
        fmt = br.read(8)
        numcolours = br.read(8) + 1
        palette = [br.read(16) for _ in range(numcolours)]
        width = br.read(8)
        height = br.read(8)
        if width * height >= 4097 or not (9 <= fmt <= 12):
            return None
        data = payload[br.pos:]
        if data[:2] == b"\x11\x72":
            data = data[2:]
        try:
            indices = zlib.decompress(data, -15)
        except zlib.error:
            return None
        mult = width * height
        out = bytearray(mult * 4)
        ci8 = fmt in (9, 11)
        for i in range(mult):
            c = indices[i] if ci8 else (indices[i // 2] >> (4 if i % 2 == 0 else 0)) & 0xF
            if c < numcolours:
                pv = palette[c]
                if fmt in (9, 10):  # RGBA16 palette (5551)
                    rgba = (_c16((pv >> 11) & 0x1F), _c16((pv >> 6) & 0x1F), _c16((pv >> 1) & 0x1F), 255 if pv & 1 else 0)
                else:  # IA16 palette
                    v = (pv >> 8) & 0xFF
                    rgba = (v, v, v, pv & 0xFF)
                out[i * 4:i * 4 + 4] = bytes(rgba)
        return bytes(out), width, height, fmt

    fmt = br.read(4)
    width = br.read(8)
    height = br.read(8)
    comp = br.read(4)
    if width * height > 0x2000 or comp > 9:
        return None
    mult = width * height
    scratch = [0] * (4 * mult)
    try:
        if comp in (0, 1):  # UNCOMPRESSED0/1
            bpp = TEXFORMAT_BPP[fmt] if fmt < len(TEXFORMAT_BPP) else 0
            if bpp == 0 or (24 + mult * bpp) > (size - 1) * 8:
                return None
            rgba = tex_read_uncompressed(br, width, height, fmt)
            return rgba, width, height, fmt
        if comp == 2:  # HUFFMAN
            samples = tex_inflate_huffman(br, TEXFORMAT_NUM_CHANNELS[fmt] * mult, TEXFORMAT_CHANNEL_SIZES[fmt])
            scratch[:len(samples)] = samples
            if TEXFORMAT_HAS_1BIT_ALPHA[fmt]:
                for i in range(mult):
                    scratch[3 * mult + i] = br.read(1)
        elif comp == 3:  # HUFFMANPERHCHANNEL
            for j in range(TEXFORMAT_NUM_CHANNELS[fmt]):
                scratch[j * mult:(j + 1) * mult] = tex_inflate_huffman(br, mult, TEXFORMAT_CHANNEL_SIZES[fmt])
            if TEXFORMAT_HAS_1BIT_ALPHA[fmt]:
                for i in range(mult):
                    scratch[3 * mult + i] = br.read(1)
        elif comp == 4:  # RLE
            samples = tex_inflate_rle(br, TEXFORMAT_NUM_CHANNELS[fmt] * mult)
            scratch[:len(samples)] = samples
            if TEXFORMAT_HAS_1BIT_ALPHA[fmt]:
                for i in range(mult):
                    scratch[3 * mult + i] = br.read(1)
        elif comp == 5:  # LOOKUP
            ncolours, lookup = tex_build_lookup(br, TEXFORMAT_BPP[fmt])
            return tex_inflate_lookup(br, lookup, ncolours, width, height, fmt), width, height, fmt
        elif comp == 6:  # HUFFMANLOOKUP
            ncolours, lookup = tex_build_lookup(br, TEXFORMAT_BPP[fmt])
            samples = tex_inflate_huffman(br, mult, ncolours)
            return tex_inflate_lookup_from_buffer(samples, lookup, ncolours, width, height, fmt), width, height, fmt
        elif comp == 7:  # RLELOOKUP
            ncolours, lookup = tex_build_lookup(br, TEXFORMAT_BPP[fmt])
            samples = tex_inflate_rle(br, mult)
            return tex_inflate_lookup_from_buffer(samples, lookup, ncolours, width, height, fmt), width, height, fmt
        elif comp == 8:  # HUFFMANBLUR
            stack = br.read(3)
            samples = tex_inflate_huffman(br, TEXFORMAT_NUM_CHANNELS[fmt] * mult, TEXFORMAT_CHANNEL_SIZES[fmt])
            scratch[:len(samples)] = samples
            tex_blur(scratch, width, TEXFORMAT_NUM_CHANNELS[fmt] * height, stack, TEXFORMAT_CHANNEL_SIZES[fmt])
            if TEXFORMAT_HAS_1BIT_ALPHA[fmt]:
                for i in range(mult):
                    scratch[3 * mult + i] = br.read(1)
        elif comp == 9:  # RLEBLUR
            stack = br.read(3)
            samples = tex_inflate_rle(br, TEXFORMAT_NUM_CHANNELS[fmt] * mult)
            scratch[:len(samples)] = samples
            tex_blur(scratch, width, TEXFORMAT_NUM_CHANNELS[fmt] * height, stack, TEXFORMAT_CHANNEL_SIZES[fmt])
            if TEXFORMAT_HAS_1BIT_ALPHA[fmt]:
                for i in range(mult):
                    scratch[3 * mult + i] = br.read(1)
    except IndexError:
        # bitstream ran out mid-decode (see KNOWN ISSUE: header vs byte size)
        return None
    return tex_channels_to_pixels(scratch, width, height, fmt), width, height, fmt





def _slug(s: str) -> str:
    out = []
    for ch in s:
        out.append(ch if ch.isalnum() else "_")
    return "".join(out).strip("_").lower()


def _pretty(name: str) -> str:
    """'CheadbrosnansuitZ' -> 'Head Brosnan Suit'."""
    stem = name
    if stem.startswith("C"):
        stem = stem[1:]
    if stem.endswith("Z"):
        stem = stem[:-1]
    stem = stem.replace("_", " ")
    words, cur = [], ""
    for ch in stem:
        if ch.isupper() and cur and not cur[-1].isupper():
            words.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        words.append(cur)
    return " ".join(w[:1].upper() + w[1:] for w in words if w).strip() or name


def roster() -> list[dict]:
    """The 80 PAL body/head files as characters.DEDICATED roster rows."""
    return [{"key": n, "slug": f"ge_{_slug(n)}", "name": _pretty(n),
             "aliases": [f"GoldenEye {_pretty(n)}", n], "kind": "character"}
            for n in ROSTER_NAMES]


def build_skeleton(nodes: list[NodeRec]) -> tuple[list[dict], dict[int, int]]:
    """Joint list {joint_id, origin, parent} (0..N-1) and {node_offset -> joint_id}.

    Joint 0 is the implicit root (no GroupRecord); the op-0x02 GroupRecords
    carry JointID 1..numjoints-1.  A group's skeleton parent is the nearest
    group ancestor in the node tree (or 0 for the root group)."""
    by_offset = {r.offset: r for r in nodes}
    pos_nodes = [r for r in nodes if r.op == 0x02]

    def parent_group(r: NodeRec) -> NodeRec | None:
        seen = set()
        p = r.parent
        while p and p not in seen:
            seen.add(p)
            pr = by_offset.get(p)
            if pr is None:
                break
            if pr.op == 0x02:
                return pr
            p = pr.parent
        return None

    joints: list[dict] = [{"joint_id": 0, "origin": [0.0, 0.0, 0.0], "parent": -1}]
    for r in pos_nodes:
        par = parent_group(r)
        joints.append({"joint_id": r.record["joint_id"], "origin": r.record["origin"],
                       "parent": par.record["joint_id"] if par else 0})
    joints.sort(key=lambda j: j["joint_id"])
    # parent must index an existing joint id (0..len-1)
    ids = {j["joint_id"] for j in joints}
    for j in joints:
        if j["parent"] < 0:            # the implicit root has no parent
            continue
        if j["parent"] not in ids:
            j["parent"] = 0
    node_joint = {}
    for r in nodes:
        jid = 0
        p = r
        seen = set()
        while p.offset not in seen:
            seen.add(p.offset)
            if p.op == 0x02:
                jid = p.record["joint_id"]
                break
            if not p.parent or p.parent not in by_offset:
                break
            p = by_offset[p.parent]
        node_joint[r.offset] = jid
    return joints, node_joint


def joint_world_positions(joints: list[dict]) -> list[list[float]]:
    """Accumulated world-space position of each joint (translation-only bind)."""
    world: list[list[float] | None] = [None] * len(joints)
    idx = {j["joint_id"]: i for i, j in enumerate(joints)}

    def acc(i: int) -> list[float]:
        if world[i] is not None:
            return world[i]
        j = joints[i]
        if j["parent"] < 0:
            world[i] = list(j["origin"])
        else:
            o = j["origin"]
            w = acc(idx[j["parent"]])
            world[i] = [w[0] + o[0], w[1] + o[1], w[2] + o[2]]
        return world[i]

    for i in range(len(joints)):
        acc(i)
    return world  # type: ignore[return-value]


def _inverse_bind_matrices(world: list[list[float]]) -> bytes:
    """glTF column-major MAT4 inverse bind matrices (translation-only rig)."""
    mats = []
    for x, y, z in world:
        mats += [1.0, 0.0, 0.0, 0.0,
                 0.0, 1.0, 0.0, 0.0,
                 0.0, 0.0, 1.0, 0.0,
                 -x, -y, -z, 1.0]
    return struct.pack(">" + "f" * len(mats), *mats)


def _rgba_to_png(rgba: bytes, width: int, height: int) -> bytes:
    """Encode row-major RGBA8888 to a minimal 8-bit RGBA PNG (no external deps)."""
    def _chunk(typ: bytes, data: bytes) -> bytes:
        c = typ + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + rgba[y * width * 4:(y + 1) * width * 4] for y in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b""))


def to_gltf(ge: GoldenEyeROM, filename: str, out_path: str | Path) -> dict:
    """Export a decoded character as a self-contained, rigged .gltf scene.

    The 16-joint skeleton (implicit root 0 + the 15 op-0x02 GroupRecords)
    becomes a glTF ``skins`` array with translation-only inverse bind
    matrices; every op-0x18 render mesh is rigidly bound to its nearest
    ancestor group's joint with unit weights.  Vertices keep their native
    model-space coordinates, vertex colours and UVs, and the real triangles
    decoded from the F3D_OLD primary DL.  Texture pixels are not decoded yet;
    per-node texture ids are recorded in mesh extras and the model's texture
    records in the scene extras.
    """
    doc = read_character(ge, filename)
    nodes = parse_nodes(ge.read_file(filename), doc["root_offset"])
    joints, node_joint = build_skeleton(nodes)
    world = joint_world_positions(joints)

    gltf = {"asset": {"version": "2.0", "generator": "gbox.goldeneye_reader"},
            "scenes": [{"nodes": []}], "scene": 0,
            "nodes": [], "meshes": [], "skins": [], "accessors": [], "bufferViews": [],
            "buffers": [{"byteLength": 0}],
            "images": [], "textures": [], "samplers": [], "materials": [],
            "extras": {"textures": doc["textures"]}}
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

    # skeleton joints (sorted by joint_id 0..N-1) as glTF nodes
    gltf["nodes"] = [{"name": f"joint{j['joint_id']}", "translation": j["origin"]}
                     for j in joints]
    for i, j in enumerate(joints):
        kids = [k for k, o in enumerate(joints) if o["parent"] == j["joint_id"]]
        if kids:
            gltf["nodes"][i]["children"] = kids
    gltf["skins"].append({"joints": list(range(len(joints))),
                          "inverseBindMatrices": add_accessor(
                              _inverse_bind_matrices(world), 5126, len(joints), "MAT4")})

    # Decode the model's textures and embed them as PNG images + glTF
    # textures/samplers.  Each render mesh is bound to its first texture id
    # through a material (baseColorTexture) so TEXCOORD_0 resolves in viewers.
    gltf["samplers"].append({"magFilter": 9729, "minFilter": 9987,
                             "wrapS": 33071, "wrapT": 33071})
    tex_by_index: dict[int, int] = {}
    for t in doc["textures"]:
        dec = decode_model_texture(ge, t["index"])
        png = dec.get("pixels")
        if not png:
            continue
        gltf["images"].append({"uri": "data:image/png;base64," +
                               base64.b64encode(_rgba_to_png(png, dec["width"], dec["height"])).decode("ascii")})
        gltf["textures"].append({"sampler": 0, "source": len(gltf["images"]) - 1})
        tex_by_index[t["index"]] = len(gltf["textures"]) - 1

    def material_for(rec: dict) -> int | None:
        for tid in rec.get("texture_ids", []):
            if tid in tex_by_index:
                gltf["materials"].append({"name": f"tex{tid}",
                                          "pbrMetallicRoughness": {
                                              "baseColorTexture": {"index": tex_by_index[tid]},
                                              "metallicFactor": 0.0, "roughnessFactor": 1.0}})
                return len(gltf["materials"]) - 1
        return None

    total_tris = 0
    total_verts = 0
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
        jid = node_joint.get(r.offset, 0)
        joint_attr = struct.pack(">" + "H" * len(verts), *([jid] * len(verts)))
        joint_acc = add_accessor(joint_attr, 5123, len(verts), "VEC4")
        weight = struct.pack(">" + "f" * len(verts), *([1.0] * len(verts)))
        weight_acc = add_accessor(weight, 5126, len(verts), "VEC4")
        tri_acc = None
        tris = [t for t in r.triangles if all(0 <= i < len(verts) for i in t)]
        if tris:
            idx = struct.pack(">" + "HHH" * len(tris), *[c for t in tris for c in t])
            tri_acc = add_accessor(idx, 5123, len(tris) * 3, "SCALAR")
            total_tris += len(tris)
        mat = material_for(r.record)
        mesh = {"primitives": [{"attributes": {"POSITION": pos_acc, "COLOR_0": col_acc,
                                               "TEXCOORD_0": uv_acc,
                                               "JOINTS_0": joint_acc, "WEIGHTS_0": weight_acc},
                                **({"indices": tri_acc} if tri_acc is not None else {}),
                                "mode": 4 if tri_acc is not None else 0,
                                **({"material": mat} if mat is not None else {}),
                                "extras": {"texture_ids": r.record.get("texture_ids", []),
                                           "node_offset": r.offset,
                                           "triangle_hint": r.triangle_hint}}]}
        gltf["meshes"].append(mesh)
        gltf["nodes"].append({"name": f"mesh_{r.offset:04X}",
                              "mesh": len(gltf["meshes"]) - 1,
                              "skin": 0})
        gltf["scenes"][0]["nodes"].append(len(gltf["nodes"]) - 1)
        total_verts += len(verts)

    # self-contained .gltf: embed the buffer as a data URI (no external .bin)
    gltf["buffers"][0]["byteLength"] = len(bin_blob)
    gltf["buffers"][0]["uri"] = "data:application/octet-stream;base64," + \
        base64.b64encode(bytes(bin_blob)).decode("ascii")
    out_path = Path(out_path)
    out_path.write_text(json.dumps(gltf, indent=1))
    return {"file": str(out_path), "joints": len(joints),
            "meshes": len(gltf["meshes"]), "triangles": total_tris,
            "vertices": total_verts}


def extract_run(ctx, game: dict, entry: dict, work) -> dict:
    """characters.DEDICATED run(): decode one body to a rigged .gltf."""
    from .models import CatalogEntry
    from .tools import rom_path
    p = rom_path(CatalogEntry.model_validate(game), ctx.config)
    ge = GoldenEyeROM.load(p)
    out = Path(work) / (entry["slug"] + ".gltf")
    stats = to_gltf(ge, entry["key"], out)
    return {"files": [out], "tool": "gbox.goldeneye_reader",
            "source_files": [entry["key"]],
            "notes": f"Native GoldenEye Z-file body: {stats['joints']}-joint skeleton, "
                     f"{stats['meshes']} meshes, {stats['triangles']} triangles, vertex colours. "
                     "Texture pixels are the next reader step (global g_Textures table)."}


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
