"""MT Framework model files (`MRL\\0`), the container a Switch RE title reads for a mesh.

Stage 1 (this module today): parse the header and the resource-path table and re-emit them byte-for-byte, so the writer
owns those fields instead of copying bytes. The geometry that follows the table is carried opaque until its layout is
decoded; nothing here invents a field it does not understand.

Measured layout (all values little-endian, verified against nine models in uPl00ChrisNormal.arc and uWp06.arc):

    0x00  "MRL\\0"
    0x04  u32 version            34 in every model seen
    0x08  u32 count1             unknown meaning, varies per model (6, 9, 12, 60, 65, 123, 131 ...)
    0x0c  u32 path_count         EQUALS the number of 88-byte path records that follow - 9 of 9 models matched
    0x10  u32 hash               varies (0x7be0e51f on evf0000)
    0x14  u32 0
    0x18  u32 40                 the offset of the table below
    0x1c  u32 0
    0x20  u32 offset             a second offset (0x6b0 on evf0000); meaning not yet decoded
    0x24  u32 0
    0x28  u32 0x241f5deb         the same constant .arc entry records carry
    0x2c  .. 0x3f zeros
    0x40  path_count * 88 bytes, each a NUL-terminated ASCII path padded with 0xcd fill, e.g.
          "pawn\\pl\\pl00\\model\\evf0000_01_NM"
    then the geometry stream, opaque here.
"""
from __future__ import annotations

import struct
import math
from dataclasses import dataclass, field

MAGIC = b"MRL\x00"
VERSION = 34
CONST_OFFSET = 0x28          # the header field at 0x18 points here (40); the 0x241f5deb constant lives at it
HEADER_SIZE = 0x40           # the path table starts here: CONST_OFFSET + 24 (the constant and five zero words)
PATH_RECORD = 0x58           # 88 bytes per resource path: path[64] + u32 + 20 zero bytes
PATH_FIELD = 0x40            # the path occupies the first 64 bytes (NUL-terminated, 0xcd filled)
PATH_TAIL = 24               # what follows: the 0x241f5deb constant and twenty zero bytes, kept verbatim
TABLE_OFFSET = 0x18          # the header field holding CONST_OFFSET
ARC_CONST = 0x241F5DEB


class ModelError(ValueError):
    """A payload that is not an MRL model, or one whose header does not describe its own bytes."""


@dataclass
class ModelFile:
    version: int
    count1: int
    words: list[int]                     # the six u32 at 0x10..0x27, kept verbatim
    const: int                           # the u32 at 0x28 (ARC_CONST in every model seen)
    zeros: bytes                         # 0x2c..0x3f, kept verbatim
    paths: list[str] = field(default_factory=list)
    path_tails: list[bytes] = field(default_factory=list)   # per record: the constant and its zero padding
    tail: bytes = b""                    # the geometry stream, opaque

    def __len__(self) -> int:
        return HEADER_SIZE + PATH_RECORD * len(self.paths) + len(self.tail)


def parse(data: bytes, *, strict: bool = True) -> ModelFile:
    """Read an MRL model's header and path table. `strict` also checks the offsets against the payload length."""
    data = bytes(data)
    if len(data) < HEADER_SIZE or data[:4] != MAGIC:
        raise ModelError(f"not an MRL model (magic {data[:4]!r})")
    version, count1, path_count = struct.unpack_from("<III", data, 4)
    if version != VERSION:
        raise ModelError(f"unsupported MRL version {version} (expected {VERSION})")
    words = list(struct.unpack_from("<6I", data, 0x10))
    const = struct.unpack_from("<I", data, CONST_OFFSET)[0]
    zeros = data[0x2C:HEADER_SIZE]
    # the header says where the constant block is; the path table begins 24 bytes after it. Deriving it from the file
    # rather than assuming 0x40 is what caught this: 40 means 0x28, not the table's own offset.
    if strict and words[2] != CONST_OFFSET:
        raise ModelError(f"constant-block offset field is {words[2]}, not {CONST_OFFSET}")
    table = (words[2] if words[2] else CONST_OFFSET) + 0x18
    end = table + path_count * PATH_RECORD
    if path_count > 4096 or end > len(data):
        raise ModelError(f"path table of {path_count} records runs past the payload ({len(data)} bytes)")
    paths = []
    tails = []
    for i in range(path_count):
        record = data[table + i * PATH_RECORD:table + (i + 1) * PATH_RECORD]
        path = record[:PATH_FIELD].split(b"\x00", 1)[0]
        if not path or any(b < 0x20 or b > 0x7E for b in path):
            raise ModelError(f"path record {i} is not printable ASCII")
        paths.append(path.decode("ascii"))
        tails.append(record[PATH_FIELD:])
    return ModelFile(version=version, count1=count1, words=words, const=const, zeros=zeros,
                     paths=paths, path_tails=tails, tail=data[end:])


def build(model: ModelFile) -> bytes:
    """Re-emit the model. The header and the path table are written from the parsed fields; the geometry is the
    payload that was carried, byte for byte."""
    if model.version != VERSION:
        raise ModelError(f"unsupported MRL version {model.version}")
    if len(model.zeros) != HEADER_SIZE - 0x2C:
        raise ModelError("header padding must be 0x2c..0x40")
    if len(model.words) != 6:
        raise ModelError("the header words are six u32")
    out = bytearray(MAGIC)
    out += struct.pack("<III", model.version, model.count1, len(model.paths))
    out += struct.pack("<6I", *model.words)
    out += struct.pack("<I", model.const)
    out += model.zeros
    for index, path in enumerate(model.paths):
        raw = path.encode("ascii")
        if len(raw) >= PATH_FIELD:
            raise ModelError(f"path {path!r} does not fit in {PATH_FIELD} bytes")
        tail = model.path_tails[index] if index < len(model.path_tails) else \
            struct.pack("<I", ARC_CONST) + b"\x00" * (PATH_TAIL - 4)
        if len(tail) != PATH_TAIL:
            raise ModelError("a path record's tail must be its 24 trailing bytes")
        out += raw + b"\x00" + b"\xcd" * (PATH_FIELD - len(raw) - 1) + tail
    out += model.tail
    return bytes(out)


