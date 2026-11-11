"""NW4R BRRES ``MDL0`` (model) reader, v8-v11, big-endian.

Verified on Metroid: Other M (R3OJ01) FST file '0' ``samus_normal`` (v11).
Decodes: header/section table, properties (vertex/face/bone counts, extents),
bone tree (SRT + parent links), vertex arrays (position/normal/uv), and the
material / object / texture-link name lists.  Display-list (face) decoding is a
later stage; object entries only expose their raw offsets.
"""
from __future__ import annotations

import struct

SECTIONS = ("defs", "bones", "verts", "norms", "colors", "uvs", "furvecs",
            "furlayers", "materials", "shaders", "objects", "textures",
            "palettes", "userdata")
_CT = {0: ("B", 1), 1: ("b", 1), 2: ("H", 2), 3: ("h", 2), 4: ("f", 4)}


class Mdl0Error(ValueError):
    pass


def _u32(b, o):
    return struct.unpack_from(">I", b, o)[0]


def _s32(b, o):
    return struct.unpack_from(">i", b, o)[0]


def _cstr(b, o):
    n = _u32(b, o - 4)
    if n > 512 or o + n > len(b):
        raise Mdl0Error("bad string")
    return b[o:o + n].decode("latin1")


def _group(b: bytes, base: int):
    """Resource dict group -> [(name, absolute data offset)] (index 0 is root)."""
    if base < 0 or base + 8 > len(b):
        raise Mdl0Error("group out of range")
    _sz, n = struct.unpack_from(">II", b, base)
    if n > 8192:
        raise Mdl0Error("implausible group size")
    out = []
    for i in range(1, n + 1):
        o = base + 8 + 16 * i
        _i, _f, _l, _r, no, do = struct.unpack_from(">HHHHII", b, o)
        out.append((_cstr(b, base + no), base + do))
    return out


def _vec(b, o, n):
    return struct.unpack_from(">%df" % n, b, o)


def parse_bone(b, o, name):
    (ln, mo, so, idx, node, flags, bb, ref) = struct.unpack_from(">8I", b, o)
    scale, rot, trans = _vec(b, o + 0x20, 3), _vec(b, o + 0x2C, 3), _vec(b, o + 0x38, 3)
    vmin, vmax = _vec(b, o + 0x44, 3), _vec(b, o + 0x50, 3)
    par, child, nxt, prv, p2 = struct.unpack_from(">5i", b, o + 0x5C)
    return {"name": name, "index": idx, "node_id": node, "flags": flags,
            "scale": scale, "rot_deg": rot, "trans": trans, "min": vmin, "max": vmax,
            "parent_off": par, "bind": _vec(b, o + 0x70, 12), "off": o}


