import struct

import pytest

from gbox import nso_elf as N


def test_sections_are_sliced_behind_the_nso_header():
    """The header is 0x100 bytes and hactool leaves it in the output: a section's file offset is its vaddr + 0x100."""
    head = bytearray(0x100)
    head[0:4] = b"NSO0"
    struct.pack_into("<I", head, 0x18, 0x10)      # text size
    struct.pack_into("<I", head, 0x24, 0x10)      # rodata memory offset
    struct.pack_into("<I", head, 0x28, 0x08)      # rodata size
    struct.pack_into("<I", head, 0x34, 0x18)      # data memory offset
    struct.pack_into("<I", head, 0x38, 0x04)      # data size
    struct.pack_into("<I", head, 0x3C, 0x100)     # bss size
    image = bytes(head) + b"T" * 0x10 + b"R" * 0x08 + b"D" * 0x04
    rows = {row["name"]: row for row in N.sections(image)}
    assert rows[".text"]["data"] == b"T" * 0x10
    assert rows[".rodata"]["data"] == b"R" * 0x08 and rows[".rodata"]["vaddr"] == 0x10
    assert rows[".rwdata"]["data"] == b"D" * 0x04 and rows[".rwdata"]["vaddr"] == 0x18
    assert rows[".bss"]["size"] == 0x100 and rows[".bss"]["vaddr"] == 0x1C


def test_the_data_group_is_read_one_word_later_than_text_and_rodata():
    """Reading data_memory from 0x30 gives its compressed size; the memory offset is at 0x34 (the bug this pins)."""
    head = bytearray(0x100)
    head[0:4] = b"NSO0"
    struct.pack_into("<I", head, 0x30, 0xDEADBEEF)   # compressed size, not an address
    struct.pack_into("<I", head, 0x34, 0x2000)       # data memory offset
    struct.pack_into("<I", head, 0x38, 0x10)         # data size
    image = bytes(head) + b"\0" * 0x2010
    assert N.header(image)["data_memory"] == 0x2000
    assert {row["name"]: row for row in N.sections(image)}[".rwdata"]["vaddr"] == 0x2000


def test_to_elf_lays_out_one_segment_per_section_at_its_address():
    head = bytearray(0x100)
    head[0:4] = b"NSO0"
    struct.pack_into("<I", head, 0x18, 0x10)
    struct.pack_into("<I", head, 0x24, 0x10)
    struct.pack_into("<I", head, 0x28, 0x08)
    struct.pack_into("<I", head, 0x34, 0x18)
    struct.pack_into("<I", head, 0x38, 0x04)
    image = bytes(head) + b"T" * 0x10 + b"R" * 0x08 + b"D" * 0x04
    elf = N.to_elf(image)
    assert elf[:4] == b"\x7fELF"
    segments = N.section_table(elf)
    assert [(s["vaddr"], s["filesz"]) for s in segments] == [(0x0, 0x10), (0x10, 0x08), (0x18, 0x04)]
    for segment in segments:
        assert elf[segment["offset"]:segment["offset"] + segment["filesz"]] == {
            0x0: b"T" * 0x10, 0x10: b"R" * 0x08, 0x18: b"D" * 0x04}[segment["vaddr"]]


def test_a_non_nso_file_is_refused(tmp_path):
    with pytest.raises(N.NsoError, match="not an NSO0"):
        N.header(b"NOTNSO" + b"\0" * 0x200)