# --- the geometry container (`MOD\0`) ---------------------------------------------------------------------------------
#
# Measured on nine models across five archives (2026-11-06):
#
#     0x00  "MOD\0"
#     0x04  u32            (0x0300d3 / 0x0200d3 / 0xd3 seen)
#     0x08  u32            (0x09000f / 0x020004 / 0x0b000b ...)
#     0x0c  u32 vertex_count        of the first submesh
#     0x10  u32            (2317, 530, 2335 ... no meaning yet)
#     0x14  u32            (1415, 390, 1143 ...)
#     0x18  u32 geometry_bytes      the size of block 4 (25764, 6592, 27336 ... - checked against the offsets)
#     0x1c  u32 0
#     0x20  u32 submesh_count       (2, 1, 1, 11, 9, 20 ...)
#     0x28  7 x u64 block offsets, rising, the last one 4 bytes short of the payload
#     then 6 blocks
#
# For a single-submesh model geometry_bytes / vertex_count is an EXACT integer stride: 16, 20, 24 and 28 were all seen
# (4 of 7 single-submesh models; the other three are the ones whose counts do not divide, so a per-submesh table must
# hold the split). A multi-submesh model (pl0000: 6 submeshes, 28091 vertices, 758592 bytes = 27.005 bytes/vertex) only
# makes sense as a sum over submeshes, which is the part still to decode.
MOD_MAGIC = b"MOD\x00"
MOD_VERSION_SWITCH = 211        # RE5/RE6/RE4 on Switch: u32 counts, u64 offsets, 56-byte mesh records
MOD_BLOCK_OFFSETS = 0x28
MOD_BLOCKS = 7                       # seven offsets, so six blocks
MOD_MESH_RECORD_V211 = 56            # measured: 31 of 31 models sum their records to vertex_count at this size
# (name, offset, struct code) inside one 211 mesh record. vertex_count and vertex_stride are confirmed by construction:
# their sums match the header and 8 vertices x 28 == the 224-byte vertex buffer of md0024. The remaining fields follow
# the published Mesh156/210 layout shifted to 211's 56-byte record: the record's own vertex/index ranges are what make a
# one-mesh rebuild possible, and `vertex_group_count` is what sizes the 144-byte weight-bound records after the table
# (measured 2026-11-08: `sum(vertex_group_count) * 144 == vertex_buffer_offset - meshes_offset - 56 * mesh_count` on
# 1,421 of 1,421 model-variant containers in RE5's archive tree).
MOD_MESH_FIELDS = (
    ("mesh_type", 0x00, "H"),
    ("vertex_count", 0x02, "H"),
    # +0x04 is a packed word: group 12 bits, material 12 bits, LOD mask 8 bits (handled below).
    ("vertex_flags", 0x08, "B"),
    ("mesh_class", 0x09, "B"),
    ("vertex_stride", 0x0A, "B"),
    ("render_mode", 0x0B, "B"),
    ("vertex_index", 0x0C, "I"),
    ("vertex_offset", 0x10, "I"),
    ("face_index", 0x18, "I"),
    ("face_count", 0x1C, "I"),
    ("face_offset", 0x20, "I"),
    ("bone_map_index", 0x24, "B"),
    ("vertex_group_count", 0x25, "B"),
    ("mesh_id", 0x26, "H"),
    ("min_index", 0x28, "H"),
    ("max_index", 0x2A, "H"),
)
MOD_WEIGHT_BOUND = 144          # one record: bone u32, 12 pad, sphere, min, max, 4x4 matrix, extents

MOD_MESH_FORMAT_OFFSET = 0x14        # a u32 written big-endian, one of the documented FVF values
# The documented FVF values and the vertex stride each one implies (MT Framework MOD research). Measured on 1895 mesh
# records: the value at +0x14 is one of these on 1895 of 1895, and its stride agrees with the record's own vertex_stride
# on 1895 of 1895 - an independent confirmation of both fields.
MOD_FVF_STRIDES = {
    0x133098B0: 12, 0x14A07DDB: 16, 0x36D0D7A7: 20, 0x1580B60C: 20, 0x18B0FAA8: 20,
    0x1C201FC3: 24, 0x3AA06FC6: 24, 0x1AC0F6CB: 24, 0x287029D8: 24, 0x3870A4D1: 24, 0x37607D20: 24,
    0x2000D414: 28, 0x29F0B449: 28, 0x16C020A3: 28, 0x2C207F5E: 28, 0x3C004EA1: 28, 0x2D30A6AF: 28,
    0x2ED06F92: 32, 0x2AE06DB8: 32, 0x33C09993: 32, 0x21A055DA: 32, 0x1B8077D8: 32,
    0x244042BB: 36, 0x1F1092B3: 36, 0x341068B6: 36, 0x2FC0B663: 36,
    0x23305964: 40, 0x2770CFCB: 48, 0x3DC0552F: 64,
}


def fvf_stride(value: int) -> int | None:
    """The vertex stride a documented FVF format implies, or None when the format is not in the table."""
    return MOD_FVF_STRIDES.get(value)


# Formats whose position is three signed shorts. Everything else in the record is per-format; positions are what the
# 3D view needs first, and they are the component that can be validated against the model's own box.
MOD_SHORT_POSITION = frozenset({0x133098B0, 0x18B0FAA8, 0x1580B60C, 0x1C201FC3, 0x2000D414, 0x14A07DDB,
                                0x16C020A3, 0x244042BB})
# Formats whose first component is three FLOAT32 positions (from the documented layouts).
MOD_FLOAT_POSITION = frozenset({0x36D0D7A7, 0x3AA06FC6, 0x287029D8, 0x3870A4D1, 0x37607D20, 0x29F0B449,
                                0x2C207F5E, 0x3C004EA1, 0x2D30A6AF, 0x2ED06F92, 0x2AE06DB8, 0x33C09993,
                                0x341068B6, 0x2FC0B663})
# Component offsets for the formats whose normals and UVs are confirmed: the normals decode to unit length on 100% of
# the vertices sampled (123, 40 and 85 respectively) and the UVs fall inside 0..1. The stride-12 format 0x133098B0 is
# NOT in this table: its normals are unit length on only 39% of vertices at the documented offset and no other offset
# or width examined does better, so that format's layout is still open and it returns nothing rather than a guess.
MOD_FVF_LAYOUTS = {
    0x18B0FAA8: {"normal": 8, "tangent": 12, "uv": 16},
    0x1C201FC3: {"normal": 8, "tangent": 12, "uv": 16},
    0x2000D414: {"normal": 8, "tangent": 12, "uv": 20},
}
# Where each format keeps its bone ids. Validated by checking every value against the model's own bone_count: 100% of
# the ids from 0x133098b0, 0x1580b60c, 0x18b0faa8 and 0x2000d414 are below it, and 28344 of 28344 half-float ids from
# 0x1c201fc3 are whole numbers inside it.
MOD_BONE_FIELDS = {
    0x133098B0: (6, 1, "H"),
    0x18B0FAA8: (6, 1, "H"),
    0x1580B60C: (8, 4, "B"),
    0x2000D414: (16, 4, "B"),
    0x1C201FC3: (20, 2, "e"),
}
# Tangents sit at +12 as four signed bytes on every format that carries one, and decode to unit length on 6198/6198,
# 16669/16669 and 13594/13594 vertices of the three formats checked.
MOD_BONE_RECORD = 152             # bytes per bone record on the Switch version (256-byte map + count * 152 = the block)
MOD_TANGENT_OFFSET = 12
MOD_TANGENT_FORMATS = frozenset({0x18B0FAA8, 0x1C201FC3, 0x2000D414})
# Skin weights: two half floats at +24 (0x2000d414, in 0..1 on 16669/16669 vertices) and four bytes at +12
# (0x1580b60c, summed to 255 on 9183 of 10212 - the rest of that format's field is not fully confirmed).
MOD_WEIGHT_FIELDS = {
    0x2000D414: (24, 2, "e"),
    0x1580B60C: (12, 4, "B"),
}


def decode_tangents(data: bytes, vertex_format: int, count: int, stride: int) -> list[tuple[float, float, float]]:
    """Unit tangents from signed bytes, for the formats that carry one."""
    if vertex_format not in MOD_TANGENT_FORMATS:
        return []
    out = []
    for index in range(count):
        base = index * stride + MOD_TANGENT_OFFSET
        if base + 3 > len(data):
            break
        tx, ty, tz = struct.unpack_from("<3b", data, base)
        out.append((tx / 127.0, ty / 127.0, tz / 127.0))
    return out


