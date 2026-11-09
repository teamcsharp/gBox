"""gbox.switch_romfs: the header parse and the directory/file table walk, on synthetic tables.

The real vector is the RE6 base RomFS (60,645 files under nativeNXx64/); this test keeps the structure honest without
a 18.8 GB NSP: a root, one subdirectory, two files, the EMPTY links and the sibling chains.
"""
import struct

import pytest

from gbox import switch_romfs as R

EMPTY = R.EMPTY


def tables():
    # directory table: root (name "") at 0 with child at 0x18; "arc" at 0x18 with a file at 0
    dirs = bytearray()
    dirs += struct.pack("<6I", 0, EMPTY, 0x18, EMPTY, 0, 0)              # root
    dirs += struct.pack("<6I", 0, EMPTY, EMPTY, 0, 0, 3) + b"arc"        # subdir at 0x18
    # file table: "x.arc" (offset 0, 0x100) then "y.arc" (offset 0x100, 0x200), sibling chain
    first = 0x20 + len("x.arc")
    files = bytearray()
    files += struct.pack("<IIQQII", 0x18, first, 0, 0x100, 0, 5) + b"x.arc"
    files += struct.pack("<IIQQII", 0x18, EMPTY, 0x100, 0x200, 0, 5) + b"y.arc"
    return bytes(dirs), bytes(files)


def header(dirs: bytes, files: bytes) -> bytes:
    return struct.pack("<10Q", 0x50, 0, 0, 0x50, len(dirs), 0x50 + len(dirs), 0, 0x50 + len(dirs), len(files), 0x200)


def test_walk_reads_the_tree_through_sibling_chains():
    dirs, files = tables()
    entries = R.walk(dirs, files)
    assert entries == [
        {"path": "arc/x.arc", "offset": 0, "size": 0x100},
        {"path": "arc/y.arc", "offset": 0x100, "size": 0x200},
    ]


def test_read_uses_the_header_offsets_relative_to_the_header():
    dirs, files = tables()
    romfs = header(dirs, files) + dirs + files
    calls = []

    def read_virtual(offset, size):
        calls.append((offset, size))
        base = offset - 0x1000
        return romfs[base:base + size]

    out = R.read(read_virtual, 0x1000)
    assert out["header"]["dir_meta_offset"] == 0x50
    assert out["header"]["data_offset"] == 0x200
    assert [e["path"] for e in out["files"]] == ["arc/x.arc", "arc/y.arc"]
    assert calls[0] == (0x1000, 0x50)


def test_a_non_romfs_blob_is_refused():
    with pytest.raises(ValueError, match="not a RomFS header"):
        R.parse_header(bytes(0x50))
    with pytest.raises(ValueError, match="RomFS header"):
        R.parse_header(b"short")
