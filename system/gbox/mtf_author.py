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

from . import mt_arc, mt_model

# A one-bone vertex format whose layout is fully confirmed (position, bone id, normal, tangent, UV; stride 20). Keeping
# every vertex on its dominant bone preserves the bind pose and the skin's silhouette without needing a four-weight
# palette, and the game animates each vertex with that bone.
ONE_BONE_FORMAT = 0x18B0FAA8
ONE_BONE_STRIDE = 20


class AuthorError(ValueError):
    """The model cannot be authored from these bytes."""


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


def build_one_mesh(model: mt_model.ModFile, vertices: list[dict], triangles: list[tuple[int, int, int]],
                   *, material_index: int = 0, template_index: int = 0, mesh_count: int | None = None) -> bytes:
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
    vertex_buffer = mt_model.pack_vertices(vertices, ONE_BONE_FORMAT, ONE_BONE_STRIDE)
    index_buffer = bytearray()
    for a, b, c in triangles:
        index_buffer += struct.pack("<4H", a, b, c, 0xFFFF)
    # The last 0xFFFF is the separator the header counts but the record's face_count does not; that is the measured
    # rule on every model: sum(mesh.face_count) + mesh_count == header.face_count.
    index_count = len(index_buffer) // 2
    by_bone: dict[int, list[tuple[float, float, float]]] = {}
    for vertex in vertices:
        by_bone.setdefault(int(vertex.get("bone", 0)), []).append(tuple(vertex["position"]))
    trailer = b"".join(pack_weight_bound(bone, points) for bone, points in sorted(by_bone.items()))
    record = dict(records[template_index])
    record.update({"mesh_type": 0xFFFF, "vertex_count": len(vertices), "material_index": int(material_index),
                   "level_of_detail": 0, "group_index": record.get("group_index", 0), "mesh_class": 0,
                   "vertex_stride": ONE_BONE_STRIDE, "render_mode": 4, "vertex_index": 0, "vertex_offset": 0,
                   "vertex_format": ONE_BONE_FORMAT, "face_index": 0, "face_count": index_count - 1,
                   "face_offset": 0, "bone_map_index": 0, "vertex_group_count": len(by_bone),
                   "min_index": 0, "max_index": len(vertices) - 1})
    count = max(1, int(mesh_count or 1))
    records_out = [record]
    if count > 1:
        # Keep the slot's original mesh count (and therefore its MRL shape) but make every extra record empty. This is a
        # probe: the first record draws the new geometry; the others account for the MRL's part count without vertices.
        empty = dict(record)
        empty.update({"vertex_count": 0, "face_count": 0, "vertex_group_count": 0, "vertex_index": len(vertices),
                      "vertex_offset": len(vertex_buffer), "face_index": index_count, "face_offset": 0,
                      "min_index": 0, "max_index": 0, "level_of_detail": 0, "mesh_class": 0})
        records_out += [empty] * (count - 1)
    return mt_model.rebuild_mod(model, vertex_buffer=vertex_buffer, index_buffer=bytes(index_buffer),
                                mesh_records=records_out, mesh_count=count, vertex_count=len(vertices),
                                face_count=index_count + count - 1, edge_count=0, bounds=bounds, mesh_trailer=trailer)


def build_partitioned(model: mt_model.ModFile, vertices: list[dict], triangles: list[tuple[int, int, int]],
                      *, part_count: int, material_index: int = 0, template_index: int = 0) -> bytes:
    """The same geometry split across `part_count` real records.

    The low Majini slot's MRL describes 341 parts; an empty padded table boots but the round load rejects it. This
    variant gives every record actual vertices/triangles (round-robin), so the part count, the header's vertex/face
    counts and the envelope table are all consistent without a zero-vertex record.
    """
    if not vertices or not triangles:
        raise AuthorError("a partitioned model needs vertices and triangles")
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
    for group in groups:
        ids = sorted({int(v) for tri in group for v in tri})
        local = {old: new for new, old in enumerate(ids)}
        if not ids:
            # Every part must be real for this probe; repeat vertex 0 and skip its triangles rather than emit an empty
            # record (the empty form is what the low loader rejected).
            ids = [0]
            local = {0: 0}
            group = []
        part_vertices = [vertices[i] for i in ids]
        packed = mt_model.pack_vertices(part_vertices, ONE_BONE_FORMAT, ONE_BONE_STRIDE)
        part_indices = bytearray()
        for tri in group:
            a, b, c = (local[int(v)] for v in tri)
            part_indices += struct.pack("<4H", a, b, c, 0xFFFF)
        bone = int(part_vertices[0].get("bone", 0))
        points = [tuple(v["position"]) for v in part_vertices]
        trailer += pack_weight_bound(bone, points)
        record = dict(records_in[template_index])
        record.update({"mesh_type": 0xFFFF, "vertex_count": len(part_vertices),
                       "material_index": int(material_index), "level_of_detail": 0,
                       "group_index": record.get("group_index", 0), "mesh_class": 0,
                       "vertex_stride": ONE_BONE_STRIDE, "render_mode": 4, "vertex_index": vertex_index,
                       "vertex_offset": len(vertex_buffer), "vertex_format": ONE_BONE_FORMAT,
                       "face_index": face_index, "face_count": max(0, len(part_indices) // 2 - 1),
                       "face_offset": 0, "bone_map_index": 0, "vertex_group_count": 1,
                       "min_index": 0, "max_index": len(part_vertices) - 1})
        records.append(record)
        vertex_buffer += packed
        index_buffer += part_indices
        vertex_index += len(part_vertices)
        face_index += len(part_indices) // 2
    return mt_model.rebuild_mod(model, vertex_buffer=bytes(vertex_buffer), index_buffer=bytes(index_buffer),
                                mesh_records=records, mesh_count=count, vertex_count=vertex_index,
                                face_count=len(index_buffer) // 2, edge_count=0, bounds=bounds,
                                mesh_trailer=trailer)


def replace_archive_model(archive: bytes, entry_index: int, model: bytes) -> bytes:
    """Put `model` into one entry of an MTF `.arc`, updating the tag's uncompressed length."""
    arc = mt_arc.parse(archive)
    if not 0 <= entry_index < len(arc.entries):
        raise AuthorError(f"entry {entry_index} is outside the archive")
    entry = arc.entries[entry_index]
    tag = (entry.tag & 0xFF000000) | len(model)
    return mt_arc.replace_at(archive, entry_index, zlib.compress(model, 9)[2:-4], tag=tag)


def build_archive(source_archive: bytes, model: bytes, entry_index: int) -> bytes:
    """The archive with one model entry replaced by an authored one."""
    return replace_archive_model(source_archive, entry_index, model)
