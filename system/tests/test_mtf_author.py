"""Authoring a one-mesh MTF model from decoded parts: the table and envelope rules that make it load."""
import struct

import pytest

from gbox import mtf_author, mt_model


def make_target(meshes=2):
    """A small version-211 MOD with `meshes` triangles, one material and one bone per vertex."""
    bones = 2
    groups = 1
    materials = 1
    stride = mtf_author.ONE_BONE_STRIDE
    bounds = ((0.0, 50.0, 0.0, 60.0), (-40.0, 0.0, -40.0, 0.0), (40.0, 100.0, 40.0, 0.0))
    header_size = 0x28 + 8 * mt_model.MOD_BLOCKS
    tail = struct.pack("<4f", *bounds[0]) + struct.pack("<4f", *bounds[1]) + struct.pack("<4f", *bounds[2])
    tail += b"\x00" * (68 - len(tail))
    bone_block = b"\x00" * (bones * mt_model.MOD_BONE_RECORD) + bytes(256)
    group_block = b"\x00" * (groups * 32)
    material_block = b"\x00" * (materials * 128)
    records = bytearray()
    vertices = bytearray()
    indices = bytearray()
    vertex_offset = 0
    face_index = 0
    for index in range(meshes):
        record = bytearray(mt_model.MOD_MESH_RECORD_V211)
        struct.pack_into("<H", record, 0x00, 0xFFFF)
        struct.pack_into("<H", record, 0x02, 3)
        record[0x05] = 0
        record[0x07] = 1  # packed LOD mask: bit zero selects the highest-detail level
        record[0x0A] = stride
        struct.pack_into("<I", record, 0x10, vertex_offset)
        struct.pack_into(">I", record, 0x14, mtf_author.ONE_BONE_FORMAT)
        struct.pack_into("<I", record, 0x18, face_index)
        struct.pack_into("<I", record, 0x1C, 3)
        record[0x25] = 1
        struct.pack_into("<H", record, 0x28, 0)
        struct.pack_into("<H", record, 0x2A, 2)
        records += record
        z = float(index * 10)
        for point, bone in (((-1.0 + z, 0.0, 0.0), 0), ((1.0 + z, 0.0, 0.0), 1), ((0.0 + z, 2.0, 0.0), 0)):
            vertices += mt_model.pack_vertices([{"position": point, "normal": (0.0, 1.0, 0.0),
                                                 "uv": (0.5, 0.5), "bones": [bone], "bounds": {
                                                     "sphere": {"x": 0, "y": 0, "z": 0, "r": 60},
                                                     "min": {"x": bounds[1][0], "y": bounds[1][1], "z": bounds[1][2]},
                                                     "max": {"x": bounds[2][0], "y": bounds[2][1], "z": bounds[2][2]}},
                                                 }], mtf_author.ONE_BONE_FORMAT, stride)
        indices += struct.pack("<4H", 0, 1, 2, 0xFFFF)
        vertex_offset += 3 * stride
        face_index += 4
    trailer = mtf_author.pack_weight_bound(0, [(0.0, 0.0, 0.0), (1.0, 1.0, 1.0)])
    trailer += mtf_author.pack_weight_bound(1, [(2.0, 2.0, 2.0)])
    blocks = (bone_block, group_block, material_block, bytes(records) + trailer, bytes(vertices), bytes(indices))
    offsets = [header_size + len(tail)]
    for block in blocks:
        offsets.append(offsets[-1] + len(block))
    out = bytearray(mt_model.MOD_MAGIC) + bytes((mt_model.MOD_VERSION_SWITCH, 0))
    out += struct.pack("<3H", bones, meshes, materials)
    out += struct.pack("<3I", meshes * 3, meshes * 4, 0)
    out += struct.pack("<2I", len(vertices), 0)
    out += struct.pack("<I", groups)
    out += struct.pack("<I", 0)
    for off in offsets:
        out += struct.pack("<Q", off)
    out += tail
    for block in blocks:
        out += block
    return bytes(out)


def test_combine_reads_every_decodable_mesh_and_keeps_dominant_bones():
    model = mt_model.parse_mod(make_target(2))
    combined = mtf_author.combine(model)
    assert len(combined["triangles"]) == 2
    assert len(combined["vertices"]) == 6
    assert combined["used_bones"] == [0, 1]
    assert combined["vertices"][0]["bones"] == [0]
    assert combined["vertices"][1]["bones"] == [1]


