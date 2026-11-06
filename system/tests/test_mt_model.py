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


def make_mod(meshes=((100, 24),), groups=1, bones=2, materials=1,
             bounds=((0.0, 50.0, 0.0, 25.0), (-10.0, 0.0, -10.0, 0.0), (10.0, 100.0, 10.0, 0.0))):
    """A synthetic version-211 MOD: header, the bounding tail, then groups, materials, mesh records and buffers.

    `meshes` is a sequence of (vertex_count, vertex_stride); the header's vertex_count is their sum, so a well-formed
    fixture validates through ModFile.split_valid().
    """
    header_size = 0x28 + 8 * mt_model.MOD_BLOCKS
    tail = struct.pack("<4f", *bounds[0]) + struct.pack("<4f", *bounds[1]) + struct.pack("<4f", *bounds[2])
    tail += b"\x00" * (68 - len(tail))
    bone_block = b"\x00" * (bones * mt_model.MOD_BONE_RECORD) + bytes(256)
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
        # the format is a documented FVF written big-endian, and its stride must agree with the record's
        fvf = next(value for value, size in mt_model.MOD_FVF_STRIDES.items() if size == stride)
        record[mt_model.MOD_MESH_FORMAT_OFFSET:mt_model.MOD_MESH_FORMAT_OFFSET + 4] = fvf.to_bytes(4, "big")
        mesh_block += record
        vertex_total += vertex_count * stride
    faces = 30
    vertex_block = b"\x11" * vertex_total
    index_block = b"\x22" * (2 * faces)
    offsets = [header_size + len(tail)]
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
    out += tail
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

def test_the_writer_reassembles_the_container_from_its_parts():
    """Not a copy: the header is built from decoded fields and every offset is recomputed from the block sizes."""
    data = make_mod(meshes=((100, 24), (60, 20)))
    model = mt_model.parse_mod(data)
    assert mt_model.rebuild_mod(model) == data


def test_the_writer_can_replace_the_vertex_buffer_and_the_offsets_follow():
    data = make_mod(meshes=((100, 24),))
    model = mt_model.parse_mod(data)
    bigger = b"\x33" * (100 * 24 + 48)
    out = mt_model.rebuild_mod(model, vertex_buffer=bigger)
    rebuilt = mt_model.parse_mod(out)
    header = rebuilt.header()
    assert header["vertex_buffer_size"] == len(bigger)
    assert rebuilt.block(4) == bigger
    assert header["offsets"]["index_buffer"] > model.header()["offsets"]["index_buffer"]


def test_the_writer_can_replace_a_mesh_record():
    data = make_mod(meshes=((100, 24),))
    model = mt_model.parse_mod(data)
    out = mt_model.rebuild_mod(model, mesh_records=[{"vertex_count": 90, "vertex_stride": 28}])
    record = mt_model.parse_mod(out).meshes()[0]
    assert (record["vertex_count"], record["vertex_stride"]) == (90, 28)


def test_the_writer_refuses_an_undecoded_variant():
    data = bytearray(make_mod())
    struct.pack_into("<Q", data, mt_model.MOD_BLOCK_OFFSETS, 0)     # the effect variant's table starts at 0
    with pytest.raises(mt_model.ModelError):
        mt_model.rebuild_mod(mt_model.parse_mod(bytes(data)))
@pytest.mark.parametrize("value,stride", [
    (0x133098B0, 12), (0x14A07DDB, 16), (0x1580B60C, 20), (0x1C201FC3, 24),
    (0x2000D414, 28), (0x29F0B449, 28), (0x2ED06F92, 32), (0x244042BB, 36),
    (0x23305964, 40), (0x2770CFCB, 48), (0x3DC0552F, 64),
])
def test_a_documented_fvf_names_its_vertex_stride(value, stride):
    assert mt_model.fvf_stride(value) == stride
    assert mt_model.fvf_stride(0xDEADBEEF) is None