def decode_weights(data: bytes, vertex_format: int, count: int, stride: int) -> list[tuple[float, ...]]:
    """Skin weights per vertex, for the formats whose weight field is confirmed."""
    field = MOD_WEIGHT_FIELDS.get(vertex_format)
    if field is None:
        return []
    offset, width, code = field
    size = width * struct.calcsize("<" + code)
    out = []
    for index in range(count):
        base = index * stride + offset
        if base + size > len(data):
            break
        values = struct.unpack_from(f"<{width}{code}", data, base)
        if code == "B":
            out.append(tuple(v / 255.0 for v in values))
        else:
            out.append(tuple(float(v) for v in values))
    return out


def decode_bone_ids(data: bytes, vertex_format: int, count: int, stride: int) -> list[tuple[int, ...]]:
    """Each vertex's bone ids, for the formats whose layout is confirmed."""
    field = MOD_BONE_FIELDS.get(vertex_format)
    if field is None:
        return []
    offset, width, code = field
    size = width * struct.calcsize("<" + code)
    out = []
    for index in range(count):
        base = index * stride + offset
        if base + size > len(data):
            break
        values = struct.unpack_from(f"<{width}{code}", data, base)
        out.append(tuple(int(round(v)) for v in values))
    return out


def decode_normals(data: bytes, vertex_format: int, count: int, stride: int) -> list[tuple[float, float, float]]:
    """Unit normals from signed bytes, for the formats whose layout is confirmed."""
    layout = MOD_FVF_LAYOUTS.get(vertex_format)
    if layout is None:
        return []
    out = []
    for index in range(count):
        base = index * stride + layout["normal"]
        if base + 3 > len(data):
            break
        nx, ny, nz = struct.unpack_from("<3b", data, base)
        out.append((nx / 127.0, ny / 127.0, nz / 127.0))
    return out


def decode_uvs(data: bytes, vertex_format: int, count: int, stride: int) -> list[tuple[float, float]]:
    """Texture coordinates as half floats, for the formats whose layout is confirmed."""
    layout = MOD_FVF_LAYOUTS.get(vertex_format)
    if layout is None:
        return []
    out = []
    for index in range(count):
        base = index * stride + layout["uv"]
        if base + 4 > len(data):
            break
        u, v = struct.unpack_from("<2e", data, base)
        out.append((u, v))
    return out


def encode_positions(points: list[tuple[float, float, float]], bounds: dict, vertex_format: int) -> bytes:
    """Pack model-space positions the way the format stores them: the inverse of decode_positions.

    This is the writer's primitive. The quantisation is the one measured on decode - `(value - min) / size * 32767` for
    the short formats - so a value that survives decode and re-encode comes back within one quantisation step, which is
    what the round-trip test checks.
    """
    low = (bounds["min"]["x"], bounds["min"]["y"], bounds["min"]["z"])
    span = (bounds["max"]["x"] - low[0], bounds["max"]["y"] - low[1], bounds["max"]["z"] - low[2])
    out = bytearray()
    for x, y, z in points:
        if vertex_format in MOD_FLOAT_POSITION:
            out += struct.pack("<3f", x, y, z)
            continue
        if vertex_format not in MOD_SHORT_POSITION:
            raise ModelError(f"format {vertex_format:08x} has no known position layout")
        packed = []
        for axis, value in enumerate((x, y, z)):
            scaled = 0.0 if not span[axis] else (value - low[axis]) / span[axis]
            packed.append(max(0, min(32767, int(round(scaled * 32767.0)))))
        out += struct.pack("<3H", *packed)
    return bytes(out)


def encode_normals(normals: list[tuple[float, float, float]], vertex_format: int) -> bytes:
    """Pack normals as the three signed bytes the confirmed formats use."""
    if vertex_format not in MOD_FVF_LAYOUTS:
        raise ModelError(f"format {vertex_format:08x} has no known normal layout")
    out = bytearray()
    for x, y, z in normals:
        out += struct.pack("<3b", max(-127, min(127, int(round(x * 127.0)))),
                           max(-127, min(127, int(round(y * 127.0)))),
                           max(-127, min(127, int(round(z * 127.0)))))
    return bytes(out)


def encode_uvs(uvs: list[tuple[float, float]], vertex_format: int) -> bytes:
    """Pack texture coordinates as half floats."""
    if vertex_format not in MOD_FVF_LAYOUTS:
        raise ModelError(f"format {vertex_format:08x} has no known uv layout")
    return b"".join(struct.pack("<2e", u, v) for u, v in uvs)


def _transform_point(point, matrix):
    """MT matrices use row vectors; translation is in the last row."""
    return tuple(sum(point[k] * matrix[k * 4 + axis] for k in range(3)) + matrix[12 + axis]
                 for axis in range(3))


def _inverse_matrix(matrix):
    rows = [[float(matrix[r * 4 + c]) for c in range(4)] + [float(r == c) for c in range(4)]
            for r in range(4)]
    for col in range(4):
        pivot = max(range(col, 4), key=lambda row: abs(rows[row][col]))
        if abs(rows[pivot][col]) < 1e-12:
            raise ModelError("the position transform is singular")
        rows[col], rows[pivot] = rows[pivot], rows[col]
        divisor = rows[col][col]
        rows[col] = [v / divisor for v in rows[col]]
        for row in range(4):
            if row != col:
                scale = rows[row][col]
                rows[row] = [a - scale * b for a, b in zip(rows[row], rows[col])]
    return tuple(rows[r][c + 4] for r in range(4) for c in range(4))


