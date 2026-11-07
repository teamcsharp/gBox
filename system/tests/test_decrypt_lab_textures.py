"""The HD texture catalogue and its preview, exercised without a title.

`hd_textures` walks an HD tree's `bio4/imagepackhd`; `hd_texture_png` renders one DDS. Both take a root path, so a
temporary tree with a synthetic archive is enough to pin the shaping, the caching and the refusals.
"""
import struct
import zlib

import pytest

from gbox import decrypt_lab as L
from gbox import re4hd_tex as T


def dds(width=64, height=64, *, fourcc=b"DXT3", mips=5, body=None):
    # DXT3 64x64 needs 16 bytes per 4x4 block (256 blocks) before any mip, so give it room
    body = b"\0" * (width * height) if body is None else body
    head = bytearray(0x80)
    head[0:4] = b"DDS "
    struct.pack_into("<I", head, 4, 0x7C)
    struct.pack_into("<I", head, 8, 0xA1007)
    struct.pack_into("<I", head, 0x0C, height)
    struct.pack_into("<I", head, 0x10, width)
    struct.pack_into("<I", head, 0x1C, mips)
    struct.pack_into("<II", head, 0x4C, 32, 0x4)
    head[0x54:0x58] = fourcc
    return bytes(head) + body


def fen(entries):
    """A FEN whose offset table covers these wrapped entries."""
    n = len(entries)
    start = 8 + 8 * n
    offsets, cursor = [], start
    for entry in entries:
        offsets.append(cursor)
        cursor += len(entry)
    body = bytearray(struct.pack("<II", n, n))
    for offset in offsets:
        body += struct.pack("<Q", offset)
    for entry in entries:
        body += entry
    return struct.pack("<I", len(body)) + zlib.compress(bytes(body), 9)


def wrapped(surface):
    return struct.pack("<4I", len(surface), 0xFFFFFFFF, 1, 0) + surface


@pytest.fixture
def hd_tree(tmp_path):
    packs = tmp_path / "bio4" / "imagepackhd"
    packs.mkdir(parents=True)
    (packs / "00000001.pack.fen").write_bytes(fen([wrapped(dds(64, 64)),
                                                   wrapped(dds(128, 32, fourcc=b"DXT5"))]))
    (packs / "00000002.pack.fen").write_bytes(fen([wrapped(dds(32, 32))]))
    (tmp_path / "bio4" / "em").mkdir()
    return tmp_path


def test_the_catalogue_lists_every_surface_with_its_archive_and_format(hd_tree):
    L._TEXTURE_CACHE.clear()
    out = L.hd_textures(hd_tree)
    assert out["edition"] == "hd" and out["archive_count"] == 2
    assert out["count"] == 3
    assert out["formats"] == {"DXT3": 2, "DXT5": 1}
    rows = out["textures"]
    assert {(r["archive"], r["index"]) for r in rows} == {
        ("00000001.pack.fen", 0), ("00000001.pack.fen", 1), ("00000002.pack.fen", 0)}
    assert {(r["width"], r["height"]) for r in rows} == {(64, 64), (128, 32), (32, 32)}
    assert out["failures"] == []


def test_the_walk_is_bounded_and_cached(hd_tree, monkeypatch):
    L._TEXTURE_CACHE.clear()
    first = L.hd_textures(hd_tree, archives=1)
    assert first["archive_count"] == 1 and first["count"] == 2
    # a second call inside the TTL must not re-read the archives
    reads = []
    real = type(hd_tree / "bio4" / "imagepackhd" / "00000001.pack.fen").read_bytes

    def counting(self):
        reads.append(self.name)
        return real(self)

    monkeypatch.setattr(type(hd_tree / "bio4" / "imagepackhd" / "00000001.pack.fen"), "read_bytes", counting)
    again = L.hd_textures(hd_tree, archives=1)
    assert again["count"] == first["count"] and reads == []