def test_a_mesh_record_reports_its_format_and_the_stride_that_format_implies():
    """Measured on 1895 real records: the format sits at +0x14 big-endian and its stride agrees with the record's."""
    model = mt_model.parse_mod(make_mod(meshes=((100, 24), (60, 28))))
    meshes = model.meshes()
    assert [m["vertex_stride"] for m in meshes] == [24, 28]
    assert all(m["format_stride"] == m["vertex_stride"] for m in meshes)
    assert mt_model.fvf_stride(meshes[0]["vertex_format"]) == 24
def test_a_mesh_record_carries_its_place_in_the_vertex_buffer():
    """Measured on 28 models: vertex_offset starts at 0, never decreases, and every part fits inside the buffer."""
    model = mt_model.parse_mod(make_mod(meshes=((100, 24), (60, 20), (40, 28))))
    header = model.header()
    meshes = model.meshes()
    offsets = [m["vertex_offset"] for m in meshes]
    assert offsets[0] == 0 and offsets == sorted(offsets)
    for mesh in meshes:
        assert mesh["vertex_offset"] + mesh["vertex_count"] * mesh["vertex_stride"] <= header["vertex_buffer_size"]
    assert header["vertex_buffer_size"] == sum(m["vertex_count"] * m["vertex_stride"] for m in meshes)
def test_the_model_bounding_box_decodes():
    """Measured on real models: a 186 cm character's box is y 0..187, a grenade's is +-21.5 in x and z."""
    bounds = ((0.0, 50.0, 0.0, 25.0), (-10.0, 0.0, -10.0, 0.0), (10.0, 100.0, 10.0, 0.0))
    model = mt_model.parse_mod(make_mod(bounds=bounds))
    got = model.bounds()
    assert got is not None
    assert got["sphere"] == {"x": 0.0, "y": 50.0, "z": 0.0, "r": 25.0}
    assert got["min"] == {"x": -10.0, "y": 0.0, "z": -10.0}
    assert got["max"] == {"x": 10.0, "y": 100.0, "z": 10.0}
def test_positions_are_dequantised_by_the_model_box():
    """Measured on 903 meshes: box_min + (short / 32767) * box_size puts every vertex inside the model's own box."""
    bounds = {"sphere": {"x": 0.0, "y": 50.0, "z": 0.0, "r": 25.0},
              "min": {"x": -10.0, "y": 0.0, "z": -10.0},
              "max": {"x": 10.0, "y": 100.0, "z": 10.0}}
    # two stride-12 vertices; the first three shorts of each are the position
    data = struct.pack("<12h", 16383, 16383, 16383, 0, 0, 0, 32767, 32767, 32767, 0, 0, 0)
    points = mt_model.decode_positions(data, 0x133098B0, 2, 12, bounds)
    assert len(points) == 2
    # 16383/32767 is 0.49998..., not exactly half, so compare with a tolerance that reflects the quantisation
    assert all(abs(a - b) < 0.01 for a, b in zip(points[0], (0.0, 50.0, 0.0)))
    assert all(abs(a - b) < 0.01 for a, b in zip(points[1], (10.0, 100.0, 10.0)))


def test_float_positions_decode_and_an_unknown_format_does_not():
    """The documented float-position formats are decoded directly; anything else is not guessed at."""
    bounds = {"sphere": {"x": 0.0, "y": 50.0, "z": 0.0, "r": 25.0},
              "min": {"x": -10.0, "y": 0.0, "z": -10.0},
              "max": {"x": 10.0, "y": 100.0, "z": 10.0}}
    data = struct.pack("<3f", 1.5, 2.5, 3.5) + b"\x00" * 12
    points = mt_model.decode_positions(data, 0x287029D8, 1, 24, bounds)
    assert points and all(abs(a - b) < 0.001 for a, b in zip(points[0], (1.5, 2.5, 3.5)))
    assert mt_model.decode_positions(data, 0xDEADBEEF, 1, 24, bounds) == []
