"""DOA5A (KT engine) TMC geometry probe: MdlGeo records -> VtxLay/IdxLay buffers.

Layout proven on HELENA_COS_001.tmc (decoded with doa5a_inventory.kt_decompress):

* ``MdlGeo`` is a KT container; each child record holds an ``ObjEO`` name block and a
  ``GeoDecl`` block.  Words after the 0x30-byte GeoDecl header: [7] = VtxLay/IdxLay slot, [8] = index count,
  [9] = vertex count, [17] = vertex stride (record size varies; GeoDecl is located by tag).
* ``VtxLay`` / ``IdxLay`` children are raw buffers: vertices are ``stride`` bytes with a
  float3 position first (stride 0x38 here); indices are u16 (checked: max < vertex count).
  Buffers are padded to 16 bytes.

Field meanings beyond those used here (primitive type, vertex attribute order) are hypotheses.
Loader xrefs in DOA5A.exe are still outstanding (Ghidra job failed earlier).
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
