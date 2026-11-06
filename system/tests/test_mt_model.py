"""The MT Framework model containers: what is decoded, and what a writer can and cannot do yet."""
import struct

import pytest

from gbox import mt_model


def make_mrl(paths=("pawn\\pl\\pl00\\model\\a_BM",), count1=7):
    """A synthetic MRL: the header, the constant block and one 88-byte record per path."""
    out = bytearray(mt_model.MAGIC)
    out += struct.pack("<III", mt_model.VERSION, count1, len(paths))
    out += struct.pack("<6I", 0x7BE0E51F, 0, mt_model.CONST_OFFSET, 0, 0x1234, 0)
    out += struct.pack("<I", mt_model.ARC_CONST)
    out += b"\x00" * (mt_model.HEADER_SIZE - 0x2C)
    for path in paths:
        raw = path.encode("ascii")
        out += raw + b"\x00" + b"\xcd" * (mt_model.PATH_FIELD - len(raw) - 1)
        out += struct.pack("<I", mt_model.ARC_CONST) + b"\x00" * (mt_model.PATH_TAIL - 4)
    out += b"\x01\x02\x03\x04"
    return bytes(out)


def make_mod(meshes=((100, 24),), groups=1, bones=2, materials=1):
    """A synthetic version-211 MOD: header, then groups, materials, mesh records, vertex and index buffers.

    `meshes` is a sequence of (vertex_count, vertex_stride); the header's vertex_count is their sum, so a well-formed
    fixture validates through ModFile.split_valid().
    """
    header_size = 0x28 + 8 * mt_model.MOD_BLOCKS
    bone_block = b"\x00" * (bones * 40)
    group_block = b"\x00" * (groups * 32)
    material_block = b"\x00" * (materials * 32)
    mesh_block = bytearray()
    vertex_total = 0
    for vertex_count, stride in meshes:
        record = bytearray(mt_model.MOD_MESH_RECORD_V211)
        struct.pack_into("<H", record, 0x02, vertex_count)
        record[0x05] = 0
        record[0x06] = 0
        record[0x0A] = stride
        mesh_block += record
        vertex_total += vertex_count * stride
    faces = 30
    vertex_block = b"\x11" * vertex_total
    index_block = b"\x22" * (2 * faces)
    offsets = [header_size]
    for block in (bone_block, group_block, material_block, bytes(mesh_block), vertex_block, index_block):
        offsets.append(offsets[-1] + len(block))
    out = bytearray(mt_model.MOD_MAGIC)
    out += bytes((mt_model.MOD_VERSION_SWITCH, 0))
    out += struct.pack("<3H", bones, len(meshes), materials)
    out += struct.pack("<3I", sum(v for v, _ in meshes), faces, faces * 2)
    out += struct.pack("<2I", vertex_total, 0)
    out += struct.pack("<I", groups)
    out += struct.pack("<I", 0)                       # the word at 0x24
    for off in offsets[:7]:
        out += struct.pack("<Q", off)
    out += bone_block + group_block + material_block + bytes(mesh_block) + vertex_block + index_block
    return bytes(out)


def test_a_model_resource_round_trips_and_reports_its_paths():
    data = make_mrl(paths=("pawn\\pl\\pl00\\model\\a_BM", "pawn\\pl\\pl00\\model\\a_MM"))
    model = mt_model.parse(data)
    assert model.version == mt_model.VERSION
    assert model.paths == ["pawn\\pl\\pl00\\model\\a_BM", "pawn\\pl\\pl00\\model\\a_MM"]
    assert mt_model.build(model) == data


def test_a_texture_payload_is_not_taken_for_a_model():
    with pytest.raises(mt_model.ModelError):
        mt_model.parse(b"TEX\x00" + b"\x00" * 100)


def test_a_model_whose_header_lies_about_its_table_is_refused():
    data = bytearray(make_mrl())
    struct.pack_into("<I", data, 0x18, 0x99)
    with pytest.raises(mt_model.ModelError):
        mt_model.parse(bytes(data))


def test_the_geometry_container_round_trips_byte_identically():
    data = make_mod()
    model = mt_model.parse_mod(data)
    assert mt_model.build_mod(model) == data
    assert mt_model.roundtrip_mod(data) == data


def test_the_header_decodes_with_named_offsets():
    model = mt_model.parse_mod(make_mod(meshes=((100, 24),), groups=2, bones=3, materials=4))
    header = model.header()
    assert header["version"] == mt_model.MOD_VERSION_SWITCH
    assert (header["bone_count"], header["mesh_count"], header["material_count"]) == (3, 1, 4)
    assert header["vertex_count"] == 100 and header["group_count"] == 2
    assert set(header["offsets"]) == set(mt_model.MOD_OFFSET_NAMES)
    offs = header["offsets"]
    assert offs["meshes"] < offs["vertex_buffer"] < offs["index_buffer"] <= offs["end"]


def test_the_mesh_records_are_the_per_part_split():
    """Measured on 31 real models: 56-byte records whose vertex counts sum to the header's vertex_count."""
    model = mt_model.parse_mod(make_mod(meshes=((120, 24), (80, 20), (60, 28))))
    meshes = model.meshes()
    assert [m["vertex_count"] for m in meshes] == [120, 80, 60]
    assert [m["vertex_stride"] for m in meshes] == [24, 20, 28]
    assert model.split_valid() is True


def test_a_split_that_does_not_account_for_every_vertex_is_reported_invalid():
    data = bytearray(make_mod(meshes=((120, 24), (80, 20))))
    header = mt_model.parse_mod(bytes(data)).header()
    # move the header's vertex_count without touching the records
    struct.pack_into("<I", data, 0x0C, header["vertex_count"] + 1)
    assert mt_model.parse_mod(bytes(data)).split_valid() is False


def test_the_index_buffer_is_two_bytes_per_face():
    model = mt_model.parse_mod(make_mod(meshes=((100, 24),)))
    header = model.header()
    index = model.block(5)
    assert len(index) == 2 * header["face_count"]


def test_a_multi_part_model_reports_fractional_or_exact_stride_from_its_records():
    model = mt_model.parse_mod(make_mod(meshes=((100, 24), (50, 28))))
    meshes = model.meshes()
    assert sum(m["vertex_count"] * m["vertex_stride"] for m in meshes) == model.header()["vertex_buffer_size"]


def test_the_two_header_variants_are_both_accepted():
    model = mt_model.parse_mod(make_mod())
    assert model.variant in ("model", "effect")