def test_normals_and_uvs_decode_for_a_confirmed_format():
    """Measured: on formats 0x18b0faa8 / 0x1c201fc3 / 0x2000d414 the normals are unit length on 100% of vertices."""
    vertex = bytearray(20)
    struct.pack_into("<3b", vertex, 8, 0, 127, 0)          # a normal pointing up
    struct.pack_into("<2e", vertex, 16, 0.5, 0.25)         # a uv
    data = bytes(vertex) + b"\x00" * 4                     # one stream; count comes from the caller
    normals = mt_model.decode_normals(data, 0x18B0FAA8, 1, 20)
    uvs = mt_model.decode_uvs(data, 0x18B0FAA8, 1, 20)
    assert normals and abs(normals[0][1] - 1.0) < 0.001 and abs(normals[0][0]) < 0.001
    assert uvs and abs(uvs[0][0] - 0.5) < 0.001 and abs(uvs[0][1] - 0.25) < 0.001


def test_an_unconfirmed_format_returns_no_normals_rather_than_a_guess():
    """0x133098b0's normals decode to unit length on only 39% of vertices, so nothing is claimed for it."""
    assert mt_model.decode_normals(b"\x00" * 96, 0x133098B0, 8, 12) == []
    assert mt_model.decode_uvs(b"\x00" * 96, 0x133098B0, 8, 12) == []
def test_the_index_buffer_is_a_strip_stream_and_triangles_respect_winding():
    """Measured: the buffer holds face_count ushorts, 0xFFFF separates strips, and strips are stitched with degenerates."""
    data = make_mod(meshes=((4, 24),))
    model = mt_model.parse_mod(data)
    header = model.header()
    start = header["offsets"]["index_buffer"]
    raw = bytearray(model.raw)
    # one strip of 4 vertices then a restart then a strip of 3, with a degenerate in the first
    values = [0, 1, 2, 3, 0xFFFF, 2, 1, 0]
    values += [0xFFFF] * (header["face_count"] - len(values))       # padding is restart marks, not vertices
    for i, value in enumerate(values):
        struct.pack_into("<H", raw, start + 2 * i, value)
    model = mt_model.parse_mod(bytes(raw))
    strips = model.triangle_strips()
    assert strips[0] == [0, 1, 2, 3] and strips[1] == [2, 1, 0]
    tris = model.triangles()
    # a strip of four yields two triangles; the odd one swaps its first two vertices, which is what a strip requires
    assert tris[0] == (0, 1, 2) and tris[1] == (2, 1, 3)
    assert tris[2] == (2, 1, 0)                     # the second strip
    assert len(tris) == 3                            # degenerate triangles are dropped


def test_a_mesh_that_cannot_be_decoded_keeps_its_place_in_the_vertex_space():
    """Dropping it would shift every later index; the measured symptom was 3647 out-of-range indices."""
    data = make_mod(meshes=((4, 24), (6, 20)))
    model = mt_model.parse_mod(data)
    points = model.all_positions()
    assert len(points) == sum(m["vertex_count"] for m in model.meshes())
def test_bone_ids_decode_for_every_confirmed_format():
    """Validated against the model's own bone_count: 100% below it on four formats, 28344/28344 on the fifth."""
    cases = [(0x133098B0, 6, struct.pack("<H", 3), 12, (3,)),
             (0x18B0FAA8, 6, struct.pack("<H", 5), 20, (5,)),
             (0x1580B60C, 8, struct.pack("<4B", 1, 2, 3, 4), 20, (1, 2, 3, 4)),
             (0x2000D414, 16, struct.pack("<4B", 9, 8, 7, 6), 28, (9, 8, 7, 6)),
             (0x1C201FC3, 20, struct.pack("<2e", 0.0, 7.0), 24, (0, 7))]
    for fmt, offset, payload, stride, expected in cases:
        data = bytearray(stride)
        data[offset:offset + len(payload)] = payload
        got = mt_model.decode_bone_ids(bytes(data), fmt, 1, stride)
        assert got == [expected], (hex(fmt), got, expected)


