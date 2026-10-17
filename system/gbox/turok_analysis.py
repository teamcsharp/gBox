# Turok: Dinosaur Hunter (N64, NTUE Rev B) — per-object geometry & animation
# analysis over the tengine CIndexedSet cart tree.
#
# Layout (Acclaim/Iguana "tengine"; cartdir.h / romstruc.h / geometry.cpp,
# the released official source — struct names and block indices below are
# the exact source identifiers):
#
#   Cart root @0x1F00: 11 collections (CIndexedSet).
#   GraphicObjects[i] (CGraphicObject) is an indexed set of 4:
#     [0] ObjectInfo    — { bounds, usAnimTypes } (CART_OBJECTINFO)
#     [1] Geometry      — CIndexedSet of 2:
#           [0] info        (CROMGeometryInfo, 1 DWORD)
#           [1] isNodes     — CIndexedSet of CNode; each node is a set of 3:
#                 [0] usChildNodeIndices  (CUnindexedSet of u16)
#                 [1] usPartIndices       (CUnindexedSet of u16)
#                 [2] isParts             — CIndexedSet of CPart; each part is
#                     a set of CSections; each section is a set of 3:
#                     [0] section   (CROMSection: texSet, matFlags, RGBA,
#                                    blackColor, MultU, MultV = 20 bytes)
#                     [1] usPStream (CUnindexedSet of u16 POLYSTREAM words)
#                     [2] usVertices(CUnindexedSet of Vtx, 16 bytes each)
#     [2] Anims        — anim table (see parse_anim below)
#     [3] StaticEvents
#
#   POLYSTREAM word (u16): 5b VA, 5b VB, 5b VC, 1b LASTINRUN.
#   Each word is one triangle; VA/VB/VC index a 32-entry vertex cache
#   (VERTEX_CACHE_SIZE).  LASTINRUN closes the current triangle strip,
#   so the stream packs whole triangle strips: tri_i = {V, V+1, V+2} of
#   the strip under construction, with odd/even winding swapped.
#
#   Vtx (rommodel.h): ob[3] s16 xyz, u16 flag, tc[2] s16, then either
#   cn[4] u8 RGBA (color vertex) or n[3] s8 + a u8 (normal vertex).
#
#   Anims block: CIndexedSet of 7 (CART_ANIM):
#     [0] usYRotations      — CUnindexedSet u16, count = nFrames
#     [1] usNodeAnimIndices — CUnindexedSet CROMNodeIndex {s16 transSet,
#                              s16 rotSet}, count = nNodes
#     [2] usInitialOrients  — CUnindexedSet CROMInitialOrientation
#                              {CVector3 pos(12B), 4x s16 rot}, nNodes
#     [3] usTranslationSets — CUnindexedSet of per-set CUnindexedSets of
#                              CPosFrame (12B), nFrames each
#     [4] usRotationSets    — same with CRotFrame (8B)
#     [5] isTransitionTable
#     [6] usEvents
#
# The per-object Geometry/Anims blocks may be RNC(Propack)-packed inside the
# collection payload; decode with turok_inventory.decode_rnc first.
from __future__ import annotations

import argparse
import json
import struct
import sys

from gbox import turok_inventory as ti

GRAPHOBJ_NAMES = ti.GRAPHOBJ_NAMES
CART_ROOT_OFFSET = ti.CART_ROOT_OFFSET

# cartdir.h block indices
GEOM_INFO, GEOM_NODES = 0, 1
NODE_CHILD_INDICES, NODE_PART_INDICES, NODE_PARTS = 0, 1, 2
SECTION_SECTION, SECTION_PSTREAM, SECTION_VERTICES = 0, 1, 2
ANIM_YROTS, ANIM_NODEIDX, ANIM_INITOR, ANIM_TRANS, ANIM_ROTS = 0, 1, 2, 3, 4
ANIM_TRANTABLE, ANIM_EVENTS = 5, 6

VERTEX_CACHE_SIZE = 32
POLYSTREAM_LASTINRUN = 1 << 15

CROMSECTION = struct.Struct(">II4s4sHH")          # 20 bytes
VTX = struct.Struct(">3hH2h")                     # first 12 bytes of Vtx
VTX_TAIL = struct.Struct(">4s")                   # color RGBA / normal+alpha
CROMNODEINDEX = struct.Struct(">hh")              # 4 bytes
CROMINITORIENT = struct.Struct(">3f4h")           # 20 bytes: no padding!
CPOSFRAME = struct.Struct(">3f")                  # 12 bytes
CROTFRAME = struct.Struct(">4h")                  # 8 bytes


