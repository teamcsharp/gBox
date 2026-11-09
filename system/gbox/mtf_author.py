"""Author a playable MT Framework model from decoded parts (Switch RE5/RE6/RE4).

The writer in `mt_model` can rebuild a container, but a model is only drawn when its 56-byte mesh table and the
144-byte per-bone envelope records after it agree with the vertex/index buffers. This module owns that agreement:

* `combine(ModFile)` reads every mesh it can decode, keeps each vertex's dominant bone and gives one triangle list;
* `build_one_mesh(ModFile, ...)` writes a one-mesh `MOD\\0` container that keeps the target's bones, groups, materials
  and bounding box, and emits an envelope record for every bone the mesh uses;
* `replace_archive_model(...)` puts it back in an `.arc` entry with a corrected tag.

The first consumer is RE5 Switch's whole-archive swap (`re5_char_swap`): the engine draws whatever a character archive
contains, so a one-mesh model written here can be dropped into a slot the loader accepts.
"""
from __future__ import annotations

import struct
import zlib
import math

from . import mt_arc, mt_model

# A one-bone vertex format whose layout is fully confirmed (position, bone id, normal, tangent, UV; stride 20). Keeping
# every vertex on its dominant bone preserves the bind pose and the skin's silhouette without needing a four-weight
# palette, and the game animates each vertex with that bone.
ONE_BONE_FORMAT = 0x18B0FAA8
ONE_BONE_STRIDE = 20


class AuthorError(ValueError):
    """The model cannot be authored from these bytes."""


def tangent_frames(vertices: list[dict], triangles: list[tuple[int, int, int]]) -> list[dict]:
    """Derive a UV tangent frame for each final authored vertex, with a stable degenerate-UV fallback.

    Normals and UV seams belong to the vertex identity supplied by the caller. Area-weighted UV derivatives are
    orthogonalized against each normal. Handedness is retained separately for the native tangent's fourth byte.
    """
    import numpy as np
    points = np.asarray([v['position'] for v in vertices], float)
    uvs = np.asarray([v.get('uv', (0., 0.)) for v in vertices], float)
    if points.shape != (len(vertices), 3) or uvs.shape != (len(vertices), 2) or not np.isfinite(points).all() or not np.isfinite(uvs).all():
        raise AuthorError('tangent frames require finite positions and two-component UVs')
    tangent, bitangent = np.zeros_like(points), np.zeros_like(points)
    for face in triangles:
        if len(face) != 3 or any(not isinstance(i, int) or not 0 <= i < len(vertices) for i in face):
            raise AuthorError('source triangles must address three source vertices')
        a,b,c = face
        e1,e2 = points[b]-points[a],points[c]-points[a]
        du1,du2 = uvs[b]-uvs[a],uvs[c]-uvs[a]
        determinant = du1[0]*du2[1]-du1[1]*du2[0]
        area = np.linalg.norm(np.cross(e1,e2))
        if abs(determinant) < 1e-12 or area < 1e-12:
            continue
        t = (e1*du2[1]-e2*du1[1])*(area/determinant)
        bvec = (e2*du1[0]-e1*du2[0])*(area/determinant)
        for i in face:
            tangent[i] += t
            bitangent[i] += bvec
    output = []
    for i, vertex in enumerate(vertices):
        normal = np.array(vertex.get('normal', (0.,1.,0.)), dtype=float, copy=True)
        if normal.shape != (3,) or not np.isfinite(normal).all() or np.linalg.norm(normal) < 1e-12:
            raise AuthorError('tangent frames require a finite nonzero normal')
        normal /= np.linalg.norm(normal)
        t = tangent[i]-normal*np.dot(normal,tangent[i])
        if np.linalg.norm(t) < 1e-12:
            axis = np.eye(3)[int(np.argmin(np.abs(normal)))]
            t = axis-normal*np.dot(axis,normal)
        t /= np.linalg.norm(t)
        sign = -1. if np.dot(np.cross(normal,t),bitangent[i]) < 0 else 1.
        output.append(vertex | {'normal':tuple(map(float,normal)), 'tangent':tuple(map(float,t)),
                                'tangent_sign':sign, 'occlusion':vertex.get('occlusion',1.)})
    return output


