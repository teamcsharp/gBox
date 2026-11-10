"""DOA5A (KT engine) TMC geometry probe: MdlGeo records -> VtxLay/IdxLay buffers.

Layout proven on HELENA_COS_001.tmc (decoded with doa5a_inventory.kt_decompress):

* ``MdlGeo`` is a KT container; each child record holds an ``ObjEO`` name block and a
  ``GeoDecl`` block.  Words after the 0x30-byte GeoDecl header: [7] = VtxLay/IdxLay slot, [8] = index count,
  [9] = vertex count, [17] = vertex stride (record size varies; GeoDecl is located by tag).
* ``VtxLay`` / ``IdxLay`` children are raw buffers: vertices are ``stride`` bytes with a
  float3 position first (stride 0x38 here); indices are u16 (checked: max < vertex count).
  Buffers are padded to 16 bytes.

Field meanings beyond those used here (primitive type, vertex attribute order) are hypotheses.
Loader (Ghidra job 4b5ad51f15374e23): FUN_00a97670 validates MdlGeo/VtxLay/IdxLay/NodeLay chunks; chunk header u32 +0x14 = child count, +0x2c (VtxLay/IdxLay) / +0x20 (NodeLay) = relative offset table.
"""
from __future__ import annotations

import struct

from gbox.doa5a_inventory import container_children, kt_decompress, parse_container

W_LAYER, W_IDX, W_VTX, W_STRIDE = 7, 8, 9, 17  # u32 words after GeoDecl header (+0x30)


def _child_base(raw: bytes, tag: str) -> int:
    for k in container_children(raw):
        if k["tag"] == tag:
            return k["offset"]
    raise ValueError(f"TMC has no {tag} chunk")


def read_geometry(raw: bytes) -> list[dict]:
    """Return one dict per MdlGeo record with counts, buffer slot and byte ranges."""
    go, vo, io = (_child_base(raw, t) for t in ("MdlGeo", "VtxLay", "IdxLay"))
    geo, vtx, idx = (parse_container(raw, b) for b in (go, vo, io))
    out = []
    for i, off in enumerate(geo["offsets"]):
        if not off:
            continue
        rec = go + off
        end = go + (geo["offsets"][i + 1] if i + 1 < len(geo["offsets"]) else geo["size"])
        d = raw.find(b"GeoDecl\0", rec, end)
        if d < 0:
            raise ValueError(f"geo {i}: no GeoDecl block")
        words = struct.unpack_from("<18I", raw, d + 0x30)
        name = raw[rec + 0x50:rec + 0x60].split(b"\0", 1)[0].decode("ascii", "replace")
        layer, n_idx, n_vtx, stride = words[W_LAYER], words[W_IDX], words[W_VTX], words[W_STRIDE]
        if layer >= vtx["count"] or layer >= idx["count"]:
            raise ValueError(f"geo {i}: layer {layer} outside Vtx/Idx tables")
        vb, ib = vo + vtx["offsets"][layer], io + idx["offsets"][layer]
        if n_vtx * stride > vtx["sizes"][layer] or n_idx * 2 > idx["sizes"][layer]:
            raise ValueError(f"geo {i}: counts exceed buffer sizes")
        out.append({"geo": i, "name": name, "layer": layer, "vertex_count": n_vtx,
                    "index_count": n_idx, "stride": stride, "vtx_offset": vb, "idx_offset": ib})
    return out


def read_indices(raw: bytes, g: dict) -> tuple[int, ...]:
    return struct.unpack_from(f"<{g['index_count']}H", raw, g["idx_offset"])


def read_positions(raw: bytes, g: dict) -> list[tuple[float, float, float]]:
    return [struct.unpack_from("<3f", raw, g["vtx_offset"] + n * g["stride"])
            for n in range(g["vertex_count"])]


# Vertex layout (proved on HELENA_COS_001 for strides 56/60/64: normals unit length, u8 weights sum to 255 on
# every vertex).  Offsets: 0 pos f32x3 | 12 normal f32x3 | 24 weights u8x4 | 28 bone idx u8x4 (local to the
# geo's palette - palette ownership is NOT yet traced) | 32 tangent f32x3 | 44 tangent sign f32 | 48 uv0 f16x2 for
# stride 56 (uv1 duplicates uv0).  Strides 60/64 carry extra attributes after 32 that are not decoded here.
VTX_NORMAL, VTX_WEIGHTS, VTX_BONES, VTX_TANGENT, VTX_UV0 = 12, 24, 28, 32, 48