def parse_vertex_array(b, o, name, kind):
    ln, mo, do, so, idx, comp, typ = struct.unpack_from(">7I", b, o)
    div, stride, cnt = struct.unpack_from(">BBH", b, o + 0x1C)
    nf = 3 if kind in ("pos", "norm") else 2
    if kind == "pos":
        nf = 3 if comp else 2
    if kind == "uv":
        nf = 2 if comp else 1
    if typ not in _CT:
        raise Mdl0Error("bad component type %d" % typ)
    fmt, sz = _CT[typ]
    start = o + do
    if start + cnt * stride > len(b):
        raise Mdl0Error("vertex data out of range")
    if stride != nf * sz and kind != "norm":
        raise Mdl0Error("stride %d != %d*%d" % (stride, nf, sz))
    nf_dec = min(nf, stride // sz)
    pts = []
    sc = 1.0 / (1 << div) if typ != 4 else 1.0
    for i in range(cnt):
        v = struct.unpack_from(">%d%s" % (nf_dec, fmt), b, start + i * stride)
        pts.append(tuple(x * sc for x in v))
    return {"name": name, "index": idx, "type": typ, "divisor": div, "stride": stride,
            "count": cnt, "components": nf_dec, "data_off": start, "values": pts}


def parse_object(b, o, name):
    """MDL0 object (polygons) entry, v11 layout.

    Header offsets are relative to this header start, per the Custom
    Mario Kart MDL0 wiki (section "Objects (Polygons)"). The vertex
    declaration offset is relative to field 0x20, the vertex data
    offset relative to field 0x24. The bone table sits immediately
    after the 0x68 header (u32 count + u16 per-vertex IDs; 0xFFFF seen
    for static vertices); its use is documented as only partially
    understood, so it is stored as raw data.
    """
    ln, mo, bone, cpvtx, cptex, norspec, declsz, uflags = struct.unpack_from(
        ">8i", b, o)
    decl_off, vds1, vds2, vdata_off, xfflags, unk = struct.unpack_from(
        ">6i", b, o + 0x20)
    name_off, idx, nverts, nfaces = struct.unpack_from(
        ">4i", b, o + 0x38)
    vg, ng, c0, c1 = struct.unpack_from(">4H", b, o + 0x48)
    tg = struct.unpack_from(">8H", b, o + 0x50)
    unk60, bt_off = struct.unpack_from(">2i", b, o + 0x60)

    def grp(i):
        return None if i >= 0x8000 else i

    ob = {
        "name": name, "off": o, "index": idx, "length": ln,
        "bone_index": bone,
        "vertex_count": nverts, "face_count": nfaces,
        "vertex_group": grp(vg), "normal_group": grp(ng),
        "color_groups": [grp(c0), grp(c1)],
        "tex_groups": [grp(t) for t in tg],
        "decl_offset": decl_off, "decl_size": declsz,
        "vertex_data_offset": vdata_off, "vertex_data_size": vds1,
        "xf_flags": xfflags, "bone_table_offset": bt_off,
    }
    if bt_off:
        bt = o + bt_off
        cnt = _u32(b, bt)
        if cnt > nverts:
            raise Mdl0Error(
                "object %r bone table count %d > vertex count" % (name, cnt))
        ob["bone_table"] = list(struct.unpack_from(">%dH" % cnt, b, bt + 4))
    # raw GX/GXL payloads, offsets verified against real samus_normal data
    dstart = o + 0x20 + decl_off
    ob["decl_bytes"] = b[dstart:dstart + declsz]
    cstart = o + 0x24 + vdata_off
    ob["code_bytes"] = b[cstart:o + ln]
    return ob


def decode_display_list(mdl):
    """Validate and total the object/display-list section.

    Resolves each object's vertex/normal group bindings against the
    vertex/normal arrays, checks bone-table counts, and sums face
    counts. Acceptance on real data: total_faces must equal the MDL0
    header face count (9980 for samus_normal).
    """
    objs = []
    for ob in mdl["objects"]:
        vg = ob["vertex_group"]
        if vg is None or vg >= len(mdl["verts"]):
            raise Mdl0Error("object %r vertex group %r out of range"
                            % (ob["name"], vg))
        v = mdl["verts"][vg]
        # 0x48 group-field semantics still under verification (real data
        # binds some objects to arrays smaller than their vertex count),
        # so record binding validity instead of failing the decode.
        gsize_ok = v["count"] >= ob["vertex_count"]
        rec = dict(ob)
        rec["vertex_array"] = v["name"]
        rec["group_size_ok"] = gsize_ok
        rec["normal_array"] = (
            mdl["norms"][ob["normal_group"]]["name"]
            if ob["normal_group"] is not None
            and ob["normal_group"] < len(mdl["norms"]) else None)
        objs.append(rec)
    total_faces = sum(o["face_count"] for o in objs)
    return {
        "objects": objs,
        "total_faces": total_faces,
        "header_faces": mdl["num_faces"],
        "consistent": total_faces == mdl["num_faces"],
        "all_group_size_ok": all(o["group_size_ok"] for o in objs),
    }


def parse_mdl0(b: bytes, o: int = 0) -> dict:
    if b[o:o + 4] != b"MDL0":
        raise Mdl0Error("not MDL0")
    size, ver = struct.unpack_from(">II", b, o + 4)
    if ver not in (8, 9, 10, 11):
        raise Mdl0Error("unsupported MDL0 version %d" % ver)
    n_off = 14 if ver == 11 else 12
    offs = struct.unpack_from(">%di" % n_off, b, o + 0x10)
    names = SECTIONS[:n_off]
    name = _cstr(b, o + _s32(b, o + 0x10 + 4 * n_off))
    po = o + 0x10 + 4 * n_off + 4
    (hl, _mo, scaling, texmtx, nverts, nfaces, _orig, nnodes) = struct.unpack_from(">IiIIIIII", b, po)
    mdl = {"name": name, "version": ver, "size": size, "offset": o,
           "scaling_rule": scaling, "num_vertices": nverts, "num_faces": nfaces,
           "num_bones": nnodes, "min": _vec(b, po + 0x28, 3), "max": _vec(b, po + 0x34, 3),
           "sections": {}}
    for nm, off in zip(names, offs):
        if off:
            mdl["sections"][nm] = [(n, d) for n, d in _group(b, o + off)]
    mdl["bones"] = [parse_bone(b, d, n) for n, d in mdl["sections"].get("bones", [])]
    # parent resolution by absolute offset
    by_off = {bn["off"]: bn["name"] for bn in mdl["bones"]}
    for bn in mdl["bones"]:
        bn["parent"] = by_off.get(bn["off"] + bn["parent_off"]) if bn["parent_off"] else None
    for key, kind in (("verts", "pos"), ("norms", "norm"), ("uvs", "uv")):
        mdl[key] = [parse_vertex_array(b, d, n, kind) for n, d in mdl["sections"].get(key, [])]
    mdl["materials"] = [n for n, _ in mdl["sections"].get("materials", [])]
    mdl["objects"] = [parse_object(b, d, n) for n, d in mdl["sections"].get("objects", [])]
    mdl["textures"] = [n for n, _ in mdl["sections"].get("textures", [])]
    return mdl
