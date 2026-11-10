import struct
import pytest

from gbox.pop_sot_gc import (
    parse_big_header,
    parse_big_index_header,
    parse_big_entries,
    big_tab_offset,
    sha256_stream,
    FILE_INDEX_HEADER_SIZE,
    FILE_TAB_ENTRY_SIZE,
    FOLDER_TAB_ENTRY_SIZE,
)


def test_header():
    h = parse_big_header(b"BIG\x00" + struct.pack("<III", 0x25, 0x642, 5))
    assert h["bigfile_parameters"] == 0x25
    assert h["files1"] == 1602 and h["folders1"] == 5


def test_bad_magic():
    with pytest.raises(ValueError):
        parse_big_header(b"XXXX" + b"\0" * 12)


def test_sha():
    assert sha256_stream([b"a", b"bc"]) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def _make_hdr(skips1=179055, files1=2, folders1=1):
    hdr = bytearray(0x2C + FILE_INDEX_HEADER_SIZE)
    hdr[0:4] = b"BIG\x00"
    struct.pack_into("<I", hdr, 0x04, 0x25)
    struct.pack_into("<I", hdr, 0x08, files1)
    struct.pack_into("<I", hdr, 0x0C, folders1)
    struct.pack_into("<I", hdr, 0x18, 0xFFFFFFFF)
    struct.pack_into("<I", hdr, 0x1C, 0xFFFFFFFF)
    struct.pack_into("<I", hdr, 0x20, skips1)
    struct.pack_into("<I", hdr, 0x24, 1)
    # file index header @ 0x2c
    struct.pack_into("<I", hdr, 0x2C, files1)      # files2
    struct.pack_into("<I", hdr, 0x30, folders1)    # folders2
    struct.pack_into("<I", hdr, 0x34, 0x44)        # file_listing_offset
    struct.pack_into("<I", hdr, 0x38, 0xFFFFFFFF)  # next_listing_offset
    struct.pack_into("<I", hdr, 0x3C, 0)           # bf_16
    struct.pack_into("<I", hdr, 0x40, skips2 := 0)  # skips2
    return bytes(hdr), skips2


def test_entries_roundtrip():
    hdr, _ = _make_hdr()
    idx = hdr[0x2C:]
    files2, folders2, list_off = 2, 1, 0x44
    skips1 = struct.unpack_from("<I", hdr, 0x20)[0]
    ft_off = big_tab_offset(list_off, skips1)

    listing = struct.pack(
        "<4I", 0x1E0E000, 0x0B00572C, 0x2E0E000, 0x0B00572D)
    filetab = bytearray()
    for name, size in ((b"ps2.ico", 0xA7FC), (b"chars.bfh", 0x1000)):
        e = struct.pack("<5I", size, 0, 0, 0, 0) + name.ljust(0x40, b"\x00")
        assert len(e) == FILE_TAB_ENTRY_SIZE
        filetab += e
    foldertab = struct.pack("<5I", 0, 0, 0, 0, 0) + b"root".ljust(0x40, b"\x00")
    assert len(foldertab) == FOLDER_TAB_ENTRY_SIZE

    entries, folders, meta = parse_big_entries(hdr, idx, listing, bytes(filetab), foldertab)
    assert meta["file_tab_offset"] == ft_off
    assert len(entries) == 2 and len(folders) == 1
    assert entries[0]["name"] == "ps2.ico"
    assert entries[0]["offset"] == 0x1E0E000
    assert entries[0]["name_hash"] == 0x0B00572C
    assert entries[0]["file_size"] == 0xA7FC
    assert entries[1]["name"] == "chars.bfh"
    assert folders[0]["name"] == "root"