def _unindexed(blob: bytes, rec_size: int | None = None):
    """Parse a CUnindexedSet payload: {u32 BlockSize, u32 BlockCount, data}."""
    if len(blob) < 8:
        raise ValueError(f"unindexed set payload too short ({len(blob)}B)")
    bsize, count = struct.unpack_from(">II", blob, 0)
    data = blob[8:]
    if count and not bsize:
        raise ValueError(f"unindexed set of {count} zero-size records")
    if bsize * count > len(data):
        raise ValueError(
            f"unindexed set {bsize}x{count} overruns payload ({len(data)}B)")
    if rec_size is not None and bsize and bsize != rec_size:
        raise ValueError(f"record size {bsize} != expected {rec_size}")
    return {"block_size": bsize, "count": count, "data": data}


def _indexed(blob: bytes, base: int = 0):
    """Parse a CIndexedSet and return blocks as raw byte slices.

    A count-0 indexed set serializes as a bare {u32 count=0} header (the
    offsets array is empty) and yields no blocks."""
    if len(blob) - base >= 4 and struct.unpack_from(">I", blob, base)[0] == 0:
        return []
    blocks = ti.parse_indexed(blob, base)
    if blocks is None:
        raise ValueError("not a CIndexedSet")
    return [blob[base + off: base + off + size] for off, size in blocks]


def _decode_polystream_words(data: bytes) -> list[tuple[int, int, int, bool]]:
    """POLYSTREAM u16 words -> (va, vb, vc, last_in_run)."""
    words = struct.unpack_from(f">{len(data) // 2}H", data, 0)
    return [((w >> 0) & 31, (w >> 5) & 31, (w >> 10) & 31, bool(w & POLYSTREAM_LASTINRUN))
            for w in words]


def _polystream_triangles(words, n_vertices: int) -> list[tuple[int, int, int]]:
    """Expand polystream words into absolute vertex-index triangles.

    Each u16 word IS one triangle; VA/VB/VC address the section's vertex
    array directly (the loader maps them into RSP cache slots when building
    the display list, geometry.cpp).  LASTINRUN only groups triangles into
    draw commands and carries no geometry semantics for extraction."""
    tris = []
    for va, vb, vc, _last in words:
        if max(va, vb, vc) >= n_vertices:
            raise ValueError(
                f"polystream word ({va},{vb},{vc}) exceeds {n_vertices} vertices")
        tris.append((va, vb, vc))
    return tris