def replace_topology(model: mt_model.ModFile, vertices: list[dict], triangles: list[tuple[int, int, int]],
                     *, lod: int = 0) -> tuple[bytes, dict]:
    """Experimental geometry import inside the target's original vertex and index allocations.

    Keep the entire part table, materials, bounds, skin bytes and other LODs. Triangle strips use only each part's
    original index range; spare words become restart markers. Fail before returning bytes if the complete source
    cannot fit. This establishes container safety, not proof that a title renders the imported silhouette.
    """
    if not vertices or not triangles:
        raise AuthorError("a topology import needs vertices and triangles")
    bounds = model.bounds()
    if not bounds or model.variant != "model":
        raise AuthorError("a topology import needs a model with bounds")
    for vertex in vertices:
        position = vertex.get("position", ())
        if len(position) != 3 or not all(math.isfinite(float(v)) for v in position):
            raise AuthorError("source positions must be finite three-component vectors")
        if any(not bounds["min"][axis] <= position[i] <= bounds["max"][axis] for i, axis in enumerate("xyz")):
            raise AuthorError("fit the source positions inside the target bounds before importing")
    for tri in triangles:
        if len(tri) != 3 or any(not isinstance(v, int) or not 0 <= v < len(vertices) for v in tri):
            raise AuthorError("source triangles must address three source vertices")
    header = model.header()
    offsets = header["offsets"]
    records = model.meshes()
    # Unknown components stay in the base bytes; only formats with confirmed positions can carry source geometry.
    formats = {fmt: stride for fmt, stride in mt_model.MOD_FVF_STRIDES.items()
               if fmt in mt_model.MOD_SHORT_POSITION | mt_model.MOD_FLOAT_POSITION}
    parts = []
    ranges = []
    for index, record in enumerate(records):
        start = offsets["index_buffer"] + 2 * record["face_index"]
        end = start + 2 * (record["face_count"] + 1)
        vstart = offsets["vertex_buffer"] + record["vertex_offset"] + record["vertex_index"] * record["vertex_stride"]
        vend = vstart + record["vertex_count"] * record["vertex_stride"]
        ranges.append((start, end, vstart, vend))
        if not record["level_of_detail"] & (1 << lod):
            continue
        if record["vertex_count"] < 3 or record["face_count"] < 3:
            continue
        if formats.get(record["vertex_format"]) != record["vertex_stride"]:
            raise AuthorError(f"LOD {lod} part {index} has an unsupported vertex layout")
        if not offsets["index_buffer"] <= start < end <= offsets["end"]:
            raise AuthorError(f"part {index}'s index allocation runs outside the index buffer")
        if not offsets["vertex_buffer"] <= vstart < vend <= offsets["index_buffer"]:
            raise AuthorError(f"part {index}'s vertex allocation runs outside the vertex buffer")
        if record["vertex_index"] + record["vertex_count"] > 0xFFFF:
            raise AuthorError(f"part {index}'s indices would collide with the strip restart marker")
        parts.append(index)
    if not parts:
        raise AuthorError(f"no supported triangle parts at LOD {lod}")
    # Shared buffer bases are expected; overlapping actual vertex/index ranges are not safe to rewrite independently.
    for index in parts:
        a, b, va, vb = ranges[index]
        for other, (c, d, vc, vd) in enumerate(ranges):
            if other == index:
                continue
            if max(a, c) < min(b, d) or max(va, vc) < min(vb, vd):
                raise AuthorError(f"part {index}'s allocation overlaps part {other}")
    local = {i: [] for i in parts}
    lookup = {i: {} for i in parts}
    assigned = {i: [] for i in parts}
    cursor = 0
    for number, tri in enumerate(triangles):
        for step in range(len(parts)):
            pi = parts[(cursor + step) % len(parts)]
            record = records[pi]
            needed = set(tri) - lookup[pi].keys()
            if (len(local[pi]) + len(needed) > record["vertex_count"]
                    or 4 * (len(assigned[pi]) + 1) > record["face_count"] + 1):
                continue
            for vertex in tri:
                if vertex not in lookup[pi]:
                    lookup[pi][vertex] = len(local[pi])
                    local[pi].append(vertex)
            assigned[pi].append(tuple(lookup[pi][v] + record["vertex_index"] for v in tri))
            cursor = (cursor + step + 1) % len(parts)
            break
        else:
            raise AuthorError(f"source triangle {number + 1}/{len(triangles)} exceeds the target's vertex/index capacity")
    out = bytearray(model.raw)
    for pi in parts:
        record = records[pi]
        start, end, vstart, vend = ranges[pi]
        # The source's bones and weights deliberately do not enter this path: keep the target's skin bindings.
        updates = [{key: vertices[v][key] for key in ("position", "normal", "uv") if key in vertices[v]}
                   | {"bounds": bounds} for v in local[pi]]
        packed = mt_model.pack_vertices(updates, record["vertex_format"], record["vertex_stride"],
                                        base=model.raw[vstart:vend], position_transform=model.position_transform())
        out[vstart:vstart + len(packed)] = packed
        indices = b"".join(struct.pack("<4H", *tri, 0xFFFF) for tri in assigned[pi])
        out[start:end] = indices + b"\xff" * (end - start - len(indices))
    result = bytes(out)
    if len(result) != len(model.raw) or not mt_model.parse_mod(result).split_valid():
        raise AuthorError("the imported model no longer describes its original allocations")
    return result, {"lod": lod, "parts": len(parts), "parts_used": sum(bool(v) for v in assigned.values()),
                    "source_vertices": len(vertices), "triangles": len(triangles), "dropped_triangles": 0,
                    "skin": "original target bindings", "live_verified": False}


