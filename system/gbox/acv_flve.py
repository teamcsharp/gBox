"""Bounded FLVE (FLVER-family, big-endian Xbox 360) header probe for Armored Core V.

Observed header (all big-endian, verified on owned-ISO samples):
0x00 'FLVE', 0x04 'R\\0' 'B\\0' (B = big-endian), 0x08 version (0x20009),
0x0C data_offset, 0x10 data_size, 0x14 dummy_count, 0x18 material_count,
0x1C bone_count, 0x20 mesh_count, 0x24 vertex_buffer_count,
0x28 bbox min xyz, 0x34 bbox max xyz (floats), 0x40 face_count,
0x44 total_face_count, 0x48 index_size_bits (u8, 16/32).
Counts are bounds-checked; this is a header probe, not a mesh reader.
"""
from __future__ import annotations

import math
import struct

HEADER_SIZE = 0x50


def parse_flve_header(buf: bytes) -> dict:
    if len(buf) < HEADER_SIZE or buf[:4] != b"FLVE":
        raise ValueError("not FLVE")
    if buf[5:6] != b"\0" or buf[6:7] != b"B":
        raise ValueError("unsupported endianness marker %r" % buf[4:8])
    (version, data_off, data_size, dummies, materials, bones, meshes,
     vbufs) = struct.unpack_from(">8I", buf, 8)
    bbox = struct.unpack_from(">6f", buf, 0x28)
    faces, total_faces = struct.unpack_from(">II", buf, 0x40)
    index_bits = buf[0x48]
    if not all(math.isfinite(v) for v in bbox):
        raise ValueError("non-finite bbox")
    if any(bbox[i] > bbox[i + 3] for i in range(3)):
        raise ValueError("inverted bbox")
    if data_off + data_size > len(buf) or data_off < HEADER_SIZE:
        raise ValueError("data region out of range")
    if max(dummies, materials, bones, meshes, vbufs) > 4096:
        raise ValueError("implausible counts")
    if index_bits not in (0, 8, 16, 32):
        raise ValueError("bad index size")
    return {"version": version, "data_offset": data_off, "data_size": data_size,
            "dummy_count": dummies, "material_count": materials, "bone_count": bones,
            "mesh_count": meshes, "vertex_buffer_count": vbufs,
            "bbox_min": bbox[:3], "bbox_max": bbox[3:], "face_count": faces,
            "total_face_count": total_faces, "index_bits": index_bits}
