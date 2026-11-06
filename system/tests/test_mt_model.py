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
    out += b"\x01\x02\x03\x04"                                  # an opaque geometry tail
    return bytes(out)


def make_mod(vertex_count=100, index_count=150, subs=1, vertex_bytes=None, index_bytes=None,
             blocks=(712, 64, 1152, 3000, None, None)):
    """A synthetic MOD whose block offsets are laid out the way the real ones are."""
    vertex_bytes = 24 * vertex_count if vertex_bytes is None else vertex_bytes
    index_bytes = 2 * index_count if index_bytes is None else index_bytes
    sizes = list(blocks)
    sizes[4] = vertex_bytes
    sizes[5] = index_bytes
    header = 0x28 + 8 * mt_model.MOD_BLOCKS
    offsets = [header + 68]                                     # the real files leave a gap after the header
    for size in sizes:
        offsets.append(offsets[-1] + size)
    offsets = offsets[:7]
    out = bytearray(mt_model.MOD_MAGIC)
    out += struct.pack("<8I", 0x300D3, 0x9000F, vertex_count, index_count, 0, vertex_bytes, 0, subs)
    out += struct.pack("<I", 0)                                 # the word at 0x24, before the offset table at 0x28
    for off in offsets:
        out += struct.pack("<II", off, 0)
    out += b"\xaa" * (offsets[0] - header)                      # the undecoded gap
    out += b"".join(b"\x11" * size for size in sizes)
    out += b"\x00\x00\x00\x00"                                  # the four-byte trailer every file has
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
    struct.pack_into("<I", data, 0x18, 0x99)                    # the constant-block offset no longer points at 0x28
    with pytest.raises(mt_model.ModelError):
        mt_model.parse(bytes(data))


def test_the_geometry_container_round_trips_byte_identically():
    data = make_mod()
    model = mt_model.parse_mod(data)
    assert mt_model.build_mod(model) == data
    assert mt_model.roundtrip_mod(data) == data


def test_the_index_buffer_is_two_bytes_per_index():
    """Measured on 31 real containers: block 5 is the index buffer and header word 0x10 is its count."""
    for index_count in (10, 150, 48300):
        layout = mt_model.parse_mod(make_mod(index_count=index_count)).layout()
        assert layout["index_count"] == index_count
        assert layout["index_block"] == 2 * index_count
        assert layout["index_block_matches"] is True


def test_a_single_submesh_model_reports_an_exact_vertex_stride():
    layout = mt_model.parse_mod(make_mod(vertex_count=100, vertex_bytes=2400, subs=1)).layout()
    assert layout["stride"] == 24.0 and layout["stride_exact"] is True


def test_a_multi_submesh_model_reports_a_fractional_stride_rather_than_guessing():
    """The per-submesh split is not in the header, so a multi-submesh stride must not look exact."""
    layout = mt_model.parse_mod(make_mod(vertex_count=100, vertex_bytes=2450, subs=6)).layout()
    assert layout["stride_exact"] is False


def test_the_two_header_variants_are_both_accepted():
    model = mt_model.parse_mod(make_mod())
    assert model.variant == "model"
    effect = bytearray(make_mod())
    struct.pack_into("<I", effect, mt_model.MOD_BLOCK_OFFSETS, 0)   # effect models start their table at 0
    assert mt_model.parse_mod(bytes(effect)).variant == "effect"