def mesh_triangles(model: mt_model.ModFile, index: int) -> list[tuple[int, int, int]]:
    """One mesh's triangle list, from its own index range and strip stream."""
    header = model.header()
    meshes = model.meshes()
    if not 0 <= index < len(meshes):
        raise AuthorError(f"no mesh {index}")
    record = meshes[index]
    start = header["offsets"]["index_buffer"] + 2 * record["face_index"]
    end = start + 2 * record["face_count"]
    if end > len(model.raw):
        raise AuthorError(f"mesh {index}'s index range runs past the model")
    data = model.raw[start:end]
    values = struct.unpack_from(f"<{len(data) // 2}H", data, 0)
    strips: list[list[int]] = []
    current: list[int] = []
    for value in values:
        if value == 0xFFFF:
            if len(current) >= 3:
                strips.append(current)
            current = []
        else:
            current.append(value)
    if len(current) >= 3:
        strips.append(current)
    out: list[tuple[int, int, int]] = []
    for strip in strips:
        for k in range(len(strip) - 2):
            a, b, c = strip[k], strip[k + 1], strip[k + 2]
            if k % 2:
                a, b = b, a
            if a == b or b == c or a == c:
                continue
            out.append((a, b, c))
    return out


def combine(model: mt_model.ModFile, *, material_index: int | None = None) -> dict:
    """Every decodable mesh in the model as one vertex list, triangle list and material.

    A mesh whose position format is not decoded by `mt_model.positions` is skipped, not guessed at: a skipped part
    leaves a hole, while a guessed part corrupts the whole buffer. The chosen material defaults to the material of the
    largest mesh that contributed geometry.
    """
    bounds = model.bounds()
    if not bounds:
        raise AuthorError("the target model carries no bounding box")
    vertices: list[dict] = []
    triangles: list[tuple[int, int, int]] = []
    used_bones: set[int] = set()
    largest = 0
    material = 0 if material_index is None else int(material_index)
    for index, record in enumerate(model.meshes()):
        points = model.positions(index)
        if len(points) != record["vertex_count"] or not points:
            continue
        normals = model.normals(index) or [(0.0, 1.0, 0.0)] * len(points)
        uvs = model.uvs(index) or [(0.0, 0.0)] * len(points)
        bones = model.bone_ids(index) or [(0,)] * len(points)
        tris = mesh_triangles(model, index)
        if not tris:
            continue
        base = len(vertices)
        if len(points) > largest:
            largest = len(points)
            if material_index is None:
                material = record["material_index"]
        for point, normal, uv, bone in zip(points, normals, uvs, bones):
            bone_id = int(bone[0]) if bone else 0
            used_bones.add(bone_id)
            vertices.append({"position": point, "normal": normal, "uv": uv, "bones": [bone_id],
                             "bounds": bounds, "bone": bone_id})
        # The index stream is global to the shared vertex buffer: a part's first vertex is record["vertex_index"], not
        # zero. Normalise before adding this part's base or a shared-buffer model gets indices past the vertex list.
        shift = int(record.get("vertex_index") or 0)
        triangles.extend((a - shift + base, b - shift + base, c - shift + base) for a, b, c in tris)
    if not vertices or not triangles:
        raise AuthorError("no mesh of this model could be decoded")
    return {"vertices": vertices, "triangles": triangles, "material": int(material),
            "used_bones": sorted(used_bones), "source_meshes": len({v["bone"] for v in vertices})}


