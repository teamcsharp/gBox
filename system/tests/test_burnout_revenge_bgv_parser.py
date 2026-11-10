"""Tests for the Burnout Revenge .bgv geometry parser (gbox.burnout_revenge_bgv).

These are round-trip and validation tests built on the documented format (big-endian
vertex/index soup wrapped in zlib, magic 0x78 0xda). They run without the owned disc:
build_bgv() is a deterministic serializer, so a real serialize -> parse round-trip is
exercised, plus marker/index/boundary failure modes. When a real .bgv from the owned
build is available it should also parse — that is the acceptance the remote run must
add (read the actual bytes and assert vertex/index counts match a manual inspect).
"""

import zlib

import pytest

from gbox.burnout_revenge_bgv import (
    BGVError,
    BGVGeometry,
    build_bgv,
    build_bgv_compressed,
    parse_bgv,
    read_bgv,
)


def _sample():
    pos = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (1.0, 1.0, 0.0),
    ]
    nrm = [(0.0, 0.0, 1.0)] * 4
    idx = [0, 1, 2, 1, 3, 2]
    return pos, nrm, idx


def test_roundtrip_decompressed():
    pos, nrm, idx = _sample()
    g = parse_bgv(build_bgv(pos, nrm, idx))
    assert g.marker == 0x00000025
    assert g.vertex_count == 4
    assert g.index_count == 6
    assert g.positions == pos
    assert g.normals == nrm
    assert g.indices == idx


def test_read_bgv_accepts_zlib_stream():
    pos, nrm, idx = _sample()
    blob = build_bgv_compressed(pos, nrm, idx)
    assert blob[:2] == b"\x78\xda"  # the observed on-disc .bgv magic
    g = read_bgv(blob)
    assert g.positions == pos and g.indices == idx


def test_read_bgv_decompressed_passthrough():
    pos, nrm, idx = _sample()
    # An already-decompressed blob (not a zlib stream) must also parse.
    g = read_bgv(build_bgv(pos, nrm, idx))
    assert g.vertex_count == 4 and g.index_count == 6


def test_empty_index_list():
    pos = [(0.0, 0.0, 0.0), (1.0, 1.0, 1.0)]
    nrm = [(0.0, 0.0, 1.0), (0.0, 1.0, 0.0)]
    g = parse_bgv(build_bgv(pos, nrm, []))
    assert g.vertex_count == 2 and g.index_count == 0
    assert g.indices == []


def test_bad_marker_raises():
    with pytest.raises(BGVError, match="format marker"):
        parse_bgv(b"\xde\xad\xbe\xef" + b"\x00" * 40)


def test_short_header_raises():
    with pytest.raises(BGVError, match="too short"):
        parse_bgv(b"\x00\x00\x00\x25\x00\x00")


def test_truncated_vertices_raise():
    # Header claims 10 vertices but body is too short.
    blob = build_bgv([(0.0, 0.0, 0.0)], [(0.0, 0.0, 1.0)], [0])
    import struct
    bad = struct.pack(">II", 0x00000025, 10) + blob[8:]
    with pytest.raises(BGVError, match="too short for"):
        parse_bgv(bad)


def test_out_of_range_index_raises():
    pos = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
    nrm = [(0.0, 0.0, 1.0), (0.0, 0.0, 1.0)]
    with pytest.raises(BGVError, match="out of range"):
        parse_bgv(build_bgv(pos, nrm, [0, 1, 5]))


def test_index_count_mismatch_raises():
    pos = [(0.0, 0.0, 0.0)]
    nrm = [(0.0, 0.0, 1.0)]
    blob = build_bgv(pos, nrm, [0])
    # Corrupt the trailing declared count to not match the index bytes.
    import struct
    blob = blob[:-4] + struct.pack(">I", 3)
    with pytest.raises(BGVError, match="index count mismatch"):
        parse_bgv(blob)


def test_corrupt_zlib_raises():
    with pytest.raises(BGVError, match="zlib"):
        read_bgv(b"\x78\xda broken")


def test_validate_index_range_helper():
    pos, nrm, idx = _sample()
    g = BGVGeometry(0x00000025, pos, nrm, [0, 99])
    with pytest.raises(BGVError, match="out of range"):
        g.validate_index_range()
    # A valid one passes silently.
    BGVGeometry(0x00000025, pos, nrm, idx).validate_index_range()
