"""Writing a texture back into an `imagepackhd` archive.

The join (`%08x.pack.fen` of a texture id) says *which* archive a pack's texture lives in; this pins the other half -
putting a different surface into one entry and keeping the archive readable.

The archive is `u32 uncompressed size` + zlib(body), body = `count_a, count_b, count_b u64 offsets`, entries are the
slices between consecutive offsets. A writer therefore has two jobs: replace bytes inside an entry, and keep every later
offset correct if the length changed.
"""
import struct
import zlib

import pytest

from gbox import re4hd_tex as T


def dds(width=64, height=64, fill=b"\xAB"):
    """A DDS surface complete enough for `dds_info`: header size, flags, dimensions and a DXT3 fourCC."""
    head = bytearray(128)
    head[0:4] = T.DDS_MAGIC
    struct.pack_into("<7I", head, 4, 0x7C, 0x00081007, height, width, width * 2, 0, 1)   # size, flags, h, w, pitch, depth, mips
    struct.pack_into("<II", head, 0x4C, 32, 0x4)                                      # pixel-format size and FOURCC flag
    head[0x54:0x58] = b"DXT3"
    return bytes(head) + fill * 16


def fen(entries, *, count_a=6, wrapper=16):
    """An archive whose body holds `entries`, each optionally behind a wrapper, the way a real one does."""
    pieces = []
    for index, surface in enumerate(entries):
        prefix = b""
        if wrapper:
            prefix = bytearray(wrapper)
            struct.pack_into("<I", prefix, 0, len(surface))
            struct.pack_into("<I", prefix, 4, 0xFFFFFFFF)
            struct.pack_into("<I", prefix, 8, index)
        pieces.append(bytes(prefix) + surface)
    offsets, cursor = [], 8 + 8 * len(pieces)
    for piece in pieces:
        offsets.append(cursor)
        cursor += len(piece)
    body = bytearray(struct.pack("<II", count_a, len(pieces)) + struct.pack(f"<{len(pieces)}Q", *offsets))
    body += b"".join(pieces)
    body = bytes(body)
    return struct.pack("<I", len(body)) + zlib.compress(body, 9)


def test_patching_one_entry_keeps_the_others_and_the_offsets_honest():
    original = fen([dds(fill=b"A"), dds(fill=b"B"), dds(fill=b"C")])
    # a same-size patch replaces the whole entry, wrapper included (16-byte wrapper + a 144-byte surface = 160)
    replacement = b"\0" * 16 + dds(fill=b"Z")
    written = T.fen_patch(original, 1, replacement, allow_resize=False)
    opened = T.fen_open(written)
    assert opened["count_b"] == 3 and opened["count_a"] == 6
    assert opened["declared_size"] == len(opened["body"])
    entries = [opened["body"][a:b] for a, b in
               [(opened["offsets"][i], (opened["offsets"][i + 1] if i + 1 < 3 else len(opened["body"])))
                for i in range(3)]]
    assert entries[1] == replacement
    assert entries[0].endswith(dds(fill=b"A")) and entries[2].endswith(dds(fill=b"C"))
    assert len(entries[0]) == 160 and len(entries[2]) == 160


def test_a_longer_replacement_shifts_every_later_offset():
    original = fen([dds(fill=b"A"), dds(fill=b"B")])
    longer = dds(fill=b"Z") + b"\0" * 40
    written = T.fen_patch(original, 0, longer)
    opened = T.fen_open(written)
    assert opened["declared_size"] == len(opened["body"])
    second = opened["body"][opened["offsets"][1]:]
    assert second.endswith(dds(fill=b"B")), "the second entry must still start where the table says"
    first = opened["body"][opened["offsets"][0]:opened["offsets"][1]]
    assert first == longer


def test_a_resize_can_be_refused_with_numbers():
    original = fen([dds(fill=b"A")])
    with pytest.raises(T.TexError, match="pass allow_resize=True"):
        T.fen_patch(original, 0, dds(fill=b"Z") + b"\0" * 8, allow_resize=False)


def test_an_out_of_range_entry_is_refused():
    original = fen([dds(), dds()])
    with pytest.raises(T.TexError, match="out of range"):
        T.fen_patch(original, 5, dds())


def test_replacing_a_texture_keeps_the_wrapper_and_updates_its_count():
    original = fen([dds(width=64, height=64, fill=b"A")])
    surface = dds(width=128, height=64, fill=b"Q")
    written = T.fen_replace_texture(original, 0, surface)
    opened = T.fen_open(written)
    entry = opened["body"][opened["offsets"][0]:]
    assert entry.endswith(surface)
    assert struct.unpack_from("<I", entry, 0)[0] == len(surface)      # the wrapper's declared DDS byte count
    parsed = T.fen_texture(written, 0)
    assert (parsed["width"], parsed["height"]) == (128, 64) and parsed["dds_bytes_match"] is True


def test_replacing_refuses_a_file_that_is_not_a_dds():
    original = fen([dds()])
    with pytest.raises(T.TexError, match="does not start with"):
        T.fen_replace_texture(original, 0, b"\x89PNG\r\n\x1a\n" + b"\0" * 64)


def test_an_archive_without_a_usable_entry_map_is_refused():
    """A count that cannot index the body is not an entry map, and the writer says so instead of guessing."""
    body = struct.pack("<II", 1, 1 << 20) + b"\0" * 16
    broken = struct.pack("<I", len(body)) + zlib.compress(body, 9)
    with pytest.raises(T.TexError, match="not usable"):
        T.fen_patch(broken, 0, dds())