def pack_vertices(vertices: list[dict], vertex_format: int, stride: int, base: bytes | None = None,
                  *, position_transform=None) -> bytes:
    """Build a vertex buffer: each component written at its documented offset inside the stride.

    This is what a writer hands to the container. A vertex is a dict with any of "position" (model-space x, y, z),
    "normal" (unit vector), "tangent" (unit vector), "uv" (u, v), "bones" (ids) and "weights" (0..1). Anything the format
    does not carry, or the caller does not supply, is left as whatever `base` holds - pass the vertex data the model
    already had and every undecoded field survives untouched.

    Passing `base` matters: without it, a format whose layout is not confirmed (0x133098b0's normals, for one) gets zeros,
    which is silent data loss. Measured: rewriting a mine's model with zeroed normals rendered as unlit blobs.
    """
    layout = MOD_FVF_LAYOUTS.get(vertex_format, {})
    short_position = vertex_format in MOD_SHORT_POSITION
    float_position = vertex_format in MOD_FLOAT_POSITION
    if not (short_position or float_position):
        raise ModelError(f"format {vertex_format:08x} has no known position layout")
    bone_field = MOD_BONE_FIELDS.get(vertex_format)
    inverse = _inverse_matrix(position_transform) if position_transform is not None and short_position else None
    out = bytearray()
    for index, vertex in enumerate(vertices):
        if base is not None and (index + 1) * stride <= len(base):
            packed = bytearray(base[index * stride:(index + 1) * stride])
        else:
            packed = bytearray(stride)
        bounds = vertex.get("bounds")
        if "position" in vertex:
            x, y, z = vertex["position"]
            if short_position:
                if inverse is not None:
                    normalized = _transform_point((x, y, z), inverse)
                    if any(not math.isfinite(v) or v < -1.0001 or v > 1.0001 for v in normalized):
                        raise ModelError("the position does not fit the target skeleton's quantisation transform")
                    struct.pack_into("<3h", packed, 0,
                                     *(max(-32767, min(32767, round(v * 32767))) for v in normalized))
                elif not bounds:
                    raise ModelError("a short-position vertex needs the model bounds to quantise against")
                else:
                    low = (bounds["min"]["x"], bounds["min"]["y"], bounds["min"]["z"])
                    span = (bounds["max"]["x"] - low[0], bounds["max"]["y"] - low[1], bounds["max"]["z"] - low[2])
                    values = []
                    for axis, value in enumerate((x, y, z)):
                        scaled = 0.0 if not span[axis] else (value - low[axis]) / span[axis]
                        values.append(max(0, min(32767, int(round(scaled * 32767.0)))))
                    struct.pack_into("<3H", packed, 0, *values)
            else:
                struct.pack_into("<3f", packed, 0, x, y, z)
        if "normal" in vertex and "normal" in layout:
            nx, ny, nz = vertex["normal"]
            struct.pack_into("<3b", packed, layout["normal"],
                             max(-127, min(127, int(round(nx * 127)))),
                             max(-127, min(127, int(round(ny * 127)))),
                             max(-127, min(127, int(round(nz * 127)))))
        if "uv" in vertex and "uv" in layout:
            struct.pack_into("<2e", packed, layout["uv"], *vertex["uv"])
        if "tangent" in vertex and vertex_format in MOD_TANGENT_FORMATS:
            tx, ty, tz = vertex["tangent"]
            struct.pack_into("<3b", packed, MOD_TANGENT_OFFSET,
                             max(-127, min(127, int(round(tx * 127)))),
                             max(-127, min(127, int(round(ty * 127)))),
                             max(-127, min(127, int(round(tz * 127)))))
        # These authored layouts store occlusion in normal.w and bitangent handedness in tangent.w.
        # Only explicit values are written, preserving opaque/base bytes for in-place edits.
        if vertex_format in MOD_TANGENT_FORMATS:
            if "occlusion" in vertex:
                occlusion = float(vertex["occlusion"])
                if not math.isfinite(occlusion) or not 0 <= occlusion <= 1:
                    raise ModelError("occlusion must be finite and between zero and one")
                struct.pack_into("<b", packed, layout["normal"]+3, round(occlusion*127))
            if "tangent_sign" in vertex:
                sign = float(vertex["tangent_sign"])
                if sign not in (-1.,1.):
                    raise ModelError("tangent handedness must be -1 or 1")
                struct.pack_into("<b", packed, MOD_TANGENT_OFFSET+3, int(sign*127))
        if "weights" in vertex and vertex_format in MOD_WEIGHT_FIELDS:
            offset, width, code = MOD_WEIGHT_FIELDS[vertex_format]
            values = list(vertex["weights"])[:width]
            while len(values) < width:
                values.append(0.0)
            if code == "B":
                struct.pack_into(f"<{width}B", packed, offset,
                                 *[max(0, min(255, int(round(v * 255)))) for v in values])
            else:
                struct.pack_into(f"<{width}e", packed, offset, *values)
        if "bones" in vertex and bone_field:
            offset, width, code = bone_field
            values = list(vertex["bones"])[:width]
            while len(values) < width:
                values.append(0)
            struct.pack_into(f"<{width}{code}", packed, offset, *values)
        out += packed
    return bytes(out)


def decode_positions(data: bytes, vertex_format: int, count: int, stride: int, bounds: dict,
                     limit: int = 0, *, position_transform=None) -> list[tuple[float, float, float]]:
    """Decode positions with the skeleton's model transform when supplied.

    Being inside the bounding box did not validate the old per-axis scale: real em1000 uses a uniform 276.5326 scale
    stored in root inverse-bind * root local. The box path remains for standalone buffers without a usable skeleton.
    """
    if vertex_format in MOD_FLOAT_POSITION:
        out = []
        for index in range(count if not limit else min(count, limit)):
            base = index * stride
            if base + 12 > len(data):
                break
            x, y, z = struct.unpack_from("<3f", data, base)
            out.append((x, y, z))
        return out
    if vertex_format not in MOD_SHORT_POSITION:
        return []
    low = (bounds["min"]["x"], bounds["min"]["y"], bounds["min"]["z"])
    span = (bounds["max"]["x"] - low[0], bounds["max"]["y"] - low[1], bounds["max"]["z"] - low[2])
    take = count if not limit else min(count, limit)
    out = []
    for index in range(take):
        base = index * stride
        if base + 6 > len(data):
            break
        sx, sy, sz = struct.unpack_from("<3h", data, base)
        normalized = (sx / 32767.0, sy / 32767.0, sz / 32767.0)
        out.append(_transform_point(normalized, position_transform) if position_transform is not None else
                   tuple(low[i] + normalized[i] * span[i] for i in range(3)))
    return out
MOD_OFFSET_NAMES = ("bones", "groups", "materials", "meshes", "vertex_buffer", "index_buffer", "end")