def parse_geometry(blob: bytes) -> dict:
    """Decode one CGraphicObject Geometry block into nodes/parts/sections."""
    geom = _indexed(blob)
    if len(geom) != 2:
        raise ValueError(f"geometry has {len(geom)} blocks, want 2")
    info = _unindexed(geom[GEOM_INFO])
    if info["count"] > 1 or info["block_size"] not in (0, 4):
        raise ValueError(f"geometry info {info['block_size']}x{info['count']}")
    morph = struct.unpack_from(">I", info["data"], 0)[0] if len(info["data"]) >= 4 else 0

    nodes_blob = geom[GEOM_NODES]
    node_blocks = _indexed(nodes_blob)
    nodes = []
    for nb in node_blocks:
        node = _indexed(nb)
        if len(node) != 3:
            raise ValueError(f"node has {len(node)} blocks, want 3")
        child = _unindexed(node[NODE_CHILD_INDICES])
        if child["block_size"] not in (0, 4):
            raise ValueError(f"child index record {child['block_size']}B")
        children = list(struct.unpack_from(f">{child['count']}I", child["data"], 0)) \
            if child["count"] else []
        part_idx = _unindexed(node[NODE_PART_INDICES])
        if part_idx["block_size"] not in (0, 4):
            raise ValueError(f"part index record {part_idx['block_size']}B")
        part_indices = list(struct.unpack_from(f">{part_idx['count']}I", part_idx["data"], 0)) \
            if part_idx["count"] else []
        parts_blob = node[NODE_PARTS]
        part_blocks = _indexed(parts_blob)
        parts = []
        for pb in part_blocks:
            section_blocks = _indexed(pb)
            sections = []
            for sb in section_blocks:
                sec = _indexed(sb)
                if len(sec) != 3:
                    raise ValueError(f"section has {len(sec)} blocks, want 3")
                # CART_SECTION_section is a RAW CROMSection (20 bytes), not a
                # CUnindexedSet — the runtime casts it directly.
                raw_sec = sec[SECTION_SECTION]
                if len(raw_sec) >= 20:
                    texset, matflags, color, black, mu, mv = \
                        CROMSECTION.unpack_from(raw_sec, 0)
                    section_info = {
                        "texset": texset, "matflags": matflags,
                        "color": list(color), "black": list(black),
                        "mult_u": mu, "mult_v": mv,
                    }
                else:
                    section_info = {"texset": None, "matflags": None,
                                    "color": None, "black": None,
                                    "mult_u": None, "mult_v": None}
                ps = _unindexed(sec[SECTION_PSTREAM])
                if ps["block_size"] not in (0, 2):
                    raise ValueError(f"polystream record {ps['block_size']}B")
                words = _decode_polystream_words(ps["data"])
                vt = _unindexed(sec[SECTION_VERTICES])
                if vt["block_size"] not in (0, 16):
                    raise ValueError(f"vertex record {vt['block_size']}B")
                # ROM vertices are planar-by-byte (all bytes of component 0,
                # then component 1, ...); CUnindexedSet__DeinterleaveCopy /
                # geometry.cpp's inline loop rebuild the interleaved Vtx.
                raw = vt["data"]
                inter = bytearray()
                for i in range(vt["count"]):
                    for c in range(16):
                        inter.append(raw[c * vt["count"] + i])
                vertices = [VTX.unpack_from(inter, i * 16)
                            for i in range(vt["count"])]
                if vt["count"]:
                    tails = [VTX_TAIL.unpack_from(inter, i * 16 + 12)[0]
                             for i in range(vt["count"])]
                else:
                    tails = []
                # every vertex cache index must stay inside the vertex block
                bad = [w for w in words
                       if max(w[0], w[1], w[2]) >= vt["count"]]
                if bad:
                    raise ValueError(
                        f"{len(bad)} polystream words index beyond "
                        f"{vt['count']} vertices")
                sections.append({
                    "info": section_info,
                    "n_vertices": vt["count"],
                    "vertices": vertices,
                    "vertex_tails": tails,
                    "polystream": words,
                    "triangles": _polystream_triangles(words, vt["count"]),
                })
            parts.append({"sections": sections})
        nodes.append({
            "child_node_indices": children,
            "part_indices": part_indices,
            "parts": parts,
        })
    return {"info": {"morph_frame": morph}, "nodes": nodes}


def parse_anim(blob: bytes) -> dict:
    """Decode one CGraphicObject Anims collection: an indexed set of anim
    entries, each an (optionally RNC-packed) 7-block CART_ANIM indexed set.

    An empty collection is a bare {u32 count=0} and yields no entries."""
    entries = _indexed(blob)
    anims = []
    for entry in entries:
        data = entry
        if data[:3] == b"RNC":
            data = ti.decode_rnc(data)
        anim = _indexed(data)
        if len(anim) != 7:
            raise ValueError(f"anim has {len(anim)} blocks, want 7")
        yrots = _unindexed(anim[ANIM_YROTS])
        if yrots["block_size"] not in (0, 2):
            raise ValueError(f"yrot record {yrots['block_size']}B")
        nframes = yrots["count"]
        yrots_vals = list(struct.unpack_from(f">{nframes}H", yrots["data"], 0)) \
            if nframes else []

        node_idx = _unindexed(anim[ANIM_NODEIDX])
        if node_idx["block_size"] not in (0, 4):
            raise ValueError(f"node index record {node_idx['block_size']}B")
        nnodes = node_idx["count"]
        node_anim_indices = [CROMNODEINDEX.unpack_from(node_idx["data"], i * 4)
                             for i in range(nnodes)]

        initor = _unindexed(anim[ANIM_INITOR])
        if initor["block_size"] not in (0, 20):
            raise ValueError(f"initial orient record {initor['block_size']}B")
        initor_count = initor["count"]
        initial_orientations = [
            CROMINITORIENT.unpack_from(initor["data"], i * 20)
            for i in range(initor_count)]

        def _frames_sets(raw, rec_size, name):
            us = _unindexed(raw)
            sets = []
            for i in range(us["count"]):
                off = i * us["block_size"]
                if us["block_size"] != 8 + nframes * rec_size:
                    raise ValueError(
                        f"{name} set {i}: {us['block_size']}B != "
                        f"8+{nframes}x{rec_size}")
                sub = _unindexed(raw[8 + off: 8 + off + us["block_size"]])
                if sub["count"] != nframes or sub["block_size"] != rec_size:
                    raise ValueError(
                        f"{name} set {i}: {sub['block_size']}x{sub['count']}")
                sets.append(sub["data"])
            return sets

        trans_raw = anim[ANIM_TRANS]
        trans_sets = _frames_sets(trans_raw, CPOSFRAME.size, "translation") \
            if len(trans_raw) >= 8 and _unindexed(trans_raw)["count"] else []
        rots_raw = anim[ANIM_ROTS]
        rot_sets = _frames_sets(rots_raw, CROTFRAME.size, "rotation") \
            if len(rots_raw) >= 8 and _unindexed(rots_raw)["count"] else []
        trantable = _try_indexed(anim[ANIM_TRANTABLE])
        events = _unindexed(anim[ANIM_EVENTS]) if len(anim[ANIM_EVENTS]) >= 8 else None
        anims.append({
            "n_frames": nframes,
            "y_rotations": yrots_vals,
            "n_nodes": nnodes,
            "node_anim_indices": node_anim_indices,
            "initial_orientations": initial_orientations,
            "translation_sets": trans_sets,
            "rotation_sets": rot_sets,
            "transition_table_blocks": trantable is not None,
            "events": events,
        })
    return {"anims": anims}