def pack_weight_bound(bone: int, points: list[tuple[float, float, float]]) -> bytes:
    """One 144-byte envelope record around `points`, in the model's own space."""
    if not points:
        raise AuthorError("a weight bound needs at least one point")
    low = [min(p[axis] for p in points) for axis in range(3)]
    high = [max(p[axis] for p in points) for axis in range(3)]
    centre = [(low[axis] + high[axis]) / 2 for axis in range(3)]
    extent = [(high[axis] - low[axis]) / 2 for axis in range(3)]
    radius = max(sum((p[axis] - centre[axis]) ** 2 for axis in range(3)) ** 0.5 for p in points)
    out = bytearray(mt_model.MOD_WEIGHT_BOUND)
    struct.pack_into("<I", out, 0, int(bone) & 0xFFFFFFFF)
    struct.pack_into("<4f", out, 16, *centre, radius)
    struct.pack_into("<3f", out, 32, *low)
    struct.pack_into("<f", out, 44, 0.0)
    struct.pack_into("<3f", out, 48, *high)
    struct.pack_into("<f", out, 60, 0.0)
    struct.pack_into("<16f", out, 64, 1.0, 0.0, 0.0, 0.0,
                     0.0, 1.0, 0.0, 0.0,
                     0.0, 0.0, 1.0, 0.0,
                     *centre, 1.0)
    struct.pack_into("<3f", out, 128, *extent)
    struct.pack_into("<f", out, 140, 0.0)
    return bytes(out)


def bone_local_points(model: mt_model.ModFile, bone: int, points) -> list[tuple[float, float, float]]:
    """Envelope points are in the referenced bone's bind frame, not model coordinates."""
    world = model.bone_world_matrices()
    if not 0 <= bone < len(world):
        raise AuthorError(f"envelope bone {bone} is absent from the target skeleton")
    try:
        inverse = mt_model._inverse_matrix(world[bone])
    except mt_model.ModelError:
        # Keep legacy zero-matrix synthetic fixtures usable; real skeleton transforms must be invertible.
        if model.position_transform() is None and not any(world[bone]):
            return list(points)
        raise AuthorError(f"envelope bone {bone} has no invertible bind transform")
    return [mt_model._transform_point(point, inverse) for point in points]