@dataclass
class ModFile:
    """A parsed `MOD` geometry container.

    `raw` is kept whole: the header is 0x60 bytes, then a gap of unknown meaning up to the first block offset (164 in
    the object models), then the blocks. Re-emitting an unchanged model is therefore exact; describing what lies in the
    gap (most likely the per-submesh table) is what writing new geometry still needs.
    """
    words: list[int]                    # the eight u32 at 0x04..0x23
    offsets: list[int]                  # the seven block offsets at 0x28
    raw: bytes
    variant: str = "model"              # "model" (header 0x60, first block at 164) or "effect" (table starts at 0)

    @property
    def vertex_count(self) -> int:
        return self.words[2]

    @property
    def geometry_bytes(self) -> int:
        return self.words[5]

    @property
    def submeshes(self) -> int:
        return self.words[7]

    @property
    def header_size(self) -> int:
        return MOD_BLOCK_OFFSETS + 8 * MOD_BLOCKS

    def all_positions(self) -> list[tuple[float, float, float]]:
        """Every mesh's positions concatenated, in the order the index buffer addresses them.

        A mesh whose positions cannot be decoded contributes its vertices as the origin rather than nothing: the index
        buffer addresses the whole model's vertex space, so dropping a mesh would shift every later index and draw a
        garbled surface (measured: 3647 out-of-range indices before this was fixed).
        """
        out = []
        for index, record in enumerate(self.meshes()):
            points = self.positions(index)
            if len(points) != record["vertex_count"]:
                points = [(0.0, 0.0, 0.0)] * record["vertex_count"]
            out.extend(points)
        return out

    def triangle_strips(self) -> list[list[int]]:
        """The index buffer as strips: `0xFFFF` separates them.

        Measured on real models: the index buffer holds `face_count` ushorts (not three per face), `0xFFFF` appears as a
        separator, and every referenced vertex is inside the model's vertex range (496/496, 2075/2075, 1614/1614 on the
        three models checked). The strips are stitched with degenerate triangles - one strip reads
        [0, 1, 2, 3, 4, 3, 5, 6, 7, 8] - which is the classic tristrip trick, so this is a strip stream rather than a
        triangle list.
        """
        header = self.header()
        start = header["offsets"]["index_buffer"]
        data = self.raw[start:start + 2 * header["face_count"]]
        strips, current = [], []
        for value in struct.unpack_from(f"<{len(data) // 2}H", data, 0):
            if value == 0xFFFF:
                if len(current) >= 3:
                    strips.append(current)
                current = []
            else:
                current.append(value)
        if len(current) >= 3:
            strips.append(current)
        return strips

    def triangles(self) -> list[tuple[int, int, int]]:
        """Triangles from the strips, with alternating winding as a strip requires."""
        out = []
        for strip in self.triangle_strips():
            for i in range(len(strip) - 2):
                a, b, c = strip[i], strip[i + 1], strip[i + 2]
                if i % 2:
                    a, b = b, a
                if a == b or b == c or a == c:
                    continue
                out.append((a, b, c))
        return out

    def bone_map(self) -> list[int]:
        """The 256-byte bone map's first `bone_count` bytes: the documented animation lookup, NOT the hierarchy.

        It is tempting to read this as per-bone parents - a two-bone weapon gives [1, 255] and a three-bone one
        [1, 2, 255], which look exactly like a chain with a root. But it does not hold: a 28-bone enemy gives
        [0, 15, 16, 17, ...] with no 255 at all and its first bone parented to itself, and an 86-bone one is
        [0, 1, 2, 3, 4, 84, 255, 255, ...] - five entries then padding. Neither is a tree. The document calls this a
        "bone lookup table used for animation", which fits what is actually there, so it is returned as such and the
        hierarchy is left undecoded rather than guessed from two small samples.
        """
        table = self.bone_table()
        count = table["bone_count"]
        if not count or len(table["map"]) < count:
            return []
        return list(table["map"][:count])

    def bone_world(self) -> list[tuple[int, float, float, float]]:
        """(index, x, y, z) per bone, composed along the hierarchy from the local bind matrices."""
        return [(i, w[12], w[13], w[14]) for i, w in enumerate(self.bone_world_matrices())]

    def bone_world_matrices(self) -> list[tuple[float, ...]]:
        """Uncompressed bind matrices used for anatomy and bone-local envelope coordinates."""
        table = self.bone_table()
        if not table.get("consistent") or not table.get("local"):
            return []
        parents = table["parents"]
        local = [struct.unpack_from("<16f", block, 0) for block in table["local"]]
        world: list[list[float] | None] = [None] * len(parents)
        for index in range(len(parents)):
            parent = parents[index]
            if parent == 255 or parent >= len(parents) or world[parent] is None:
                world[index] = list(local[index])
            else:
                a, b = local[index], world[parent]
                world[index] = [sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4))
                                for r in range(4) for c in range(4)]
        return [tuple(w) for w in world if w is not None]

    def bone_roles(self) -> dict:
        """Bone roles inferred from where the bones actually are - the table a retarget needs.

        Measured on Chris's body: the highest bone sits at y 185.1 cm in a 187 cm model (the head), the extremes at
        x +-88.1 sit at y 152.4 (outstretched fingertips), the lowest is a foot at y 4.4, and the root is the hips. So
        `head = highest`, `hands = extreme x at arm height`, `feet = lowest on each side`, `root = the bone with no
        parent`. That is derived per model rather than hand-authored per character, which is what makes it reusable.
        """
        points = self.bone_world()
        if not points:
            return {}
        parents = self.bone_table()["parents"]
        highest = max(points, key=lambda p: p[2])
        lowest = min(points, key=lambda p: p[2])
        left = min(points, key=lambda p: p[1])
        right = max(points, key=lambda p: p[1])
        roots = [i for i, parent in enumerate(parents) if parent == 255]
        # feet: the lowest bone on each side of the centre line
        feet = [min((p for p in points if p[1] <= 0), key=lambda p: p[2], default=None),
                min((p for p in points if p[1] > 0), key=lambda p: p[2], default=None)]
        return {"root": roots[0] if roots else None,
                "hips": roots[0] if roots else None,
                "head": highest[0],
                "left_hand": left[0],
                "right_hand": right[0],
                "left_foot": feet[0][0] if feet[0] else None,
                "right_foot": feet[1][0] if feet[1] else None,
                "lowest": lowest[0],
                "height": round(highest[2] - lowest[2], 2),
                "span": round(right[1] - left[1], 2)}

    def bone_table(self) -> dict:
        """The skeleton: per-bone headers, then the local and inverse-bind matrices, then the map and palettes.

        The block is **structure-of-arrays**, not one 152-byte record per bone - which is why three rounds of slicing it
        into 152-byte records found no parents and no matrices:

            bone_count x 24   header per bone (anim map index at +0, parent at +1, ...)
            bone_count x 64   local (bind) matrices, 4x4 floats
            bone_count x 64   inverse bind matrices
            256               the bone map (animation lookup)
            palettes x 68     bone palettes

        `24 + 64 + 64 = 152` per bone, which is exactly the arithmetic that located the block, and the layout matches
        gBox's existing PS3 reader (`re5ps3_models`, lines 173-176), which reads parents at `+i*24+1`, the local matrices
        at `nb*24` and the inverse bind at `nb*88`.
        """
        header = self.header()
        start, end = header["offsets"]["bones"], header["offsets"]["groups"]
        count = header["bone_count"]
        region = self.raw[start:end]
        need = count * MOD_BONE_RECORD
        if not count or len(region) < need + 256:
            return {"bone_count": count, "region": len(region), "headers": [], "local": [],
                    "inverse_bind": [], "map": b"", "consistent": False}
        headers = [region[i * 24:(i + 1) * 24] for i in range(count)]
        local = [region[count * 24 + i * 64:count * 24 + (i + 1) * 64] for i in range(count)]
        inverse = [region[count * 88 + i * 64:count * 88 + (i + 1) * 64] for i in range(count)]
        return {"bone_count": count, "region": len(region), "headers": headers, "local": local,
                "inverse_bind": inverse,
                "map": region[count * MOD_BONE_RECORD:count * MOD_BONE_RECORD + 256],
                "parents": [h[1] for h in headers],
                "anim_map": [h[0] for h in headers],
                "consistent": len(region) >= need + 256}

    def pack_part(self, mesh_index: int, vertices: list[dict]) -> bytes:
        """Pack one part's vertices over the bytes it already has, so undecoded fields (normals in 0x133098b0) survive.

        This is the safe way to write geometry: `pack_vertices` alone seeds every byte with zero, which erases any
        component whose layout is not confirmed. The mine's normals are exactly that case.
        """
        data, record = self.mesh_bytes(mesh_index)
        if not data:
            raise ModelError(f"part {mesh_index} has no vertex data")
        return pack_vertices(vertices, record["vertex_format"], record["vertex_stride"], base=data,
                             position_transform=self.position_transform())

    def position_transform(self) -> tuple[float, ...] | None:
        """Model-space transform for normalized short positions: root inverse-bind * root local.

        The root inverse bind includes position compression; it is not a conventional unscaled inverse bind. Preserve
        it when authoring against the existing skeleton. No-skeleton/zero-matrix synthetic buffers use the box fallback.
        """
        table = self.bone_table()
        if not table.get("consistent") or not table.get("local"):
            return None
        a = struct.unpack("<16f", table["inverse_bind"][0])
        b = struct.unpack("<16f", table["local"][0])
        matrix = tuple(sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4))
                       for r in range(4) for c in range(4))
        if not all(math.isfinite(v) for v in matrix) or abs(matrix[15] - 1.) > 1e-5:
            return None
        try:
            _inverse_matrix(matrix)
        except ModelError:
            return None
        return matrix

    def mesh_bytes(self, mesh_index: int) -> tuple[bytes, dict]:
        """One mesh's vertex data and its record, so a caller can decode whichever components it needs."""
        header = self.header()
        meshes = self.meshes()
        if not 0 <= mesh_index < len(meshes):
            return b"", {}
        record = meshes[mesh_index]
        start = (header["offsets"]["vertex_buffer"] + record["vertex_offset"]
                 + record["vertex_index"] * record["vertex_stride"])
        end = start + record["vertex_count"] * record["vertex_stride"]
        if not header["offsets"]["vertex_buffer"] <= start <= end <= header["offsets"]["index_buffer"] <= len(self.raw):
            raise ModelError(f"part {mesh_index}'s vertices run outside the vertex buffer")
        return self.raw[start:end], record

    def normals(self, mesh_index: int = 0) -> list[tuple[float, float, float]]:
        data, record = self.mesh_bytes(mesh_index)
        if not data:
            return []
        return decode_normals(data, record["vertex_format"], record["vertex_count"], record["vertex_stride"])

    def uvs(self, mesh_index: int = 0) -> list[tuple[float, float]]:
        data, record = self.mesh_bytes(mesh_index)
        if not data:
            return []
        return decode_uvs(data, record["vertex_format"], record["vertex_count"], record["vertex_stride"])

    def bone_ids(self, mesh_index: int = 0) -> list[tuple[int, ...]]:
        data, record = self.mesh_bytes(mesh_index)
        if not data:
            return []
        return decode_bone_ids(data, record["vertex_format"], record["vertex_count"], record["vertex_stride"])

    def positions(self, mesh_index: int = 0, limit: int = 0) -> list[tuple[float, float, float]]:
        """The dequantised positions of one mesh, in model space (centimetres on the models measured)."""
        bounds = self.bounds()
        data, record = self.mesh_bytes(mesh_index)
        if bounds is None or not data:
            return []
        return decode_positions(data, record["vertex_format"], record["vertex_count"],
                                record["vertex_stride"], bounds, limit, position_transform=self.position_transform())

    def header(self) -> dict:
        """The documented header fields, decoded for the Switch version (211: u32 counts, u64 offsets)."""
        version, revision = self.raw[4], self.raw[5]
        bone, mesh, material = struct.unpack_from("<3H", self.raw, 0x06)
        vertices, faces, edges = struct.unpack_from("<3I", self.raw, 0x0C)
        vertex_buffer, vertex_buffer_2 = struct.unpack_from("<2I", self.raw, 0x18)
        groups = struct.unpack_from("<I", self.raw, 0x20)[0]
        offsets = dict(zip(MOD_OFFSET_NAMES,
                           (struct.unpack_from("<Q", self.raw, MOD_BLOCK_OFFSETS + 8 * i)[0]
                            for i in range(MOD_BLOCKS))))
        return {"version": version, "revision": revision, "bone_count": bone, "mesh_count": mesh,
                "material_count": material, "vertex_count": vertices, "face_count": faces, "edge_count": edges,
                "polygon_count": edges,  # +0x14; retain edge_count as the older caller-facing alias
                "vertex_buffer_size": vertex_buffer, "vertex_buffer_2_size": vertex_buffer_2,
                "group_count": groups, "offsets": offsets,
                "weight_bound_count": struct.unpack_from("<I", self.raw, 0xa0)[0]
                    if offsets["bones"] >= 0xa4 and len(self.raw) >= 0xa4 else None}

    def bounds(self) -> dict | None:
        """The model's bounding sphere and box, from the documented 48 bytes after the header's offset table.

        Measured sensible on real models: a standing character's box is y 154.2-184.2 with x/z within +-10, and a weapon
        sits at the origin with +-21.5. The 3D view needs this; the vertex decoder will need it too, since the short
        position formats are quantised and the box is the obvious scale - though the samples so far do not map linearly
        onto it, so that decode is still open.
        """
        start = MOD_BLOCK_OFFSETS + 8 * MOD_BLOCKS
        end = self.header()["offsets"]["bones"]
        if end - start < 48:
            return None
        sphere = struct.unpack_from("<4f", self.raw, start)
        low = struct.unpack_from("<4f", self.raw, start + 16)
        high = struct.unpack_from("<4f", self.raw, start + 32)
        return {"sphere": {"x": sphere[0], "y": sphere[1], "z": sphere[2], "r": sphere[3]},
                "min": {"x": low[0], "y": low[1], "z": low[2]},
                "max": {"x": high[0], "y": high[1], "z": high[2]}}

    def meshes(self) -> list[dict]:
        """The mesh records: one per part, each carrying its own vertex count and stride.

        Measured on 31 models across six archives: with a 56-byte record the vertex counts sum to the header's
        `vertex_count` on **31 of 31**. That is the per-part split the writer needs - it was never missing, it lives
        here rather than in the header.
        """
        header = self.header()
        if header["version"] != MOD_VERSION_SWITCH or not header["mesh_count"]:
            return []
        start = header["offsets"]["meshes"]
        region = header["offsets"]["vertex_buffer"] - start
        if region < MOD_MESH_RECORD_V211 * header["mesh_count"]:
            return []
        out = []
        for index in range(header["mesh_count"]):
            base = start + index * MOD_MESH_RECORD_V211
            record = {"index": index}
            for name, offset, code in MOD_MESH_FIELDS:
                record[name] = struct.unpack_from("<" + code, self.raw, base + offset)[0]
            packed = struct.unpack_from("<I", self.raw, base + 4)[0]
            record.update(group_index=packed & 0xFFF, material_index=(packed >> 12) & 0xFFF,
                          level_of_detail=packed >> 24)
            record["vertex_format"] = int.from_bytes(self.raw[base + MOD_MESH_FORMAT_OFFSET:
                                                              base + MOD_MESH_FORMAT_OFFSET + 4], "big")
            record["format_stride"] = fvf_stride(record["vertex_format"])
            out.append(record)
        return out

    def split_valid(self) -> bool:
        """True when the mesh records account for every vertex the header counts."""
        meshes = self.meshes()
        return bool(meshes) and sum(m["vertex_count"] for m in meshes) == self.header()["vertex_count"]

    def weight_bounds(self) -> list[dict]:
        """The per-bone envelope records that follow the 56-byte mesh table.

        Layout, measured on real assets (the published `WEIGHT_BOUNDING`): a u32 bone index, 12 padding bytes, a sphere
        (4 floats), min and max boxes (4 floats each), a 4x4 matrix whose translation is the sphere centre, and the
        box's half extents (4 floats). The table's length is `sum(mesh.vertex_group_count) * 144`; that equality holds
        on 1,421 of 1,421 model-variant containers in RE5's archive tree, which is what makes the records writable.
        """
        header = self.header()
        meshes = self.meshes()
        count = sum(m.get("vertex_group_count", 0) for m in meshes)
        start = header["offsets"]["meshes"] + MOD_MESH_RECORD_V211 * len(meshes)
        end = header["offsets"]["vertex_buffer"]
        if not count or end - start < count * MOD_WEIGHT_BOUND:
            return []
        out = []
        for index in range(count):
            base = start + index * MOD_WEIGHT_BOUND
            out.append({
                "bone": struct.unpack_from("<I", self.raw, base)[0],
                "pad": self.raw[base + 4:base + 16],
                "sphere": struct.unpack_from("<4f", self.raw, base + 16),
                "min": struct.unpack_from("<3f", self.raw, base + 32),
                "max": struct.unpack_from("<3f", self.raw, base + 48),
                "matrix": struct.unpack_from("<16f", self.raw, base + 64),
                "extent": struct.unpack_from("<3f", self.raw, base + 128),
            })
        return out

    def block(self, index: int) -> bytes:
        """Block `index` (0..5) of the geometry."""
        start, end = self.offsets[index], self.offsets[index + 1]
        return self.raw[start:end]

    def stride(self) -> float | None:
        """Bytes per vertex: exact for single-submesh models, where geometry_bytes == vertex_count * stride."""
        if not self.vertex_count:
            return None
        return self.geometry_bytes / self.vertex_count

    def layout(self) -> dict:
        """What the container's parts are, as far as they are decoded.

        Measured 2026-11-06 over 16 models in four archives:

        * **block 5 is the index buffer**: two bytes per index, and header word 0x10 is the index count
          (`len(block5) == 2 * index_count`, exact on 16/16, sometimes one or two indices of padding);
        * **block 4 is the vertex buffer**: for a single-submesh model `vertex_count * stride` equals its length with a
          stride of 16, 20, 24, 28 or 32 (an occasional 4-24 byte tail of padding makes the division inexact);
        * **block 3 is a table of 200-byte records** (a per-mesh/submesh descriptor: 200 x N records, N = 2, 11, 9, 20 ...
          which is the submesh count in most models), and **block 2 is a table of 128-byte records** beside it;
        * blocks 0 and 1 are small tables that scale with the model.

        The per-submesh vertex counts and strides are NOT in the header; they are what the records above must carry, and
        decoding them is what writing new geometry still needs.
        """
        block = [self.block(i) for i in range(6)]
        vertex, index = self.vertex_count, self.words[3]
        stride = self.stride()
        return {
            "vertex_count": vertex,
            "index_count": index,
            "submeshes": self.submeshes,
            "stride": stride,
            "stride_exact": bool(stride and abs(stride - round(stride)) < 1e-9),
            "vertex_block": len(block[4]),
            "index_block": len(block[5]),
            "index_block_matches": len(block[5]) in (2 * index, 2 * (index + 1), 2 * (index + 2)),
            "blocks": [len(b) for b in block],
            "records_200": len(block[3]) / 200,
            "records_128": len(block[2]) / 128,
            "variant": self.variant,
        }