def test_an_unconfirmed_format_yields_no_bone_ids():
    assert mt_model.decode_bone_ids(b"\x00" * 64, 0xDEADBEEF, 2, 32) == []
def test_a_vertex_survives_packing_and_decoding():
    """The writer's path: encode a vertex the way a format stores it, then read every component back."""
    bounds = {"sphere": {"x": 0.0, "y": 50.0, "z": 0.0, "r": 25.0},
              "min": {"x": -10.0, "y": 0.0, "z": -10.0},
              "max": {"x": 10.0, "y": 100.0, "z": 10.0}}
    vertex = {"position": (0.0, 50.0, -10.0), "normal": (0.0, 1.0, 0.0), "uv": (0.25, 0.75), "bones": (3,), "bounds": bounds}
    packed = mt_model.pack_vertices([vertex], 0x18B0FAA8, 20)
    assert len(packed) == 20
    position = mt_model.decode_positions(packed, 0x18B0FAA8, 1, 20, bounds)[0]
    assert all(abs(a - b) < 0.01 for a, b in zip(position, vertex["position"]))
    normal = mt_model.decode_normals(packed, 0x18B0FAA8, 1, 20)[0]
    assert abs(normal[1] - 1.0) < 0.01 and abs(normal[0]) < 0.01
    uv = mt_model.decode_uvs(packed, 0x18B0FAA8, 1, 20)[0]
    assert abs(uv[0] - 0.25) < 0.001 and abs(uv[1] - 0.75) < 0.001
    assert mt_model.decode_bone_ids(packed, 0x18B0FAA8, 1, 20) == [(3,)]


def test_packing_refuses_a_short_position_without_bounds():
    with pytest.raises(mt_model.ModelError):
        mt_model.pack_vertices([{"position": (1.0, 2.0, 3.0)}], 0x18B0FAA8, 20)
def test_tangents_and_weights_survive_packing():
    """Measured: tangents decode to unit length on 100% of vertices (6198, 16669, 13594) and round-trip exactly."""
    bounds = {"sphere": {"x": 0.0, "y": 50.0, "z": 0.0, "r": 25.0},
              "min": {"x": -10.0, "y": 0.0, "z": -10.0},
              "max": {"x": 10.0, "y": 100.0, "z": 10.0}}
    vertex = {"position": (0.0, 50.0, 0.0), "normal": (0.0, 1.0, 0.0), "tangent": (1.0, 0.0, 0.0),
              "uv": (0.5, 0.5), "bones": (1, 2, 3, 4), "weights": (0.5, 0.25), "bounds": bounds}
    packed = mt_model.pack_vertices([vertex], 0x2000D414, 28)
    tangent = mt_model.decode_tangents(packed, 0x2000D414, 1, 28)[0]
    assert abs(tangent[0] - 1.0) < 0.01 and abs(tangent[1]) < 0.01
    weights = mt_model.decode_weights(packed, 0x2000D414, 1, 28)[0]
    assert abs(weights[0] - 0.5) < 0.001 and abs(weights[1] - 0.25) < 0.001
    assert mt_model.decode_bone_ids(packed, 0x2000D414, 1, 28) == [(1, 2, 3, 4)]


def test_a_format_without_a_tangent_field_yields_none():
    assert mt_model.decode_tangents(b"\x00" * 40, 0x133098B0, 1, 12) == []
    assert mt_model.decode_weights(b"\x00" * 40, 0x133098B0, 1, 12) == []
