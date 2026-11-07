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


# ---------------------------------------------------------------- the pixels are DDS

def dds(width=256, height=256, *, fourcc=b"DXT3", mips=9, body=b"\0" * 1024):
    """A minimal DDS the parser should accept."""
    head = bytearray(0x80)
    head[0:4] = T.DDS_MAGIC
    struct.pack_into("<I", head, 4, 0x7C)          # dwSize
    struct.pack_into("<I", head, 8, 0xA1007)       # dwFlags
    struct.pack_into("<I", head, 0x0C, height)
    struct.pack_into("<I", head, 0x10, width)
    struct.pack_into("<I", head, 0x1C, mips)
    struct.pack_into("<II", head, 0x4C, 32, 0x4)   # ddspf: size, DDPF_FOURCC
    head[0x54:0x58] = fourcc
    return bytes(head) + body


def wrapped(dds_bytes, *, wrapper_extra=0, declared=None):
    """A FEN entry: [declared size, -1, archive number, 0] + padding + the DDS."""
    pad = b"\0" * wrapper_extra
    declared = len(dds_bytes) + len(pad) if declared is None else declared
    return struct.pack("<4I", declared, 0xFFFFFFFF, 7, 0) + pad + dds_bytes


def fen_with(*entries):
    """A FEN whose offset table covers these entries: two counts, then count_b u64 offsets, then the entries."""
    n = len(entries)
    start = 8 + 8 * n
    offs, cursor = [], start
    for entry in entries:
        offs.append(cursor)
        cursor += len(entry)
    body = bytearray(struct.pack("<II", n, n))
    for offset in offs:
        body += struct.pack("<Q", offset)
    for entry in entries:
        body += entry
    return struct.pack("<I", len(body)) + zlib.compress(bytes(body), 9)


def test_a_fen_entry_is_a_wrapped_dds_and_its_header_reads():
    blob = fen_with(wrapped(dds(512, 256, mips=7)))
    t = T.fen_texture(blob, 0)
    assert (t["width"], t["height"]) == (512, 256)
    assert t["format"] == "DXT3" and t["mipmaps"] == 7
    assert t["wrapper_bytes"] == 16 and t["dds_bytes_match"] is True
    assert t["archive_number"] == 7 and t["name_hash"] == 7      # same field, honest name
    assert t["dds"][:4] == T.DDS_MAGIC


def test_a_longer_wrapper_is_located_not_assumed():
    """Measured: 00000010.pack.fen declares 49,328 DDS bytes and holds 49,392 - a 64-byte wrapper."""
    blob = fen_with(wrapped(dds(), wrapper_extra=64, declared=len(dds())))
    t = T.fen_texture(blob, 0)
    assert t["wrapper_bytes"] == 80 and t["dds_bytes_match"] is True
    assert t["width"] == 256


def test_a_declared_size_that_disagrees_is_reported_not_raised():
    blob = fen_with(wrapped(dds(), declared=12345))
    t = T.fen_texture(blob, 0)
    assert t["dds_bytes"] == 12345 and t["dds_bytes_match"] is False
    assert t["width"] == 256, "the surface still decodes; only the declared size disagrees"


def test_an_entry_with_no_dds_and_a_bad_header_are_refused():
    blob = fen_with(struct.pack("<4I", 0, 0, 0, 0) + b"NOT A DDS" + b"\0" * 200)
    with pytest.raises(T.TexError, match="holds no DDS"):
        T.fen_texture(blob, 0)
    broken = bytearray(dds())
    struct.pack_into("<I", broken, 4, 0x40)          # wrong dwSize
    with pytest.raises(T.TexError, match="header size"):
        T.dds_info(bytes(broken))
    with pytest.raises(T.TexError, match="too short"):
        T.dds_info(b"DDS ")


def test_a_listing_reports_every_texture_and_drops_the_bodies():
    blob = fen_with(wrapped(dds(64, 64, fourcc=b"DXT5")), wrapped(dds(32, 32)))
    assert len(T.fen_open(blob)["entries"]) == 2
    rows = T.fen_textures(blob)
    assert [r["format"] for r in rows] == ["DXT5", "DXT3"]
    assert "dds" not in rows[0] and "wrapper" not in rows[0]

def test_the_archive_name_is_eight_hex_digits_from_the_id():
    """Read out of the loader: "%s\\%s\\%08x.pack.fen" with the texture id formatted as eight hex digits."""
    assert T.archive_name(6) == "00000006.pack.fen"
    assert T.archive_name(48) == "00000030.pack.fen"
    assert T.archive_name(0x4400011C) == "4400011c.pack.fen"


def test_archive_for_reports_presence(tmp_path):
    folder = tmp_path / "bio4" / "imagepackhd"
    folder.mkdir(parents=True)
    (folder / "00000030.pack.fen").write_bytes(b"x" * 5)
    found = T.archive_for(tmp_path, 48)
    assert found["archive"] == "00000030.pack.fen" and found["present"] is True and found["bytes"] == 5
    missing = T.archive_for(tmp_path, 51)
    assert missing["archive"] == "00000033.pack.fen" and missing["present"] is False
