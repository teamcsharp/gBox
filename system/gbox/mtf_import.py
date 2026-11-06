"""Write an arbitrary mesh into an MT Framework model: one part, my own vertex and index buffers.

This is what "put Sonic in the game" needs and what `replace_part` could not do: a model is 15 parts with an index buffer
that addresses all of them, so adding a mesh with its own topology means rebuilding the part table and the index stream, not
just one part's vertices.

The skeleton is the TARGET's, untouched: the source's joints are mapped onto the target's bones by `mtf_fit`, so the mesh
deforms with the animations the game already plays. Textures are not carried yet, so an imported mesh renders with the
target's material.

Measured on the real assets (2026-11-06): SA2 Sonic - 4107 vertices, 1369 triangles, POSITION/NORMAL/TEXCOORD_0/JOINTS_0/
WEIGHTS_0, 62 joints; RE5's uEm10 (a Majini the round spawns) is the target.
"""
from __future__ import annotations

import struct

from . import mt_model

# the vertex format the imported mesh is written in: position, one bone id, normal, tangent, uv (stride 20)
IMPORT_FORMAT = 0x18B0FAA8
IMPORT_STRIDE = 20


class ImportError_(ValueError):
    """The mesh cannot be written into that model."""


def _fit(points, source_box, target_box, *, keep_aspect: bool = True):
    """Scale and place the source mesh into the target's box: feet on the floor, centred, facing the same way."""
    (sx0, sy0, sz0), (sx1, sy1, sz1) = source_box
    (tx0, ty0, tz0), (tx1, ty1, tz1) = target_box
    source_h = max(sy1 - sy0, 1e-6)
    target_h = max(ty1 - ty0, 1e-6)
    scale = target_h / source_h
    if not keep_aspect:
        sx = (tx1 - tx0) / max(sx1 - sx0, 1e-6)
        sz = (tz1 - tz0) / max(sz1 - sz0, 1e-6)
    else:
        sx = sz = scale
    cx = (sx0 + sx1) / 2
    cz = (sz0 + sz1) / 2
    tx = (tx0 + tx1) / 2
    tz = (tz0 + tz1) / 2
    return [(tx + (x - cx) * sx, ty0 + (y - sy0) * scale, tz + (z - cz) * sz) for x, y, z in points]


def build_model(source_model: mt_model.ModFile, vertices: list[dict], triangles: list[tuple[int, int, int]],
                *, material_index: int = 0) -> bytes:
    """A copy of `source_model` whose geometry is one part: `vertices` packed in IMPORT_FORMAT, `triangles` as strips.

    Keeps the target's bones, groups, materials and header tail (bounds rewritten to cover the new mesh), so the model still
    belongs to the game's character and animates with it.
    """
    if not vertices or not triangles:
        raise ImportError_("an imported model needs vertices and triangles")
    highest = max(max(triangle) for triangle in triangles)
    if highest >= len(vertices):
        raise ImportError_(f"triangle index {highest} is past the {len(vertices)} vertices")
    points = [tuple(v["position"]) for v in vertices]
    low = tuple(min(p[i] for p in points) for i in range(3))
    high = tuple(max(p[i] for p in points) for i in range(3))
    bounds = {"sphere": {"x": (low[0] + high[0]) / 2, "y": (low[1] + high[1]) / 2, "z": (low[2] + high[2]) / 2,
                         "r": max(high[i] - low[i] for i in range(3)) / 2},
              "min": {"x": low[0], "y": low[1], "z": low[2]},
              "max": {"x": high[0], "y": high[1], "z": high[2]}}
    vertex_buffer = bytearray()
    for vertex in vertices:
        packed = bytearray(IMPORT_STRIDE)
        x, y, z = vertex["position"]
        values = []
        for axis, value in enumerate((x, y, z)):
            span = high[axis] - low[axis]
            scaled = 0.0 if not span else (value - low[axis]) / span
            values.append(max(0, min(32767, int(round(scaled * 32767.0)))))
        struct.pack_into("<3H", packed, 0, *values)
        bones = list(vertex.get("bones") or [0])[:1] or [0]
        struct.pack_into("<H", packed, 6, int(bones[0]) & 0xFFFF)
        nx, ny, nz = vertex.get("normal") or (0.0, 1.0, 0.0)
        struct.pack_into("<3b", packed, 8, max(-127, min(127, int(round(nx * 127)))),
                         max(-127, min(127, int(round(ny * 127)))), max(-127, min(127, int(round(nz * 127)))))
        struct.pack_into("<3b", packed, 12, 127, 0, 0)          # tangent: unused by the imported mesh
        u, v = vertex.get("uv") or (0.0, 0.0)
        struct.pack_into("<2e", packed, 16, float(u), float(v))
        vertex_buffer += packed
    # one triangle per strip, separated by the 0xFFFF restart marker the game's strip stream uses
    strips = bytearray()
    for a, b, c in triangles:
        strips += struct.pack("<4H", a, b, c, 0xFFFF)
    index_count = len(strips) // 2
    record = {"vertex_count": len(vertices), "vertex_stride": IMPORT_STRIDE, "vertex_format": IMPORT_FORMAT,
              "vertex_offset": 0, "material_index": material_index, "level_of_detail": 0}
    built = mt_model.rebuild_mod(source_model, vertex_buffer=bytes(vertex_buffer), index_buffer=bytes(strips),
                                 mesh_records=[record], vertex_count=len(vertices), mesh_count=1,
                                 face_count=index_count, bounds=bounds)
    check = mt_model.parse_mod(built)
    if not check.split_valid():
        raise ImportError_("the rebuilt model does not describe itself")
    return built