def test_a_tree_without_the_archives_says_so(tmp_path):
    assert L.hd_textures(tmp_path)["archive_count"] == 0
    with pytest.raises(FileNotFoundError):
        L.hd_texture_png(tmp_path, "00000001.pack.fen", 0)


def test_a_texture_renders_to_png_and_a_bad_index_is_refused(hd_tree):
    png = L.hd_texture_png(hd_tree, "00000001.pack.fen", 0)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    with pytest.raises(ValueError, match="out of range"):
        L.hd_texture_png(hd_tree, "00000001.pack.fen", 9)
    with pytest.raises(FileNotFoundError):
        L.hd_texture_png(hd_tree, "nope.fen", 0)


def test_a_dds_pil_cannot_open_is_reported_as_a_value_error(hd_tree):
    # a real DDS header with a body that is not valid block data
    packs = hd_tree / "bio4" / "imagepackhd"
    (packs / "00000003.pack.fen").write_bytes(fen([wrapped(dds(64, 64, body=b"\xff" * 3))]))
    with pytest.raises(ValueError, match="did not decode"):
        L.hd_texture_png(hd_tree, "00000003.pack.fen", 0)


def pack_with(*items):
    """An HD pack whose DAT holds these slots (BIN-named, so the DAT layout is the one the readers expect)."""
    n = len(items)
    base = 16 + 4 * n + 4 * n
    offsets, cursor = [], base
    for item in items:
        offsets.append(cursor)
        cursor += len(item)
    dat = bytearray(struct.pack("<II", n, 0) + b"\0" * 8)
    dat += struct.pack(f"<{n}I", *offsets)
    dat += b"TPL\0" * n
    for item in items:
        dat += item
    hdr = bytearray(b"\xca\xb6\xbe\x20" * 8)
    hdr += struct.pack("<IIII", 0, len(dat), 0, 0x400) + b"\0" * 16
    hdr += struct.pack("<I", 0xFFFFFFFF)
    hdr += b"\0" * (0x400 - len(hdr))
    return bytes(hdr) + bytes(dat)


def container(*records):
    """A TPL container: header, one sixteen-byte table entry per record, the records, then (type, id) pairs."""
    count = len(records)
    offsets, cursor = [], 0x10 + 0x10 * count
    for width, height, fmt, payload, _tid in records:
        offsets.append(cursor)
        cursor += 0x28
    body = bytearray(struct.pack("<IIII", 0x12345678, count, 0x10, 0))
    for offset in offsets:
        body += struct.pack("<QQ", offset, 0)
    for width, height, fmt, payload, _tid in records:
        body += struct.pack("<HHII", width, height, fmt, payload) + b"\0" * 0x1C      # a record is 0x28 bytes
    for _w, _h, _f, _p, tid in records:
        body += struct.pack("<II", 0x16, tid)
    return bytes(body)


def test_texture_descriptors_reads_the_container_layout(tmp_path):
    """The dimensions must come from a record, not from a fixed offset - the mistake that poisoned a round of joins."""
    packs = tmp_path / "bio4" / "em"
    packs.mkdir(parents=True)
    slot = container((256, 256, 14, 184, 48), (128, 128, 14, 192, 49))
    (packs / "em11.udas").write_bytes(pack_with(slot))
    out = L.texture_descriptors(tmp_path, "em11.udas")
    assert out["images"] == 2 and out["slots"] == 1
    assert out["ids"] == [48, 49]
    first, second = out["rows"]
    assert (first["width"], first["height"], first["format_code"], first["id"], first["payload"]) == (256, 256, 14, 48, 184)
    assert (second["width"], second["height"], second["id"]) == (128, 128, 49)
    assert "archive" in out["note"] and "join" in out["note"]
    with pytest.raises(FileNotFoundError):
        L.texture_descriptors(tmp_path, "nope.udas")


def test_tpl_images_refuses_a_record_that_is_not_a_plausible_size():
    bad = bytearray(container((256, 256, 14, 184, 48)))
    struct.pack_into("<HH", bad, 0x30, 0, 0)             # a zero-sized record means this is not a container
    assert T.tpl_images(bytes(bad)) == []