def _try_indexed(blob: bytes):
    try:
        return _indexed(blob)
    except ValueError:
        return None


def graphic_object(rom: bytes, obj: dict) -> dict:
    """Fetch + decode all four CGraphicObject sub-blocks for one object."""
    out = {"index": obj["i"]}
    for key in GRAPHOBJ_NAMES:
        b = obj[key]
        blob = rom[obj["rom"] + b["rel"]: obj["rom"] + b["rel"] + b["size"]]
        packed = None
        if blob[:3] == b"RNC":
            packed = blob[3]
            blob = ti.decode_rnc(blob)
        out[key] = {"size": b["size"], "packed_method": packed,
                    "unpacked": len(blob), "data": blob}
    return out


def decode_object(rom: bytes, obj: dict) -> dict:
    go = graphic_object(rom, obj)
    res = {"index": obj["i"]}
    for key in ("Geometry", "Anims"):
        data = go[key]["data"]
        if key == "Geometry":
            try:
                res["geometry"] = parse_geometry(data)
            except ValueError as e:
                res["geometry_error"] = str(e)
        else:
            try:
                res["anim"] = parse_anim(data)
            except ValueError as e:
                res["anim_error"] = str(e)
    return res


def analyze(rom: bytes, limit: int | None = None) -> dict:
    inv = ti.inventory(rom)
    objs = inv["graphic_objects"]["objects"]
    n_ok = n_geom_err = n_anim_err = 0
    stats = []
    for obj in objs[:limit]:
        r = decode_object(rom, obj)
        if "geometry" in r:
            n_ok += 1
            g = r["geometry"]
            n_nodes = len(g["nodes"])
            n_parts = sum(len(n["parts"]) for n in g["nodes"])
            n_secs = sum(len(p["sections"]) for n in g["nodes"]
                         for p in n["parts"])
            n_vtx = sum(s["n_vertices"] for n in g["nodes"]
                        for p in n["parts"] for s in p["sections"])
            n_tri = sum(len(s["triangles"]) for n in g["nodes"]
                        for p in n["parts"] for s in p["sections"])
            stats.append({"i": obj["i"], "nodes": n_nodes, "parts": n_parts,
                          "sections": n_secs, "vertices": n_vtx,
                          "triangles": n_tri})
            if "anim" in r:
                pass
        else:
            n_geom_err += 1
        if "anim_error" in r:
            n_anim_err += 1
    return {
        "objects_total": len(objs[:limit]),
        "geometry_ok": n_ok,
        "geometry_errors": n_geom_err,
        "anim_parse_failures": n_anim_err,
        "stats": stats,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("src", help="ROM path (.z64/.n64/.v64 or the owned .zip)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--obj", type=int, default=None,
                    help="dump a single graphic object index as JSON")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    from gbox import n64_rom
    raw = n64_rom.read(args.src)
    if args.obj is not None:
        inv = ti.inventory(raw)
        obj = inv["graphic_objects"]["objects"][args.obj]
        res = decode_object(raw, obj)
        # compact structural dump: drop raw vertex/polystream payloads
        if "geometry" in res:
            for n in res["geometry"]["nodes"]:
                for p in n["parts"]:
                    for s in p["sections"]:
                        s.pop("vertices", None)
                        s.pop("vertex_tails", None)
                        s.pop("polystream", None)
        print(json.dumps(res, indent=1))
        return 0
    res = analyze(raw, args.limit)
    text = json.dumps(res, indent=1)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
    else:
        print(text[:200000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
