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
                                   edit_geometry, RECORD_SIZES,
                                   relayout, rarezip_compress, splice_file,
                                   cast_swap)
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


# -- writer(2): blob re-layout, rarezip recompression, ROM splice, cast swap --

def _torso(nodes):
    return max((n for n in nodes if n.op == 0x18),
               key=lambda n: n.record.get("num_vertices", 0))


def _geom_blobs(zf, node_offset):
    return {b.kind: b.data for b in zf.blobs
            if b.node_offset == node_offset
            and b.kind in ("verts", "collision", "point_usage",
                           "primary_dl", "secondary_dl")}


def test_relayout_noop_byte_identical(ge):
    """relayout with no replacements reproduces every body/head file exactly."""
    for b in ge.body_table():
        zf = parse(ge, b.filename)
        assert relayout(zf) == zf.original, b.filename


def test_relayout_larger_donor_fits(ge):
    """A donor torso larger than the target slot re-packs with correct pointers.

    CnatalyaZ's 423-vertex torso (199 tris) replaces CsuitbondZ's 97-vertex
    torso (67 tris): the file grows, every seg-5 pointer is recomputed, and the
    result re-parses with the donor geometry and the rest of the model intact.
    """
    zf_t = parse(ge, "CsuitbondZ")
    zf_d = parse(ge, "CnatalyaZ")
    torso_t = _torso(gr.parse_nodes(zf_t.original, zf_t.root_offset))
    torso_d = _torso(gr.parse_nodes(zf_d.original, zf_d.root_offset))
    assert torso_d.record["num_vertices"] > torso_t.record["num_vertices"]

    new_file = relayout(zf_t, {torso_t.offset: _geom_blobs(zf_d, torso_d.offset)})
    assert len(new_file) > len(zf_t.original)

    nodes = gr.parse_nodes(new_file, zf_t.root_offset)
    assert len(nodes) == 79
    t = next(n for n in nodes if n.offset == torso_t.offset)
    assert len(t.vertices) == 423
    assert len(t.collision_vertices) == 103
    assert len(t.triangles) == 199
    # 619 original render triangles - 67 target torso + 199 donor torso
    assert sum(len(n.triangles) for n in nodes if n.op == 0x18) == 751


def test_rarezip_roundtrip(ge):
    """rarezip_compress is the exact inverse of rarezip_inflate."""
    from gbox.goldeneye_files import rarezip_inflate
    data = ge.read_file("CsuitbondZ")
    c = rarezip_compress(data)
    assert c[:2] == b"\x11\x72"
    rt, used = rarezip_inflate(c, 0)
    assert used == len(c)
    assert rt == data


def test_splice_noop_roundtrip_and_budget(ge):
    """A no-op splice re-reads identically; an oversize block is refused."""
    data = ge.read_file("CsuitbondZ")
    rom = splice_file(ge, "CsuitbondZ", data)
    assert GoldenEyeROM.from_bytes(rom).read_file("CsuitbondZ") == data
    # incompressible padding guarantees the recompressed block exceeds the slot
    big = data + bytes((i * 37 + 11) & 0xFF for i in range(16384))
    with pytest.raises(GoldenEyeFormatError):
        splice_file(ge, "CsuitbondZ", big)


def test_cast_swap_changed_donor(ge):
    """A real changed-donor swap: CsuitbondZ's torso becomes CgreyguardZ's.

    The spliced ROM re-reads CsuitbondZ with the donor's 60-vertex/43-triangle
    torso in place of the native 97-vertex torso, the other 24 meshes and 79
    nodes are intact, and the donor file is untouched.
    """
    new_rom, meta = cast_swap(ge, "CsuitbondZ", "CgreyguardZ")
    assert meta["donor_vertices"] == 60 and meta["target_vertices"] == 97
    assert meta["compressed_after"] <= meta["file_slot"]
    assert meta["inflated_after"] < meta["inflated_before"]  # smaller donor

    ge2 = GoldenEyeROM.from_bytes(new_rom)
    zf = parse(ge2, "CsuitbondZ")
    nodes = gr.parse_nodes(zf.original, zf.root_offset)
    assert len(nodes) == 79
    torso = next(n for n in nodes if n.offset == int(meta["target_torso_node"], 16))
    assert len(torso.vertices) == 60
    assert len(torso.triangles) == 43
    # 619 - 67 (native torso) + 43 (donor torso)
    assert sum(len(n.triangles) for n in nodes if n.op == 0x18) == 595
    # the donor body file is unchanged in the spliced ROM
    assert ge2.read_file("CgreyguardZ") == ge.read_file("CgreyguardZ")


def test_cast_swap_rejects_too_large_donor(ge):
    """CnatalyaZ's 423-vertex torso exceeds CsuitbondZ's file-table slot."""
    with pytest.raises(GoldenEyeFormatError):
        cast_swap(ge, "CsuitbondZ", "CnatalyaZ")