def read_vertices(raw: bytes, g: dict) -> dict:
    """Decode position/normal/skin weights/bone indices (all strides) and uv0 (stride 56 only)."""
    import numpy as np
    n, s, o = g["vertex_count"], g["stride"], g["vtx_offset"]
    u8 = np.frombuffer(raw, dtype=np.uint8, count=n * s, offset=o).reshape(n, s)
    f32 = np.frombuffer(raw, dtype="<f4", count=n * s // 4, offset=o).reshape(n, s // 4)
    out = {"position": f32[:, 0:3].copy(), "normal": f32[:, 3:6].copy(),
           "weights": u8[:, VTX_WEIGHTS:VTX_WEIGHTS + 4].copy(), "bones": u8[:, VTX_BONES:VTX_BONES + 4].copy()}
    if s == 56:
        f16 = np.frombuffer(raw, dtype="<f2", count=n * s // 2, offset=o).reshape(n, s // 2)
        out["uv0"] = f16[:, 24:26].astype("f4")
    return out


def read_triangles(raw: bytes, g: dict) -> list[tuple[int, int, int]]:
    """Index buffers are triangle strips joined by degenerate triangles (hypothesis backed by odd index
    counts, 2965 repeated-index windows on the body, and sane edge lengths); degenerates are dropped."""
    ix, tris = read_indices(raw, g), []
    for i in range(len(ix) - 2):
        a, b, c = ix[i:i + 3]
        if a == b or b == c or a == c:
            continue
        tris.append((a, b, c) if i % 2 == 0 else (b, a, c))
    return tris


def export_obj(raw: bytes, path: str, names: tuple[str, ...] | None = None) -> dict:
    """Write geos (all, or those named) as OBJ objects with normals/uv0; skin weights go in a .weights.json
    sidecar ({object: [[(bone, weight255)...] per vertex]}). Returns counts."""
    import json
    lines, side, v0, nt = [], {}, 1, 0
    for g in read_geometry(raw):
        if names and g["name"] not in names:
            continue
        v, t = read_vertices(raw, g), read_triangles(raw, g)
        lines.append(f"o {g['name']}")
        lines += [f"v {x:.6f} {y:.6f} {z:.6f}" for x, y, z in v["position"]]
        lines += [f"vn {x:.5f} {y:.5f} {z:.5f}" for x, y, z in v["normal"]]
        has_uv = "uv0" in v
        if has_uv:
            lines += [f"vt {u:.5f} {1 - w:.5f}" for u, w in v["uv0"]]
        for a, b, c in t:
            lines.append("f " + " ".join(
                f"{i + v0}/{i + v0}/{i + v0}" if has_uv else f"{i + v0}//{i + v0}" for i in (a, b, c)))
        side[g["name"]] = [[(int(b), int(w)) for b, w in zip(bs, ws) if w]
                           for bs, ws in zip(v["bones"], v["weights"])]
        v0 += g["vertex_count"]
        nt += len(t)
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    with open(path + ".weights.json", "w") as f:
        json.dump(side, f)
    return {"objects": len(side), "vertices": v0 - 1, "triangles": nt}


def geometry_summary(raw: bytes) -> list[dict]:
    """Per-geo counts, max index and position bounding box (for pinning in tests)."""
    res = []
    for g in read_geometry(raw):
        ix, ps = read_indices(raw, g), read_positions(raw, g)
        res.append({k: g[k] for k in ("geo", "name", "layer", "vertex_count", "index_count", "stride")}
                   | {"max_index": max(ix),
                      "bbox_min": [min(p[a] for p in ps) for a in range(3)],
                      "bbox_max": [max(p[a] for p in ps) for a in range(3)]})
    return res


def load_tmc(path: str) -> bytes:
    with open(path, "rb") as f:
        return kt_decompress(f.read())


# --- static loader probe (DOA5A.exe, PE32 i386, base 0x400000) ----------------------------------
CHUNK_TAGS = ("HieLay", "LHeader", "VtxLay", "IdxLay", "BnOfsMtx", "GlblMtx", "MHeader", "MdlInfo",
              "MtrCol", "MdlGeo", "NodeLay", "GeoDecl")


def _pe_sections(b: bytes):
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    ns, oh = struct.unpack_from("<H", b, pe + 6)[0], struct.unpack_from("<H", b, pe + 20)[0]
    base = struct.unpack_from("<I", b, pe + 52)[0]
    out = []
    for i in range(ns):
        o = pe + 24 + oh + i * 40
        vs, va, rs, ro = struct.unpack_from("<IIII", b, o + 8)
        out.append((b[o:o + 8].rstrip(b"\0").decode(), base + va, min(vs, rs) if rs else vs, ro))
    return out


def exe_chunk_tag_xrefs(exe: bytes) -> dict[str, dict]:
    """Static (no Ghidra) proof of the TMC chunk-tag loader: for every KT chunk tag string in the exe, its VA
    and the VAs of every 4-byte absolute pointer to it (push imm32 / table slot).  Pure byte scan."""
    secs = _pe_sections(exe)

    def va_of(off):
        for _, va, size, ro in secs:
            if ro <= off < ro + size:
                return va + off - ro

    res = {}
    for tag in CHUNK_TAGS:
        needle = tag.encode() + b"\0"
        i = exe.find(needle)
        while i >= 0 and (va_of(i) or 1) % 4:  # the tag table strings are 4-byte aligned
            i = exe.find(needle, i + 1)
        if i < 0:
            continue
        sva = va_of(i)
        pat, refs, j = struct.pack("<I", sva), [], exe.find(struct.pack("<I", sva))
        while j >= 0:
            refs.append(va_of(j))
            j = exe.find(pat, j + 1)
        res[tag] = {"va": sva, "refs": [r for r in refs if r]}
    return res
