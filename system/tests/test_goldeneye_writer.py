"""GoldenEye 007 (Europe) Z-file writer tests.

Run from the repository root (system/):
    python -m pytest tests/test_goldeneye_writer.py -v

Requires the normalised PAL z64 (sha256 40ff3643...) at
artifacts/source/007_GoldenEye_Europe_norm.z64 (see gbox/goldeneye_inventory.py).
"""
import hashlib
import struct
from pathlib import Path

import pytest

from gbox.goldeneye_files import GoldenEyeROM, GoldenEyeFormatError
from gbox.goldeneye_writer import (ZFile, parse, serialize, verify_coverage,
                                   edit_geometry, RECORD_SIZES)
from gbox import goldeneye_reader as gr

ROM = Path(__file__).resolve().parent.parent / "artifacts" / "source" / "007_GoldenEye_Europe_norm.z64"

pytestmark = pytest.mark.skipif(not ROM.exists(), reason="normalised PAL z64 not present")


@pytest.fixture(scope="module")
def ge():
    rom = ROM.read_bytes()
    assert hashlib.sha256(rom).hexdigest() == gr.PAL_Z64_SHA256
    return GoldenEyeROM.from_bytes(rom)


def test_record_sizes_match_decomp():
    """Record sizes are the decomp bondtypes.h ModelRoData_* sizes."""
    assert RECORD_SIZES == {0x01: 0x10, 0x02: 0x1C, 0x04: 0x14, 0x08: 0x10,
                            0x09: 0x24, 0x0A: 0x1C, 0x0D: 0x20, 0x12: 0x08,
                            0x15: 0x14, 0x17: 0x02, 0x18: 0x20}
    # 0x17 is HeadPlaceholderRecord (u16 RwDataIndex), NOT the 32-byte Op17Record
    assert RECORD_SIZES[0x17] == 0x02


def test_csuitbondz_noop_roundtrip_sha(ge):
    """CsuitbondZ re-serialises byte-identically (pinned inflated sha256)."""
    zf = parse(ge, "CsuitbondZ")
    out = serialize(zf)
    assert out == zf.original
    assert hashlib.sha256(out).hexdigest() == \
        "521bc97bbdd7787fa74f2fda73bc2addb7732810de6301d74c55a1be7c8a7afa"
    # coverage: any uncovered bytes must be zero alignment padding, never a
    # missed (non-zero) blob
    for s, e in verify_coverage(zf):
        assert zf.original[s:e] == b"\x00" * (e - s)


def test_all_bodies_noop_roundtrip(ge):
    """Every PAL body/head file round-trips byte-identically, and the blob map
    claims every byte (no non-zero gaps) -- the writer's universal no-op proof."""
    bodies = ge.body_table()
    assert len(bodies) == 80
    for b in bodies:
        zf = parse(ge, b.filename)
        out = serialize(zf)
        assert out == zf.original, f"{b.filename}: no-op roundtrip not byte-identical"
        for s, e in verify_coverage(zf):
            assert zf.original[s:e] == b"\x00" * (e - s), \
                f"{b.filename}: non-zero gap 0x{s:X}-0x{e:X} (missed blob type)"


def test_node_data_pointers_recomputed(ge):
    """serialize recomputes each node's seg-5 Data pointer from the blob layout."""
    zf = parse(ge, "CsuitbondZ")
    for off in zf.node_offsets:
        raw = serialize(zf)[off:off + 0x18]
        dptr = struct.unpack_from(">I", raw, 4)[0]
        rec = zf.record_blob.get(off)
        expected = (0x05000000 + rec.start) if rec else \
            struct.unpack_from(">I", zf.original, off + 4)[0]
        assert dptr == expected


def test_geometry_edit_roundtrip(ge):
    """A changed vertex re-serialises and re-parses with the change reflected.

    This is the writer's in-place 'changed donor' primitive: the torso mesh's
    first vertex x is bumped by +5, everything else stays byte-identical."""
    zf = parse(ge, "CsuitbondZ")
    # the torso node is the op-0x18 node with the most render vertices
    nodes = gr.parse_nodes(zf.original, zf.root_offset)
    torso = max((n for n in nodes if n.op == 0x18), key=lambda n: n.record["num_vertices"])
    verts_blob = next(b for b in zf.blobs
                      if b.node_offset == torso.offset and b.kind == "verts")
    nv = len(verts_blob.data) // 0x10
    assert nv == 97

    x_old = struct.unpack_from(">h", verts_blob.data, 0)[0]
    new_verts = bytearray(verts_blob.data)
    struct.pack_into(">h", new_verts, 0, x_old + 5)
    edited = edit_geometry(zf, torso.offset, verts=bytes(new_verts))

    # exactly one blob changed, and only its first vertex
    assert edited != zf.original
    assert edited[:verts_blob.start] == zf.original[:verts_blob.start]
    assert edited[verts_blob.end:] == zf.original[verts_blob.end:]
    assert struct.unpack_from(">h", edited, verts_blob.start)[0] == x_old + 5

    # the edited file still parses as the full CsuitbondZ model
    reparsed = gr.parse_nodes(edited, zf.root_offset)
    assert len(reparsed) == 79
    rt = next(n for n in reparsed if n.offset == torso.offset)
    assert rt.record["num_vertices"] == 97
    assert rt.vertices[0].x == x_old + 5
    # triangle decode still intact (619 render triangles)
    vnodes = [n for n in reparsed if n.op == 0x18]
    assert sum(len(n.triangles) for n in vnodes) == 619


def test_edit_rejects_oversize_replacement(ge):
    """A replacement longer than its slot raises GoldenEyeFormatError."""
    zf = parse(ge, "CsuitbondZ")
    nodes = gr.parse_nodes(zf.original, zf.root_offset)
    torso = max((n for n in nodes if n.op == 0x18), key=lambda n: n.record["num_vertices"])
    verts_blob = next(b for b in zf.blobs
                      if b.node_offset == torso.offset and b.kind == "verts")
    with pytest.raises(GoldenEyeFormatError):
        edit_geometry(zf, torso.offset, verts=verts_blob.data + b"\x00" * 0x10)


def test_parse_is_reentrant(ge):
    """parse/serialize are pure over the ROM: two passes give identical bytes."""
    a = serialize(parse(ge, "CnatalyaZ"))
    b = serialize(parse(ge, "CnatalyaZ"))
    assert a == b