def build_one_mesh(model: mt_model.ModFile, vertices: list[dict], triangles: list[tuple[int, int, int]],
                   *, material_index: int = 0, template_index: int = 0, mesh_count: int | None = None,
                   four_weights: bool = False) -> bytes:
    """A one-mesh copy of `model`: its skeleton, groups, materials and bounds, with new geometry.

    The mesh record is based on the target's `template_index` record so fields this writer does not name keep the
    values the engine already accepted; the fields that describe the new geometry are overwritten.
    """
    if not vertices or not triangles:
        raise AuthorError("an authored model needs vertices and triangles")
    highest = max(max(triangle) for triangle in triangles)
    if highest >= len(vertices):
        raise AuthorError(f"triangle index {highest} is past the {len(vertices)} vertices")
    records = model.meshes()
    if not 0 <= template_index < len(records):
        raise AuthorError(f"no template mesh {template_index}")
    bounds = model.bounds()
    if not bounds:
        raise AuthorError("the target model carries no bounding box")
    vertex_format, stride = (0x2000D414, 28) if four_weights else (ONE_BONE_FORMAT, ONE_BONE_STRIDE)
    # The generic `weights` decoder predates the shader's first short weight. Encode the complete native four-weight
    # layout explicitly: w0 SNORM16@6, joint bytes@16, w1/w2 half@24, w3 is the remainder. No palette is rewritten.
    packed_vertices = tangent_frames(vertices, triangles)
    influences = []
    for vertex in packed_vertices:
        if four_weights:
            bones, weights = list(vertex.get("bones", [])), list(vertex.get("weights", []))
            if not 1 <= len(bones) <= 4 or len(bones) != len(weights):
                raise AuthorError("four-weight vertices need one to four matching bones and weights")
            if (any(not isinstance(b, int) or not 0 <= b < model.header()["bone_count"] or b > 255 for b in bones)
                    or any(not math.isfinite(w) or w < 0 for w in weights) or abs(sum(weights) - 1.) > 1e-6):
                raise AuthorError("four-weight skin bindings must be normalized and address existing target bones")
            merged = {}
            for bone, weight in zip(bones, weights):
                if weight > 0:
                    merged[bone] = merged.get(bone, 0.) + weight
            pairs = sorted(merged.items(), key=lambda pair: (-pair[1], pair[0]))
            bones, weights = [b for b, _ in pairs], [w for _, w in pairs]
            bones += [0] * (4 - len(bones))
            weights += [0.] * (4 - len(weights))
            vertex["bones"], vertex["weights"] = bones, weights[1:3]
            influences.append(list(zip(bones, weights)))
        else:
            bone = int((vertex.get("bones") or [vertex.get("bone", 0)])[0])
            if not 0 <= bone < model.header()["bone_count"]:
                raise AuthorError("one-weight skin bindings must address an existing target bone")
            vertex["bones"] = [bone]
            influences.append([(bone, 1.)])
    vertex_buffer = bytearray(mt_model.pack_vertices(packed_vertices, vertex_format, stride,
                                          position_transform=model.position_transform())
                             )
    if four_weights:
        for i, weights in enumerate(influences):
            half_weights = struct.unpack_from("<2e", vertex_buffer, i * stride + 24)
            # The last weight is implicit; rounding the stored components must never make it negative.
            first = min(round(weights[0][1] * 32767), math.floor(max(0., 1. - sum(half_weights)) * 32767))
            struct.pack_into("<h", vertex_buffer, i * stride + 6, first)
    index_buffer = bytearray()
    for a, b, c in triangles:
        index_buffer += struct.pack("<4H", a, b, c, 0xFFFF)
    # The last 0xFFFF is the separator the header counts but the record's face_count does not; that is the measured
    # rule on every model: sum(mesh.face_count) + mesh_count == header.face_count.
    index_count = len(index_buffer) // 2
    by_bone: dict[int, list[tuple[float, float, float]]] = {}
    for vertex, weights in zip(vertices, influences):
        for bone, weight in weights:
            if weight > 0:
                by_bone.setdefault(bone, []).append(tuple(vertex["position"]))
    trailer = b"".join(pack_weight_bound(bone, bone_local_points(model, bone, points))
                       for bone, points in sorted(by_bone.items()))
    record = dict(records[template_index])
    record.update({"mesh_type": 0xFFFF, "vertex_count": len(vertices), "material_index": int(material_index),
                   "level_of_detail": 0xFF, "group_index": record.get("group_index", 0), "mesh_class": 0,
                   "vertex_flags": 33 if four_weights else 9,
                   "vertex_stride": stride, "render_mode": 4, "vertex_index": 0, "vertex_offset": 0,
                   "vertex_format": vertex_format, "face_index": 0, "face_count": index_count - 1,
                   "face_offset": 0, "bone_map_index": 0, "vertex_group_count": len(by_bone),
                   "min_index": 0, "max_index": len(vertices) - 1})
    count = max(1, int(mesh_count or 1))
    records_out = [record]
    if count > 1:
        # Keep the slot's original mesh count (and therefore its MRL shape) but make every extra record empty. This is a
        # probe: the first record draws the new geometry; the others account for the MRL's part count without vertices.
        empty = dict(record)
        empty.update({"vertex_count": 0, "face_count": 0, "vertex_group_count": 0, "vertex_index": 0,
                      "vertex_offset": len(vertex_buffer), "face_index": index_count, "face_offset": 0,
                      "min_index": 0, "max_index": 0, "level_of_detail": 0xFF, "mesh_class": 0})
        used_ids = {record.get("mesh_id", 0)}
        for i in range(count - 1):
            candidate_id = next(value for value in range(0x10000) if value not in used_ids)
            used_ids.add(candidate_id)
            records_out.append(empty | {"mesh_id": candidate_id})
    return mt_model.rebuild_mod(model, vertex_buffer=vertex_buffer, index_buffer=bytes(index_buffer),
                                mesh_records=records_out, mesh_count=count, vertex_count=len(vertices),
                                face_count=index_count + count - 1, edge_count=len(triangles), bounds=bounds, mesh_trailer=trailer)