def parse_mod(data: bytes, *, strict: bool = True) -> ModFile:
    """Read a `MOD` geometry container's header and block table. The blocks are carried, not interpreted."""
    data = bytes(data)
    if len(data) < MOD_BLOCK_OFFSETS + 8 * MOD_BLOCKS or data[:4] != MOD_MAGIC:
        raise ModelError(f"not a MOD container (magic {data[:4]!r})")
    words = list(struct.unpack_from("<8I", data, 0x04))
    offsets = [struct.unpack_from("<I", data, MOD_BLOCK_OFFSETS + 8 * i)[0] for i in range(MOD_BLOCKS)]
    if strict:
        if any(b < a for a, b in zip(offsets, offsets[1:])):
            raise ModelError(f"block offsets are not rising: {offsets}")
        if offsets[-1] > len(data):
            raise ModelError(f"the last block offset runs past the payload: {offsets}")
    return ModFile(words=words, offsets=offsets, raw=data, variant="effect" if offsets[0] < MOD_BLOCK_OFFSETS + 8
                   * MOD_BLOCKS else "model")


def replace_part(data: bytes, part_index: int, vertices: bytes, vertex_count: int, vertex_format: int,
                 stride: int, *, bounds: dict | None = None) -> bytes:
    """Rebuild a MOD with one part's geometry replaced, keeping every other part's bytes exactly as they are.

    This is the first writing step that changes the container's shape: the new part may have a different vertex count and
    stride, so every later part's `vertex_offset` moves and the header's `vertex_count` and `vertex_buffer_size` change
    with it. Untouched parts are copied byte for byte rather than re-packed, so components that are not decoded (a
    format's unknown fields) survive in them instead of being zeroed.
    """
    model = parse_mod(data)
    header = model.header()
    meshes = model.meshes()
    if not 0 <= part_index < len(meshes):
        raise ModelError(f"no part {part_index} (the model has {len(meshes)})")
    if len(vertices) != vertex_count * stride:
        raise ModelError("the vertex data does not match the count and stride")
    model.mesh_bytes(part_index)  # validate the target allocation before any in-place slice assignment
    vb = header["offsets"]["vertex_buffer"]
    blocks = []
    for index, record in enumerate(meshes):
        if index == part_index:
            blocks.append(vertices)
        else:
            blocks.append(model.mesh_bytes(index)[0])
    # A same-size rewrite must not move anything: models do NOT necessarily store their parts in record order, so
    # re-laying the buffer out contiguously points every other part at the wrong bytes. Measured on RE5's uEm10 (341
    # parts): a rewrite in which all 340 comparable parts' data came back byte-identical still moved 301,633 bytes of the
    # buffer, and the game hung. So when the new data is the same length as the part's, patch it in place and leave every
    # record and every other byte untouched.
    target = meshes[part_index]
    target_start = vb + target["vertex_offset"] + target["vertex_index"] * target["vertex_stride"]
    target_length = target["vertex_count"] * target["vertex_stride"]
    if (vertex_count, stride, vertex_format) == (target["vertex_count"], target["vertex_stride"], target["vertex_format"]) and target_length:
        patched = bytearray(data)
        patched[target_start:target_start + target_length] = vertices
        if bounds is not None:
            header_end = MOD_BLOCK_OFFSETS + 8 * MOD_BLOCKS
            tail_start = header_end
            if header["offsets"]["bones"] >= header_end + 48:
                struct.pack_into("<4f", patched, tail_start, bounds["sphere"]["x"], bounds["sphere"]["y"],
                                 bounds["sphere"]["z"], bounds["sphere"]["r"])
                struct.pack_into("<3f", patched, tail_start + 16,
                                 bounds["min"]["x"], bounds["min"]["y"], bounds["min"]["z"])
                struct.pack_into("<3f", patched, tail_start + 32,
                                 bounds["max"]["x"], bounds["max"]["y"], bounds["max"]["z"])
        return bytes(patched)
    if any(record["vertex_index"] for record in meshes):
        raise ModelError("resizing a shared vertex buffer needs an index rebuild; use an explicit topology author")
    records = []
    running = 0
    for index, record in enumerate(meshes):
        if index == part_index:
            record = dict(record, vertex_count=vertex_count, vertex_stride=stride, vertex_format=vertex_format)
        record = dict(record, vertex_offset=running)
        running += record["vertex_count"] * record["vertex_stride"]
        records.append(record)
    total_vertices = sum(record["vertex_count"] for record in records)
    rebuilt = rebuild_mod(model, vertex_buffer=b"".join(blocks), mesh_records=records,
                          vertex_count=total_vertices, bounds=bounds)
    return rebuilt


