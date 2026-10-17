"""Cooked USkeletalMesh -> rigged GLB (LOD0 positions, normals, UVs, indices, skin weights + reference skeleton).

Supported: UE 4.24-4.27 cooked packages with *tagged* properties (the "new cooked format", SkeletalMesh render data
split from the model). Everything else stops with MeshUnsupported naming the exact blocker:

- UE 4.0-4.18: the cooked mesh is an FStaticLODModel with chunks (pre-SplitModelAndRenderData), not parsed here.
- UE 4.19-4.23: the cooked LOD layout predates bInlined/streamed LODs (SerializeRenderItem_Legacy); not parsed here.
- Packages saved with unversioned property serialization (PKG_UnversionedProperties, an opt-in 4.26+ cook setting and
  the UE5 default): the tagged property stream is replaced by a schema-driven bit mask, so the parser cannot find
  where the mesh's native data begins without the engine's class layouts.
- UE5 (large-world-coordinate doubles, new section/weight fields) and IoStore (.utoc/.ucas zen packages).

Layouts follow USkeletalMesh::Serialize, FSkeletalMeshLODRenderData::Serialize / SerializeStreamedData,
FSkelMeshRenderSection, FStaticMeshVertexBuffer, FSkinWeightVertexBuffer (UE 4.24-4.27), cross-checked against the
open-source CUE4Parse reader. Units are converted from Unreal (left-handed, Z-up, centimetres) to glTF (right-handed,
Y-up, metres) with (x, y, z) -> (x, z, y) * 0.01.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .ue_asset import AssetError, Package, export_body
from .ue_pak import PakError, Reader

RF_CLASS_DEFAULT_OBJECT = 0x10
STRIP_EDITOR, STRIP_AUDIOVISUAL = 1, 2
CDSF_ADJACENCY = 1
BULK_PAYLOAD_AT_END = 0x1
BULK_ZLIB = 0x2
BULK_UNUSED = 0x20
BULK_FORCE_INLINE = 0x40
BULK_SEPARATE_FILE = 0x100
BULK_OPTIONAL = 0x800
BULK_SIZE64 = 0x2000
BULK_BAD_DATA_VERSION = 0x8000
BULK_NO_OFFSET_FIXUP = 0x10000
BULK_DUPLICATE_NON_OPTIONAL = 0x4000
UE_TO_GL = np.array([[1, 0, 0], [0, 0, 1], [0, 1, 0]], float)     # (x, y, z) -> (x, z, y): LH Z-up -> RH Y-up
CM_TO_M = 0.01


class MeshUnsupported(AssetError):
    """The asset is valid but its layout is outside what this exporter handles (message names the blocker)."""


def mesh_support(engine: tuple | None, pkg: Package) -> str | None:
    """None when export_skeletal_mesh can handle this package, else the exact blocker."""
    if not engine or engine[0] is None:
        return "engine version unknown: pass engine=(4, minor)"
    major, minor = engine[0], engine[1] or 0
    if major == 5:
        return "UE5 skeletal meshes (LWC doubles, new section fields, usually IoStore) are not supported yet"
    if major != 4:
        return f"engine {major}.{minor} is not Unreal Engine 4"
    if minor < 19:
        return (f"UE 4.{minor}: cooked mesh data predates SplitModelAndRenderData (FStaticLODModel with chunks); "
                "only 4.24-4.27 is implemented")
    if minor < 24:
        return (f"UE 4.{minor}: cooked LOD layout predates inlined/streamed LODs (SerializeRenderItem_Legacy); "
                "only 4.24-4.27 is implemented")
    if pkg.unversioned_properties:
        return ("package uses unversioned property serialization (PKG_UnversionedProperties): the property stream "
                "needs the engine's class schema, so the start of the native mesh data cannot be located")
    return None


def _fname(r: Reader, names: list[str]) -> str:
    idx, num = r.i32(), r.i32()
    if not 0 <= idx < len(names):
        raise AssetError(f"name index {idx} outside the name map")
    return names[idx] if num == 0 else f"{names[idx]}_{num - 1}"


def read_tagged_properties(r: Reader, pkg: Package) -> dict:
    """FPropertyTag stream up to 'None'. Returns {name: value} for simple types, raw bytes otherwise."""
    names, out = pkg.names, {}
    for _ in range(100000):
        name = _fname(r, names)
        if name == "None":
            return out
        ptype = _fname(r, names)
        size, _array_index = r.i32(), r.i32()
        boolval = None
        if ptype == "StructProperty":
            _fname(r, names)
            if pkg.ue4 >= 441:
                r.guid()
        elif ptype == "BoolProperty":
            boolval = bool(r.u8())
        elif ptype in ("ByteProperty", "EnumProperty"):
            _fname(r, names)
        elif ptype in ("ArrayProperty", "SetProperty"):
            _fname(r, names)
        elif ptype == "MapProperty":
            _fname(r, names); _fname(r, names)
        if pkg.ue4 >= 503 and r.u8():
            r.guid()
        if size < 0:
            raise AssetError(f"property {name}: negative size")
        raw = r.take(size)
        if boolval is not None:
            out[name] = boolval
        elif ptype in ("IntProperty", "ObjectProperty") and size == 4:
            out[name] = int.from_bytes(raw, "little", signed=True)
        elif ptype == "ByteProperty" and size == 1:
            out[name] = raw[0]
        else:
            out[name] = raw
    raise AssetError("property stream has no terminating None")


def _object_header(r: Reader, pkg: Package, flags: int) -> dict:
    props = read_tagged_properties(r, pkg)
    if not flags & RF_CLASS_DEFAULT_OBJECT and r.bool32():
        r.guid()
    return props


def _strip(r: Reader) -> tuple[int, int]:
    return r.u8(), r.u8()


def read_ref_skeleton(r: Reader, pkg: Package) -> list[dict]:
    """FReferenceSkeleton (cooked: no export names)."""
    editor = not pkg.summary["package_flags"] & 0x80000000
    bones = []
    for _ in range(r.count(12, limit=65536)):
        name, parent = _fname(r, pkg.names), r.i32()
        if editor:
            r.fstring()
        bones.append({"name": name, "parent": parent})
    n = r.count(40, limit=65536)
    if n != len(bones):
        raise AssetError(f"reference skeleton has {len(bones)} bones but {n} poses")
    for b in bones:
        q = [r.f32() for _ in range(4)]
        t = [r.f32() for _ in range(3)]
        s = [r.f32() for _ in range(3)]
        b.update(rotation=q, translation=t, scale=s)
    for _ in range(r.count(12, limit=65536)):
        _fname(r, pkg.names); r.i32()
    for i, b in enumerate(bones):
        if not -1 <= b["parent"] < i:
            raise AssetError(f"bone {b['name']}: parent {b['parent']} is not an earlier bone")
    return bones


def skeleton_from_export(pkg: Package, body: bytes, flags: int) -> list[dict]:
    """USkeleton export -> reference skeleton (tagged properties, object guid, FReferenceSkeleton)."""
    if pkg.unversioned_properties:
        raise MeshUnsupported("package uses unversioned property serialization; cannot reach the reference skeleton")
    r = Reader(body, what="Skeleton export")
    _object_header(r, pkg, flags)
    return read_ref_skeleton(r, pkg)


def _bulk_array(r: Reader, dtype, what: str, components: int = 1) -> np.ndarray:
    """TArray::BulkSerialize: int32 element size, int32 count, raw data (element = `components` x dtype)."""
    esize, count = r.i32(), r.i32()
    want = np.dtype(dtype).itemsize * components
    if count < 0 or esize < 0 or (count and esize != want):
        raise AssetError(f"{what}: element size {esize} (expected {want}), count {count}")
    raw = r.take(esize * count)
    a = np.frombuffer(raw, dtype)
    return a.reshape(-1, components) if components > 1 else a


def _bulk_bytes(r: Reader, what: str) -> tuple[int, int, bytes]:
    esize, count = r.i32(), r.i32()
    if count < 0 or esize <= 0 and count:
        raise AssetError(f"{what}: bulk array {esize} x {count}")
    return esize, count, r.take(esize * count)


def _read_bulk_data(r: Reader, pkg: Package, uasset: bytes, uexp: bytes, ubulk: bytes | None) -> bytes:
    """FByteBulkData (UE4): header, then the payload inline, at the end of the package, or in the .ubulk."""
    flags = r.u32()
    big = flags & BULK_SIZE64
    count = r.i64() if big else r.i32()
    size = r.i64() if big else r.u32()
    offset = r.i64()
    if flags & BULK_BAD_DATA_VERSION:
        r.u16()
    if flags & BULK_DUPLICATE_NON_OPTIONAL:
        r.u32(); r.take(8 if big else 4); r.i64()
    if flags & BULK_UNUSED or size == 0:
        return b""
    if flags & BULK_ZLIB:
        raise MeshUnsupported("zlib-compressed bulk payload inside the package is not supported")
    if flags & BULK_OPTIONAL:
        raise MeshUnsupported("LOD payload is in an optional .uptnl file")
    if flags & BULK_FORCE_INLINE or not flags & (BULK_PAYLOAD_AT_END | BULK_SEPARATE_FILE):
        return r.take(size)
    fixup = 0 if flags & BULK_NO_OFFSET_FIXUP else pkg.summary.get("bulk_data_start_offset", 0)
    if flags & BULK_SEPARATE_FILE:
        if ubulk is None:
            raise MeshUnsupported("LOD payload is in the .ubulk file, which was not extracted with the asset")
        pos = offset if not fixup else offset + fixup - (len(uasset) + len(uexp))
        if len(ubulk) == size:
            pos = 0
        if not 0 <= pos <= len(ubulk) - size:
            raise AssetError(f".ubulk payload {pos}+{size} outside {len(ubulk)} bytes")
        return ubulk[pos:pos + size]
    combined = uasset + uexp
    pos = offset + fixup
    if not 0 <= pos <= len(combined) - size:
        raise AssetError(f"end-of-file payload {pos}+{size} outside {len(combined)} bytes")
    return combined[pos:pos + size]


def _section(r: Reader, minor: int) -> dict:
    strip = _strip(r)
    s = {"material": r.i16(), "base_index": r.i32(), "triangles": r.i32()}
    r.bool32()                                   # bRecomputeTangent
    if minor >= 26:
        r.u8()                                   # RecomputeTangentsVertexMaskChannel
    r.bool32()                                   # bCastShadow
    s["base_vertex"] = r.u32()
    r.take(64 * r.count(64))                     # ClothMappingData (FMeshToMeshVertData)
    s["bone_map"] = [r.u16() for _ in range(r.count(2, limit=65536))]
    s["vertices"], s["max_influences"] = r.i32(), r.i32()
    r.i16()                                      # CorrespondClothAssetIndex
    r.take(20)                                   # FClothingSectionData (guid + lod index)
    if not strip[1] & 1:                         # DuplicatedVerticesBuffer unless class-stripped
        r.take(4 * r.count(4))
        r.take(8 * r.count(8))
    s["disabled"] = r.bool32()
    if s["vertices"] < 0 or s["triangles"] < 0 or s["max_influences"] not in range(0, 13):
        raise AssetError(f"implausible section {s}")
    return s


def _streamed(r: Reader, minor: int) -> dict:
    """FSkeletalMeshLODRenderData::SerializeStreamedData up to the skin weights (all LOD0 needs)."""
    _strip(r)
    isize = r.u8()
    idx = _bulk_array(r, np.uint16 if isize == 2 else np.uint32, "index buffer")
    stride, nverts = r.i32(), r.i32()
    pos = _bulk_array(r, np.float32, "position buffer", 3) if stride == 12 else None
    if pos is None or len(pos) != nverts:
        raise AssetError(f"position buffer stride {stride} / {nverts} vertices")
    _strip(r)
    ntex, nv2 = r.i32(), r.i32()
    full_uv, hi_tan = r.bool32(), r.bool32()
    if nv2 != nverts or not 1 <= ntex <= 8:
        raise AssetError(f"static mesh vertex buffer: {nv2} vertices / {ntex} UV sets")
    esize, count, raw = _bulk_bytes(r, "tangents")
    if count != nverts or esize != (16 if hi_tan else 8):
        raise AssetError(f"tangent buffer {esize} x {count}")
    if hi_tan:
        t = (np.frombuffer(raw, "<u2").reshape(-1, 2, 4) ^ 0x8000).astype(np.float32)
        nrm = (t[:, 1, :3] - 32767.5) / 32767.5
    else:
        t = (np.frombuffer(raw, np.uint8).reshape(-1, 2, 4) ^ 0x80).astype(np.float32)
        nrm = t[:, 1, :3] / 127.5 - 1.0
    esize, count, raw = _bulk_bytes(r, "texcoords")
    per = 8 if full_uv else 4
    if esize != per or count < nverts * ntex:
        raise AssetError(f"texcoord buffer {esize} x {count} for {nverts} x {ntex}")
    uv = np.frombuffer(raw, np.float32 if full_uv else np.float16)[:nverts * ntex * 2].reshape(nverts, ntex, 2)
    uv0 = uv[:, 0, :].astype(np.float32)
    # FSkinWeightVertexBuffer
    if minor >= 25:
        _strip(r)
        variable, max_inf, _nbones, nv3 = r.bool32(), r.u32(), r.u32(), r.u32()
        bone16 = r.bool32()
        _e, _c, data = _bulk_bytes(r, "skin weights")
        _strip(r)
        r.i32()
        lookup = _bulk_array(r, np.uint32, "skin weight lookup")
    else:
        _strip(r)
        extra = r.bool32()
        r.u32()                                  # stride
        nv3 = r.u32()
        max_inf, bone16, variable, lookup = (8 if extra else 4), False, False, None
        _e, _c, data = _bulk_bytes(r, "skin weights")
    if nv3 != nverts or not 1 <= max_inf <= 12:
        raise AssetError(f"skin weight buffer: {nv3} vertices, {max_inf} influences")
    ib = 2 if bone16 else 1
    joints = np.zeros((nverts, max_inf), np.uint16)
    weights = np.zeros((nverts, max_inf), np.float32)
    buf = np.frombuffer(data, np.uint8)
    if variable:
        if lookup is None or len(lookup) != nverts:
            raise AssetError("variable bones per vertex without a matching lookup table")
        for i, lv in enumerate(lookup):
            off, n = int(lv) >> 8, int(lv) & 0xFF
            if off + n * (ib + 1) > len(buf) or n > max_inf:
                raise AssetError(f"skin weight lookup {i} out of range")
            jj = buf[off:off + n * ib]
            joints[i, :n] = jj.view("<u2") if bone16 else jj
            weights[i, :n] = buf[off + n * ib:off + n * ib + n]
    else:
        stride_v = max_inf * (ib + 1)
        if len(buf) < nverts * stride_v:
            raise AssetError(f"skin weight data {len(buf)} bytes < {nverts} x {stride_v}")
        rows = buf[:nverts * stride_v].reshape(nverts, stride_v)
        joints[:] = rows[:, :max_inf * ib].copy().view("<u2") if bone16 else rows[:, :max_inf]
        weights[:] = rows[:, max_inf * ib:]
    return {"indices": idx.astype(np.uint32), "positions": pos, "normals": nrm, "uv": uv0, "uv_sets": ntex,
            "joints": joints, "weights": weights / 255.0, "max_influences": max_inf}


def parse_skeletal_mesh(pkg: Package, export_index: int, uasset: bytes, uexp: bytes | None, ubulk: bytes | None,
                        engine: tuple) -> dict:
    """LOD0 geometry + reference skeleton of one SkeletalMesh export."""
    blocker = mesh_support(engine, pkg)
    if blocker:
        raise MeshUnsupported(blocker)
    minor = engine[1]
    e = pkg.exports[export_index - 1]
    if e.class_name != "SkeletalMesh":
        raise AssetError(f"export {e.name} is a {e.class_name}, not a SkeletalMesh")
    r = Reader(export_body(pkg, e, uasset, uexp), what=f"SkeletalMesh {e.name}")
    props = _object_header(r, pkg, e.flags)
    has_colors = bool(props.get("bHasVertexColors", False))
    gstrip, _cstrip = _strip(r)
    if not gstrip & STRIP_EDITOR:
        raise MeshUnsupported("editor data is not stripped (uncooked/editor package)")
    bounds = [r.f32() for _ in range(7)]
    materials = []
    for _ in range(r.count(16, limit=4096)):
        mat = r.i32()
        slot = _fname(r, pkg.names)
        if minor >= 22 and r.bool32():
            _fname(r, pkg.names)
        r.take(24)                               # FMeshUVChannelInfo
        materials.append({"slot": slot, "material": pkg.path_of(mat) if mat else None})
    bones = read_ref_skeleton(r, pkg)
    if not r.bool32():
        raise MeshUnsupported("render data was not cooked into this package (bCooked = false)")
    nlods = r.count(8, limit=64)
    if nlods < 1:
        raise AssetError("no LODs")
    gs, cs = _strip(r)
    cooked_out, inlined = r.bool32(), r.bool32()
    r.take(2 * r.count(2, limit=65536))          # RequiredBones
    if gs & STRIP_AUDIOVISUAL or cooked_out:
        raise MeshUnsupported("LOD0 render data is stripped or cooked out of this build")
    sections = [_section(r, minor) for _ in range(r.count(40, limit=4096))]
    r.take(2 * r.count(2, limit=65536))          # ActiveBoneIndices
    r.u32()                                      # buffers size
    if inlined:
        lod = _streamed(r, minor)
    else:
        data = _read_bulk_data(r, pkg, uasset, uexp or b"", ubulk)
        if not data:
            raise MeshUnsupported("LOD0 is streamed but its bulk payload is empty")
        lod = _streamed(Reader(data, what="LOD0 streamed data"), minor)
    nverts = len(lod["positions"])
    # Section-local bone indices -> reference skeleton indices.
    joints = lod["joints"].astype(np.int64)
    for s in sections:
        a, b = s["base_vertex"], s["base_vertex"] + s["vertices"]
        if b > nverts:
            raise AssetError(f"section vertices {a}..{b} beyond {nverts}")
        bm = np.asarray(s["bone_map"] or [0], np.int64)
        local = joints[a:b]
        if local.size and local.max() >= len(bm):
            raise AssetError("skin weight bone index outside the section bone map")
        joints[a:b] = bm[local]
    if joints.size and joints.max() >= len(bones):
        raise AssetError("skin weight bone outside the reference skeleton")
    tris = []
    for s in sections:
        if s["disabled"]:
            continue
        seg = lod["indices"][s["base_index"]:s["base_index"] + 3 * s["triangles"]]
        if len(seg) != 3 * s["triangles"]:
            raise AssetError("section indices run past the index buffer")
        tris.append(seg)
    tris = np.concatenate(tris).reshape(-1, 3) if tris else np.zeros((0, 3), np.uint32)
    if tris.size and tris.max() >= nverts:
        raise AssetError("index outside the vertex buffer")
    return {"name": e.name, "bones": bones, "materials": materials, "sections": sections, "bounds": bounds,
            "has_vertex_colors": has_colors, "lods": nlods, "lod0_inlined": inlined,
            "positions": lod["positions"], "normals": lod["normals"], "uv": lod["uv"], "uv_sets": lod["uv_sets"],
            "joints": joints, "weights": lod["weights"], "max_influences": lod["max_influences"], "triangles": tris}


def _quat_matrix(q) -> np.ndarray:
    x, y, z, w = q
    n = x * x + y * y + z * z + w * w
    if n < 1e-12:
        return np.eye(3)
    s = 2.0 / n
    return np.array([[1 - s * (y * y + z * z), s * (x * y - z * w), s * (x * z + y * w)],
                     [s * (x * y + z * w), 1 - s * (x * x + z * z), s * (y * z - x * w)],
                     [s * (x * z - y * w), s * (y * z + x * w), 1 - s * (x * x + y * y)]])


def bone_world_matrices(bones: list[dict]) -> list[np.ndarray]:
    """glTF-space world matrices of the reference pose (UE local transforms composed down the hierarchy)."""
    world = []
    for b in bones:
        L = np.eye(4)
        R = UE_TO_GL @ _quat_matrix(b["rotation"]) @ UE_TO_GL
        S = np.diag(UE_TO_GL @ np.asarray(b["scale"], float))
        L[:3, :3] = R @ S
        L[:3, 3] = UE_TO_GL @ np.asarray(b["translation"], float) * CM_TO_M
        world.append(L if b["parent"] < 0 else world[b["parent"]] @ L)
    return world


def to_glb(mesh: dict, out: Path) -> Path:
    """Write the parsed mesh as a skinned GLB (4 strongest influences per vertex, renormalised)."""
    from .gta_rw import write_skinned_glb
    P = (mesh["positions"].astype(float) @ UE_TO_GL.T) * CM_TO_M
    N = mesh["normals"].astype(float) @ UE_TO_GL.T
    lens = np.linalg.norm(N, axis=1, keepdims=True)
    N = np.where(lens > 1e-6, N / np.maximum(lens, 1e-6), [0.0, 1.0, 0.0])
    J, W = mesh["joints"], mesh["weights"]
    order = np.argsort(-W, axis=1)[:, :4]
    J4 = np.take_along_axis(J, order, 1)
    W4 = np.take_along_axis(W, order, 1)
    if J4.shape[1] < 4:
        pad = 4 - J4.shape[1]
        J4 = np.pad(J4, ((0, 0), (0, pad)))
        W4 = np.pad(W4, ((0, 0), (0, pad)))
    tot = W4.sum(1, keepdims=True)
    W4 = np.where(tot > 0, W4 / np.where(tot > 0, tot, 1), [[1.0, 0, 0, 0]])
    bones = mesh["bones"] or [{"name": "root", "parent": -1, "rotation": [0, 0, 0, 1], "translation": [0, 0, 0],
                               "scale": [1, 1, 1]}]
    names = [b["name"] for b in bones]
    parents = [b["parent"] for b in bones]
    world = bone_world_matrices(bones)
    tris = mesh["triangles"].astype(np.uint32)
    return write_skinned_glb(Path(out), P, N, mesh["uv"], J4.astype(np.uint16), tris, names, parents, world,
                             name=mesh["name"], weights=W4.astype(np.float32))


def mesh_report(mesh: dict) -> dict:
    return {"name": mesh["name"], "vertices": int(len(mesh["positions"])), "triangles": int(len(mesh["triangles"])),
            "bones": len(mesh["bones"]), "sections": len(mesh["sections"]), "lods": mesh["lods"],
            "uv_sets": mesh["uv_sets"], "max_influences": mesh["max_influences"],
            "materials": mesh["materials"], "lod0_inlined": mesh["lod0_inlined"]}


__all__ = ["MeshUnsupported", "mesh_support", "parse_skeletal_mesh", "skeleton_from_export", "to_glb",
           "mesh_report", "read_tagged_properties", "PakError"]