def build_partitioned(model: mt_model.ModFile, vertices: list[dict], triangles: list[tuple[int, int, int]],
                      *, part_count: int, material_index: int = 0, template_index: int = 0) -> bytes:
    """The same geometry split across `part_count` real records.

    The low Majini slot's MRL describes 341 parts; an empty padded table boots but the round load rejects it. This
    variant gives every record actual vertices/triangles (round-robin), so the part count, the header's vertex/face
    counts and the envelope table are all consistent without a zero-vertex record.
    """
    if not vertices or not triangles:
        raise AuthorError("a partitioned model needs vertices and triangles")
    vertices = tangent_frames(vertices, triangles)
    count = max(1, int(part_count))
    records_in = model.meshes()
    if not 0 <= template_index < len(records_in):
        raise AuthorError(f"no template mesh {template_index}")
    bounds = model.bounds()
    if not bounds:
        raise AuthorError("the target model carries no bounding box")
    groups: list[list[tuple[int, int, int]]] = [[] for _ in range(count)]
    for i, tri in enumerate(triangles):
        groups[i % count].append(tri)
    vertex_buffer = bytearray()
    index_buffer = bytearray()
    trailer = bytearray()
    records: list[dict] = []
    face_index = 0
    vertex_index = 0
    used_ids = set()
    for part_number, group in enumerate(groups):
        ids = sorted({int(v) for tri in group for v in tri})
        local = {old: new for new, old in enumerate(ids)}
        if not ids:
            # Every part must be real for this probe; repeat vertex 0 and skip its triangles rather than emit an empty
            # record (the empty form is what the low loader rejected).
            ids = [0]
            local = {0: 0}
            group = []
        part_vertices = [vertices[i] for i in ids]
        packed = mt_model.pack_vertices(part_vertices, ONE_BONE_FORMAT, ONE_BONE_STRIDE,
                                       position_transform=model.position_transform())
        part_indices = bytearray()
        for tri in group:
            a, b, c = (local[int(v)] for v in tri)
            part_indices += struct.pack("<4H", a, b, c, 0xFFFF)
        by_bone = {}
        for vertex, ids in zip(part_vertices, mt_model.decode_bone_ids(packed, ONE_BONE_FORMAT, len(part_vertices), ONE_BONE_STRIDE)):
            bone = ids[0]
            by_bone.setdefault(bone, []).append(tuple(vertex["position"]))
        for bone, points in sorted(by_bone.items()):
            trailer += pack_weight_bound(bone, bone_local_points(model, bone, points))
        record = dict(records_in[template_index])
        preferred_id = records_in[part_number].get("mesh_id", part_number) if part_number < len(records_in) else part_number
        if preferred_id in used_ids:
            preferred_id = next(value for value in range(0x10000) if value not in used_ids)
        used_ids.add(preferred_id)
        record.update({"mesh_type": 0xFFFF, "vertex_count": len(part_vertices),
                       "mesh_id": preferred_id,
                       "material_index": int(material_index), "level_of_detail": 0xFF, "vertex_flags": 9,
                       "group_index": record.get("group_index", 0), "mesh_class": 0,
                       "vertex_stride": ONE_BONE_STRIDE, "render_mode": 4, "vertex_index": 0,
                       "vertex_offset": len(vertex_buffer), "vertex_format": ONE_BONE_FORMAT,
                       "face_index": face_index, "face_count": max(0, len(part_indices) // 2 - 1),
                       "face_offset": 0, "bone_map_index": 0, "vertex_group_count": len(by_bone),
                       "min_index": 0, "max_index": len(part_vertices) - 1})
        records.append(record)
        vertex_buffer += packed
        index_buffer += part_indices
        vertex_index += len(part_vertices)
        face_index += len(part_indices) // 2
    return mt_model.rebuild_mod(model, vertex_buffer=bytes(vertex_buffer), index_buffer=bytes(index_buffer),
                                mesh_records=records, mesh_count=count, vertex_count=vertex_index,
                                face_count=len(index_buffer) // 2, edge_count=len(triangles), bounds=bounds,
                                mesh_trailer=trailer)


def replace_archive_model(archive: bytes, entry_index: int, model: bytes) -> bytes:
    """Put `model` into one entry of an MTF `.arc`, updating the tag's uncompressed length."""
    arc = mt_arc.parse(archive)
    if not 0 <= entry_index < len(arc.entries):
        raise AuthorError(f"entry {entry_index} is outside the archive")
    entry = arc.entries[entry_index]
    tag = (entry.tag & 0xFF000000) | len(model)
    # Shipped Switch entries have a zlib header/checksum. Stripping them creates a different stream format and can
    # stall the loader even though the uncompressed MOD is valid. Preserve raw framing only for an existing raw entry.
    wrapped = True
    try:
        zlib.decompress(entry.data)
    except zlib.error:
        try:
            zlib.decompress(entry.data, -zlib.MAX_WBITS)
            wrapped = False
        except zlib.error:
            pass
    payload = zlib.compress(model, 6)
    return mt_arc.replace_at(archive, entry_index, payload if wrapped else payload[2:-4], tag=tag)


def build_archive(source_archive: bytes, model: bytes, entry_index: int) -> bytes:
    """The archive with one model entry replaced by an authored one."""
    return replace_archive_model(source_archive, entry_index, model)

