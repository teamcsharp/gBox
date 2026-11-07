"""RE4 Switch (HD) texture descriptors and the compressed `imagepackhd` archive.

Measured 2026-11-07: a character pack's `TPL` slot is not a GameCube TPL but a 96-byte little-endian descriptor with
magic 0x12345678 - and it carries no pixels (a 256x256 CMPR surface is 32 KB; the slot is 96 B), just a texture id.
The pixels live in `bio4/imagepackhd/*.pack.fen`, which is `u32 uncompressed size` + a zlib stream.

These tests pin the descriptor reading, both record classes, and the archive's exact-size check, and they pin the
refusals - the point is that a slot which is not a picture says so instead of being read as an 8x0 image.
"""
import struct
import zlib

import pytest

from gbox import re4hd_tex as T


def descriptor(*, width=128, height=128, fmt=14, tex_id=46, kind_word=0x10, version=1):
    """A 96-byte image descriptor: magic, version, header word, dims+format+offset, then (type, id)."""
    b = bytearray(96)
    struct.pack_into("<I", b, 0x00, T.TPL_MAGIC)
    struct.pack_into("<I", b, 0x04, version)
    struct.pack_into("<I", b, 0x08, 16)
    struct.pack_into("<HH", b, 0x20, width, height)
    struct.pack_into("<I", b, 0x24, fmt)
    struct.pack_into("<I", b, 0x28, T.DESCRIPTOR_HEADER)
    struct.pack_into("<II", b, T.DESCRIPTOR_HEADER, kind_word, tex_id)
    return bytes(b)


def reference(word=104):
    """A reference slot: the same magic, format 0 and no data offset."""
    b = bytearray(224)
    struct.pack_into("<I", b, 0x00, T.TPL_MAGIC)
    struct.pack_into("<I", b, 0x04, 1)
    struct.pack_into("<I", b, 0x08, 16)
    struct.pack_into("<I", b, 0x20, word)
    return bytes(b)


def test_an_image_descriptor_reports_dimensions_format_and_the_texture_id():
    info = T.tex_info(descriptor(width=256, height=128, tex_id=48))
    assert info["kind"] == "image" and info["format"] == "CMPR"
    assert (info["width"], info["height"]) == (256, 128)
    assert info["id"] == 48 and info["payload_type"] == 0x10
    # a 256x128 CMPR surface is 16 KB; the slot is 96 B, so it cannot be carrying it
    assert info["surface_bytes"] == 16384 and info["carries_pixels"] is False
    assert "descriptor only" in info["note"]


def test_a_reference_slot_is_not_read_as_an_eight_by_zero_picture():
    info = T.tex_info(reference())
    assert info["kind"] == "reference"
    assert "width" not in info and "height" not in info
    assert info["word_0020"] == 104


def test_a_gamecube_tpl_is_named_as_such_instead_of_being_parsed():
    gc = bytearray(64)
    struct.pack_into(">I", gc, 0, 0x0020AF30)
    with pytest.raises(T.TexError, match="GameCube TPL"):
        T.tex_info(bytes(gc))


def test_an_unknown_magic_and_a_short_slot_are_refused():
    with pytest.raises(T.TexError, match="not an HD texture descriptor"):
        T.tex_info(b"\x00" * 96)
    with pytest.raises(T.TexError, match="too short"):
        T.tex_info(b"\x78\x56\x34\x12")


def test_an_image_descriptor_pointing_outside_its_slot_reports_no_id():
    bad = bytearray(descriptor())
    struct.pack_into("<I", bad, 0x28, 0x900)
    info = T.tex_info(bytes(bad))
    assert info["kind"] == "image" and info.get("id") is None
    assert "outside the slot" in info["note"]


def fen(count_a, count_b, offsets, *, pad_to=0x400):
    """A synthetic FEN: u32 size + zlib body (two counts, then u64 offsets)."""
    body = bytearray(struct.pack("<II", count_a, count_b))
    for o in offsets:
        body += struct.pack("<Q", o)
    while len(body) < pad_to:
        body += b"\0"
    stream = zlib.compress(bytes(body), 9)
    return struct.pack("<I", len(body)) + stream, bytes(body)


def test_the_fen_archive_decompresses_and_verifies_its_declared_size():
    blob, body = fen(6, 3, [0x70, 0x100, 0x200])
    out = T.fen_open(blob)
    assert out["declared_size"] == len(body) and out["body_size"] == len(body)
    assert out["body"] == body
    assert out["offsets"] == [0x70, 0x100, 0x200]
    assert out["count_a"] == 6 and out["count_b"] == 3


def test_the_entry_map_is_count_b_contiguous_slices_covering_the_body():
    # count_b = 3 entries: 0x70..0x100, 0x100..0x200, 0x200..end
    blob, body = fen(6, 3, [0x70, 0x100, 0x200])
    out = T.fen_open(blob)
    assert [e["size"] for e in out["entries"]] == [0x90, 0x100, len(body) - 0x200]
    assert out["entries"][-1]["ends_at_body"] is True
    assert "count_a is not understood" in out["note"]
    # and one entry can be pulled out by index
    assert len(T.fen_entry(blob, 1)) == 0x100
    with pytest.raises(T.TexError, match="holds 3 entries"):
        T.fen_entry(blob, 3)


def test_a_declared_size_that_lies_is_refused():
    blob, body = fen(1, 1, [0x70])
    wrong = struct.pack("<I", len(body) + 16) + blob[4:]
    with pytest.raises(T.TexError, match="decompressed to"):
        T.fen_open(wrong)


def test_a_stream_that_is_not_zlib_is_refused():
    with pytest.raises(T.TexError, match="not a zlib stream"):
        T.fen_open(struct.pack("<I", 100) + b"NOTZLIB" + b"\0" * 64)
    with pytest.raises(T.TexError, match="FEN too short"):
        T.fen_open(b"\x01")