def test_one_mesh_build_writes_the_table_and_an_envelope_per_bone():
    model = mt_model.parse_mod(make_target(2))
    combined = mtf_author.combine(model)
    built = mtf_author.build_one_mesh(model, combined["vertices"], combined["triangles"], material_index=0)
    written = mt_model.parse_mod(built)
    assert written.header()["mesh_count"] == 1
    assert written.header()["vertex_count"] == 6
    assert written.header()["face_count"] == 8
    assert written.header()["polygon_count"] == 2
    assert written.header()["mesh_count"] == 1
    assert written.split_valid() is True
    records = written.meshes()
    assert records[0]["vertex_group_count"] == 2
    bounds = written.weight_bounds()
    assert [row["bone"] for row in bounds] == [0, 1]
    assert written.header()["weight_bound_count"] == 2
    assert written.header()["offsets"]["vertex_buffer"] - written.header()["offsets"]["meshes"] == 56 + 2 * 144


def test_a_padded_mesh_count_keeps_the_slot_shape_with_empty_records():
    model = mt_model.parse_mod(make_target(2))
    combined = mtf_author.combine(model)
    built = mtf_author.build_one_mesh(model, combined["vertices"], combined["triangles"], material_index=0, mesh_count=2)
    written = mt_model.parse_mod(built)
    assert written.header()["mesh_count"] == 2
    assert written.header()["vertex_count"] == 6
    assert written.header()["face_count"] == 9          # real 8 + one empty separator per extra record
    assert written.split_valid() is True
    records = written.meshes()
    assert records[0]["vertex_count"] == 6 and records[0]["face_count"] == 7
    assert records[1]["vertex_count"] == 0 and records[1]["face_count"] == 0
    assert records[1]["vertex_group_count"] == 0


def test_a_partitioned_model_keeps_the_part_count_with_real_geometry_in_every_record():
    model = mt_model.parse_mod(make_target(2))
    combined = mtf_author.combine(model)
    built = mtf_author.build_partitioned(model, combined["vertices"], combined["triangles"], part_count=2)
    written = mt_model.parse_mod(built)
    assert written.header()["mesh_count"] == 2
    assert written.header()["vertex_count"] == 6
    assert written.split_valid() is True
    records = written.meshes()
    assert all(r["vertex_count"] > 0 for r in records)
    assert sum(r["face_count"] for r in records) + 2 == written.header()["face_count"]
    assert sum(r["vertex_group_count"] for r in records) * 144 == (
        written.header()["offsets"]["vertex_buffer"] - written.header()["offsets"]["meshes"] - 56 * 2)
    assert all(r["vertex_index"] == 0 for r in records)  # independent bases have local indices
    assert all(r["vertex_group_count"] == 2 for r in records)  # both encoded bone IDs have local envelopes
    assert written.header()["weight_bound_count"] == sum(r["vertex_group_count"] for r in records)
    assert written.positions(0) == model.positions(0)
    assert written.positions(1) == model.positions(1)
    assert mtf_author.combine(written)["triangles"] == [(0, 1, 2), (3, 4, 5)]


def test_a_one_mesh_model_keeps_the_target_skeleton_and_material_table():
    model = mt_model.parse_mod(make_target(2))
    combined = mtf_author.combine(model)
    built = mtf_author.build_one_mesh(model, combined["vertices"], combined["triangles"])
    written = mt_model.parse_mod(built)
    assert written.header()["bone_count"] == model.header()["bone_count"]
    assert written.header()["material_count"] == model.header()["material_count"]
    assert len(written.raw[written.header()["offsets"]["bones"]:written.header()["offsets"]["groups"]]) == \
        len(model.raw[model.header()["offsets"]["bones"]:model.header()["offsets"]["groups"]])


def test_restructured_mesh_clones_the_exact_selected_native_template():
    raw = bytearray(make_target(2))
    start = mt_model.parse_mod(raw).header()["offsets"]["meshes"] + 56
    raw[start + 0x2c:start + 0x38] = b"opaque-flags"
    struct.pack_into("<H", raw, start + 0x26, 134)
    model = mt_model.parse_mod(raw)
    combined = mtf_author.combine(model)
    output = mtf_author.build_one_mesh(model, combined["vertices"], combined["triangles"], template_index=1)
    written = mt_model.parse_mod(output)
    new_start = written.header()["offsets"]["meshes"]
    assert output[new_start + 0x2c:new_start + 0x38] == b"opaque-flags"
    assert written.meshes()[0]["mesh_id"] == 134


def test_replace_archive_model_updates_the_entry_tag_to_the_new_uncompressed_size():
    from gbox import mt_arc
    source = mt_arc.build(mt_arc.Arc(version=7, entries=[mt_arc.Entry(
        name="pawn\\pl\\pl00\\model\\pl0000", hash=mt_arc.ARC_CONST if hasattr(mt_arc, "ARC_CONST") else 0x241F5DEB,
        tag=0x00700000 | 4, size=0, offset=0, data=b"OLD!")]))
    target = mt_model.parse_mod(make_target(1))
    model = mtf_author.build_one_mesh(target,
                                      [{"position": (0.0, 0.0, 0.0), "normal": (0.0, 1.0, 0.0),
                                        "uv": (0.0, 0.0), "bones": [0], "bone": 0, "bounds": target.bounds()}],
                                      [(0, 0, 0)])
    out = mtf_author.replace_archive_model(source, 0, model)
    parsed = mt_arc.parse(out)
    assert parsed.entries[0].tag & 0x00FFFFFF == len(model)
    assert parsed.entries[0].data == zlib_compress(model)