def test_a_parts_geometry_can_be_replaced_and_the_container_still_describes_itself():
    """Measured on 11 real models: replacing a part's vertices re-parses, validates, and leaves the other parts untouched."""
    model = mt_model.parse_mod(make_mod(meshes=((4, 24), (6, 20))))
    bounds = model.bounds()
    record = model.meshes()[0]
    vertices = [{"position": (0.0, 10.0 * i, 0.0), "bounds": bounds} for i in range(3)]
    packed = mt_model.pack_vertices(vertices, record["vertex_format"], record["vertex_stride"])
    out = mt_model.replace_part(model.raw, 0, packed, 3, record["vertex_format"], record["vertex_stride"])
    again = mt_model.parse_mod(out)
    assert again.split_valid()
    assert len(again.meshes()) == 2
    assert again.meshes()[0]["vertex_count"] == 3
    assert again.meshes()[1]["vertex_count"] == 6
    # the second part is copied, not re-packed
    assert again.mesh_bytes(1)[0] == model.mesh_bytes(1)[0]
    # the offsets follow the new sizes
    offsets = again.header()["offsets"]
    assert offsets["vertex_buffer"] < offsets["index_buffer"] <= offsets["end"]


def test_replacing_a_part_that_does_not_exist_is_refused():
    model = mt_model.parse_mod(make_mod(meshes=((4, 24),)))
    with pytest.raises(mt_model.ModelError):
        mt_model.replace_part(model.raw, 5, b"", 0, 0x18B0FAA8, 20)
def test_the_skeleton_block_is_a_map_plus_one_record_per_bone():
    """Measured on 12 models: groups_offset - bones_offset == 256 + bone_count * 152, exactly."""
    model = mt_model.parse_mod(make_mod(meshes=((4, 24),), bones=3))
    table = model.bone_table()
    assert table["bone_count"] == 3
    assert table["consistent"] is True
    assert len(table["map"]) == 256
    assert len(table["headers"]) == 3 and all(len(h) == 24 for h in table["headers"])


def test_a_bone_block_of_the_wrong_size_is_reported_rather_than_padded():
    data = make_mod(meshes=((4, 24),), bones=2)
    raw = bytearray(data)
    struct.pack_into("<H", raw, 0x06, 9)                # claim nine bones where the block holds two
    table = mt_model.parse_mod(bytes(raw)).bone_table()
    assert table["consistent"] is False and table["headers"] == []
def test_the_skeleton_is_structure_of_arrays_and_has_one_root():
    """Measured on 22 models: parents in range and exactly one root each, with the matrices at the PS3-documented offsets."""
    model = mt_model.parse_mod(make_mod(meshes=((4, 24),), bones=3))
    table = model.bone_table()
    assert table["bone_count"] == 3
    assert table["consistent"] is True
    assert len(table["headers"]) == 3 and all(len(h) == 24 for h in table["headers"])
    assert len(table["local"]) == 3 and all(len(m) == 64 for m in table["local"])
    assert len(table["inverse_bind"]) == 3 and all(len(m) == 64 for m in table["inverse_bind"])
    assert len(table["parents"]) == 3 and len(table["anim_map"]) == 3
    assert len(table["map"]) == 256


def test_the_bone_block_is_152_bytes_per_bone_and_the_map_follows():
    """24-byte headers + 64-byte local + 64-byte bind = 152 per bone, then the 256-byte map."""
    model = mt_model.parse_mod(make_mod(meshes=((4, 24),), bones=4))
    table = model.bone_table()
    assert table["region"] == 4 * 152 + 256
    assert mt_model.MOD_BONE_RECORD == 152
def test_bone_roles_are_inferred_from_where_the_bones_are():
    """Measured on Chris: height 180.7, span 176.2, head at y 185.1, hands at x +-88.1 on a 187 cm model."""
    model = mt_model.parse_mod(make_mod(meshes=((4, 24),), bones=3))
    roles = model.bone_roles()
    assert roles and "head" in roles and "left_hand" in roles and "right_hand" in roles
    assert roles["height"] >= 0 and roles["span"] >= 0
    assert roles["root"] == roles["hips"]


def test_a_degenerate_skeleton_reports_zero_height_rather_than_inventing_roles():
    """A weapon or a face part has all its bones at the origin: height 0 is the honest answer, not an error."""
    model = mt_model.parse_mod(make_mod(meshes=((4, 24),), bones=2))
    roles = model.bone_roles()
    assert roles["height"] == 0 and roles["span"] == 0
    assert roles["head"] == roles["left_hand"] == roles["right_hand"]