def rebuild_mod(model: ModFile, *, vertex_buffer: bytes | None = None, index_buffer: bytes | None = None,
                mesh_records: list[dict] | None = None, vertex_count: int | None = None,
                bounds: dict | None = None, mesh_count: int | None = None, face_count: int | None = None,
                edge_count: int | None = None, mesh_trailer: bytes | None = None) -> bytes:
    """Serialise a `MOD` from its parts, recomputing every offset from the block sizes.

    This is the writer, not a copy: the header is assembled from the decoded fields, the blocks are written in
    documented order, and each offset is derived from the running total. With nothing replaced the result must be
    byte-identical to the input - the test that proves the layout is understood rather than merely parseable - and
    replacing the vertex buffer, the index buffer or the mesh records is how new geometry is meant to be written.

    The meshes region is carried whole: it is `mesh_count * 56` bytes of records followed by an unknown remainder (the
    document's `meshes_unk_buffer`), and replacing records keeps that remainder in place rather than pretending to know
    what it holds.
    """
    header = model.header()
    if header["version"] != MOD_VERSION_SWITCH:
        raise ModelError(f"writing version {header['version']} is not supported")
    if model.variant != "model":
        # the effect containers (effect\mod\...) start their offset table at 0 and lay their blocks out differently;
        # they cannot be written until that variant is decoded, and pretending otherwise is how a load gets broken
        raise ModelError("writing the effect MOD variant is not supported yet")
    offsets = header["offsets"]
    regions = {"bones": model.raw[offsets["bones"]:offsets["groups"]],
               "groups": model.raw[offsets["groups"]:offsets["materials"]],
               "materials": model.raw[offsets["materials"]:offsets["meshes"]],
               "meshes": model.raw[offsets["meshes"]:offsets["vertex_buffer"]],
               "vertex_buffer": model.raw[offsets["vertex_buffer"]:offsets["index_buffer"]],
               "index_buffer": model.raw[offsets["index_buffer"]:offsets["end"]]}
    if mesh_records is not None:
        if len(mesh_records) != (header["mesh_count"] if mesh_count is None else mesh_count):
            raise ModelError("the mesh record count cannot change without the header's mesh_count")
        old = regions["meshes"]
        if mesh_count is None:
            # same part count: start from the existing records so the fields this writer does not name survive (zeroing
            # them erased a record field the decoder needs, and part 0 came back with no positions)
            head = bytearray(old[:MOD_MESH_RECORD_V211 * len(mesh_records)])
            trailer = old[len(head):]
        else:
            # Restructured records still start from exact native templates. Copying only decoded dictionaries loses
            # opaque flags/IDs/pointers whenever the layout is incomplete. A caller can explicitly select another
            # native template; the parsed record's `index` already identifies its source by default.
            head = bytearray()
            for record in mesh_records:
                template = int(record.get("_template_index", record.get("index", 0)))
                if not 0 <= template < header["mesh_count"]:
                    raise ModelError(f"mesh template {template} is outside the original part table")
                start = template * MOD_MESH_RECORD_V211
                head += old[start:start + MOD_MESH_RECORD_V211]
            trailer = old[MOD_MESH_RECORD_V211 * header["mesh_count"]:]
        for index, record in enumerate(mesh_records):
            base = index * MOD_MESH_RECORD_V211
            for name, offset, code in MOD_MESH_FIELDS:
                if name in record:
                    struct.pack_into("<" + code, head, base + offset, record[name])
            packed = struct.unpack_from("<I", head, base + 4)[0]
            for name, shift, mask in (("group_index", 0, 0xFFF), ("material_index", 12, 0xFFF),
                                      ("level_of_detail", 24, 0xFF)):
                if name in record:
                    value = int(record[name])
                    if not 0 <= value <= mask:
                        raise ModelError(f"{name} {value} does not fit its packed mesh field")
                    packed = (packed & ~(mask << shift)) | (value << shift)
            struct.pack_into("<I", head, base + 4, packed)
            # the vertex format is written BIG-endian at +0x14 and is not in MOD_MESH_FIELDS, so a record built from
            # scratch needs it packed here: without it the format reads as 0 and no position decodes (measured).
            if "vertex_format" in record:
                struct.pack_into(">I", head, base + MOD_MESH_FORMAT_OFFSET, int(record["vertex_format"]))
        if mesh_trailer is not None:
            regions["meshes"] = bytes(head) + bytes(mesh_trailer)
        else:
            regions["meshes"] = bytes(head) + trailer
    elif mesh_trailer is not None:
        # keep the existing 56-byte records but replace the per-bone envelope table after them
        keep = MOD_MESH_RECORD_V211 * header["mesh_count"]
        regions["meshes"] = regions["meshes"][:keep] + bytes(mesh_trailer)
    if vertex_buffer is not None:
        regions["vertex_buffer"] = vertex_buffer
    if index_buffer is not None:
        regions["index_buffer"] = index_buffer
    fields = {"vertex_count": header["vertex_count"] if vertex_count is None else vertex_count,
              "face_count": header["face_count"] if face_count is None else face_count,
              "edge_count": header["edge_count"] if edge_count is None else edge_count,
              "vertex_buffer_size": len(regions["vertex_buffer"]),
              "group_count": header["group_count"], "bone_count": header["bone_count"],
              "mesh_count": header["mesh_count"] if mesh_count is None else mesh_count,
              "material_count": header["material_count"]}
    out = bytearray(MOD_MAGIC)
    out += bytes((header["version"], header["revision"]))
    out += struct.pack("<3H", fields["bone_count"], fields["mesh_count"], fields["material_count"])
    out += struct.pack("<3I", fields["vertex_count"], fields["face_count"], fields["edge_count"])
    out += struct.pack("<2I", fields["vertex_buffer_size"], header["vertex_buffer_2_size"])
    out += struct.pack("<I", fields["group_count"])
    out += struct.pack("<I", 0)                                  # the word at 0x24
    # the documented header continues after the offset table: a bounding sphere and box (48 bytes) plus five unknowns
    # (20 bytes) = the 68-byte gap every model has before its first block. Carried verbatim, because nothing here
    # needs to change it and inventing values for it would be exactly the guess that breaks a load.
    header_end = MOD_BLOCK_OFFSETS + 8 * MOD_BLOCKS
    tail = bytearray(model.raw[header_end:offsets["bones"]] if offsets["bones"] >= header_end else b"")
    if mesh_trailer is not None:
        if len(tail) < 68 or len(mesh_trailer) % MOD_WEIGHT_BOUND:
            raise ModelError("the authored envelope table must have complete 144-byte records and its header count")
        envelope_count = len(mesh_trailer) // MOD_WEIGHT_BOUND
        records = mesh_records if mesh_records is not None else model.meshes()
        if sum(record.get("vertex_group_count", 0) for record in records) != envelope_count:
            raise ModelError("the mesh envelope counts disagree with the authored envelope table")
        struct.pack_into("<I", tail, 0xa0 - header_end, envelope_count)
    if bounds is not None:
        # Culling bounds are independent of the preserved skeleton's position quantisation transform.
        if len(tail) < 48:
            raise ModelError("the model has no bounding box to rewrite")
        struct.pack_into("<4f", tail, 0, bounds["sphere"]["x"], bounds["sphere"]["y"], bounds["sphere"]["z"],
                         bounds["sphere"]["r"])
        struct.pack_into("<3f", tail, 16, bounds["min"]["x"], bounds["min"]["y"], bounds["min"]["z"])
        struct.pack_into("<3f", tail, 32, bounds["max"]["x"], bounds["max"]["y"], bounds["max"]["z"])
    tail = bytes(tail)
    running = header_end + len(tail)
    new_offsets = []
    for name in ("bones", "groups", "materials", "meshes", "vertex_buffer", "index_buffer"):
        new_offsets.append(running)
        running += len(regions[name])
    new_offsets.append(running)                                  # `end`
    for off in new_offsets:
        out += struct.pack("<Q", off)
    out += tail
    for name in ("bones", "groups", "materials", "meshes", "vertex_buffer", "index_buffer"):
        out += regions[name]
    out += model.raw[offsets["end"]:]                            # the four-byte trailer every model carries
    return bytes(out)


def build_mod(model: ModFile) -> bytes:
    """Re-emit the container. Unchanged, this is byte-identical to what was parsed."""
    if len(model.offsets) != MOD_BLOCKS:
        raise ModelError(f"a MOD has {MOD_BLOCKS} block offsets")
    return model.raw


def roundtrip_mod(data: bytes) -> bytes:
    return build_mod(parse_mod(data))


def roundtrip(data: bytes) -> bytes:
    """parse then build: the bytes a writer produces for an unchanged model."""
    return build(parse(data))