def zlib_compress(data):
    import zlib
    return zlib.compress(data, 6)


def import_triangle():
    return [{"position": p, "normal": (0., 1., 0.), "uv": (0.25, 0.75), "bones": [99], "weights": [1.]}
            for p in ((-10., 20., 0.), (10., 20., 0.), (0., 40., 0.))]


def test_same_table_import_preserves_tables_skin_and_fixed_allocations():
    target = mt_model.parse_mod(make_target(2))
    raw, receipt = mtf_author.replace_topology(target, import_triangle(), [(0, 1, 2)])
    changed = mt_model.parse_mod(raw)
    vertex_start = target.header()["offsets"]["vertex_buffer"]
    assert raw[:vertex_start] == target.raw[:vertex_start]
    assert len(raw) == len(target.raw)
    assert changed.meshes() == target.meshes()
    assert changed.bone_ids(0) == target.bone_ids(0)  # source bone 99 must not overwrite target animation binding
    assert changed.positions(0)[0] == pytest.approx((-10., 20., 0.), abs=0.004)
    assert mtf_author.mesh_triangles(changed, 0) == [(0, 1, 2)]
    assert mtf_author.mesh_triangles(changed, 1) == []  # no leftover stock triangles in this LOD
    assert receipt["triangles"] == 1 and receipt["dropped_triangles"] == 0
    assert receipt["live_verified"] is False


def test_same_table_import_checks_index_capacity_even_when_vertices_are_reused():
    target = mt_model.parse_mod(make_target(2))
    with pytest.raises(mtf_author.AuthorError, match="vertex/index capacity"):
        mtf_author.replace_topology(target, import_triangle(), [(0, 1, 2)] * 3)


def test_same_table_import_uses_global_indices_and_shared_vertex_base():
    raw = bytearray(make_target(2))
    header = mt_model.parse_mod(raw).header()
    record = header["offsets"]["meshes"] + 56
    struct.pack_into("<I", raw, record + 0x0c, 3)
    struct.pack_into("<I", raw, record + 0x10, 0)
    struct.pack_into("<4H", raw, header["offsets"]["index_buffer"] + 8, 3, 4, 5, 0xFFFF)
    target = mt_model.parse_mod(raw)
    vertices = import_triangle() + [v | {"position": (v["position"][0] + 15., v["position"][1], 10.)}
                                    for v in import_triangle()]
    out, _ = mtf_author.replace_topology(target, vertices, [(0, 1, 2), (3, 4, 5)])
    written = mt_model.parse_mod(out)
    assert mtf_author.mesh_triangles(written, 1) == [(3, 4, 5)]
    assert written.positions(0)[0] == pytest.approx((-10., 20., 0.), abs=0.004)
    assert written.positions(1)[0] == pytest.approx((5., 20., 10.), abs=0.004)


def test_same_table_import_leaves_other_lod_geometry_untouched():
    raw = bytearray(make_target(2))
    header = mt_model.parse_mod(raw).header()
    raw[header["offsets"]["meshes"] + 56 + 0x07] = 2
    target = mt_model.parse_mod(raw)
    out, _ = mtf_author.replace_topology(target, import_triangle(), [(0, 1, 2)])
    written = mt_model.parse_mod(out)
    assert written.mesh_bytes(1) == target.mesh_bytes(1)
    assert mtf_author.mesh_triangles(written, 1) == [(0, 1, 2)]


def test_same_table_import_refuses_overlapping_part_allocations():
    raw = bytearray(make_target(2))
    header = mt_model.parse_mod(raw).header()
    struct.pack_into("<I", raw, header["offsets"]["meshes"] + 56 + 0x18, 0)
    with pytest.raises(mtf_author.AuthorError, match="overlaps"):
        mtf_author.replace_topology(mt_model.parse_mod(raw), import_triangle(), [(0, 1, 2)])


@pytest.mark.parametrize("position", [(float("nan"), 0., 0.), (500., 0., 0.)])
def test_same_table_import_refuses_unencodable_source_positions(position):
    vertices = import_triangle()
    vertices[0]["position"] = position
    with pytest.raises(mtf_author.AuthorError):
        mtf_author.replace_topology(mt_model.parse_mod(make_target(2)), vertices, [(0, 1, 2)])

