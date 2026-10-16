"""re_executable original-Xbox support: XBE -> ELF32 x86 and the 'xbox' CPU mapping."""

import struct

from gbox import re_lab_tool


def _synthetic_xbe():
    """A minimal retail original-Xbox XBE with one executable section at 0x11000."""
    base = 0x10000
    header_size = 0x1000
    image_size = 0x20000
    entry = 0x11000
    thunk = 0x10000
    ep_key, thunk_key = re_lab_tool.XBOX_XBE_KEYS["retail"]
    nsec = 1
    sec_va = 0x10200                       # section table lives inside the header
    raw, rsize, vsize, va = 0x1000, 0x100, 0x100, 0x11000
    blob = bytearray(raw + rsize)
    blob[:4] = b"XBEH"
    struct.pack_into("<I", blob, 0x104, base)
    struct.pack_into("<I", blob, 0x108, header_size)
    struct.pack_into("<I", blob, 0x10C, image_size)
    struct.pack_into("<I", blob, 0x11C, nsec)
    struct.pack_into("<I", blob, 0x120, sec_va)
    struct.pack_into("<I", blob, 0x128, entry ^ ep_key)
    struct.pack_into("<I", blob, 0x158, thunk ^ thunk_key)
    # one section: flags=4 (executable), va, vsize, raw, rsize, name_va
    struct.pack_into("<6I", blob, sec_va - base, 4, va, vsize, raw, rsize, 0)
    blob[raw:raw + rsize] = b"\x90" * rsize   # NOP sled as placeholder code
    return bytes(blob)


def test_platform_cpu_has_xbox_x86_mapping():
    assert re_lab_tool.PLATFORM_CPU["xbox"] == ("x86", "x86:LE:32:default", 3, False)


def test_xbe_to_elf_is_elf32_le_x86_at_real_addresses():
    xbe = _synthetic_xbe()
    elf, info = re_lab_tool.xbe_to_elf(xbe)

    assert elf[:4] == b"\x7fELF"
    assert elf[4] == 1                       # ELFCLASS32
    assert elf[5] == 1                       # ELFDATA2LSB (little-endian x86)
    assert struct.unpack_from("<H", elf, 0x12)[0] == 3          # e_machine = EM_386
    assert struct.unpack_from("<I", elf, 0x18)[0] == 0x11000    # e_entry = decrypted entry
    phnum = struct.unpack_from("<H", elf, 0x2C)[0]
    assert phnum == 1
    # PT_LOAD: p_type=1, p_vaddr=0x11000, p_filesz=0x100, p_flags=R|X (5)
    p_type, p_offset, p_vaddr, _p_paddr, p_filesz, p_memsz, p_flags, _align = \
        struct.unpack_from("<8I", elf, 52)
    assert (p_type, p_vaddr, p_filesz, p_memsz, p_flags) == (1, 0x11000, 0x100, 0x100, 5)
    assert elf[p_offset:p_offset + p_filesz] == b"\x90" * 0x100
    assert info["base"] == 0x10000
    assert info["entry"] == 0x11000


def test_xbe_to_elf_rejects_bad_magic_and_unknown_entry_key():
    xbe = bytearray(_synthetic_xbe())
    xbe[0] = 0x59                          # corrupt the magic (not 'X')
    try:
        re_lab_tool.xbe_to_elf(bytes(xbe))
    except ValueError as exc:
        assert "not an Xbox XBE" in str(exc)
    else:
        raise AssertionError("expected ValueError for bad magic")

    bad = bytearray(_synthetic_xbe())
    struct.pack_into("<I", bad, 0x128, 0)      # entry ciphertext that no key decodes in-range
    try:
        re_lab_tool.xbe_to_elf(bytes(bad))
    except ValueError as exc:
        assert "do not decode with a known key" in str(exc)
    else:
        raise AssertionError("expected ValueError for undecodable entry")


def test_ram_to_image_accepts_xbox_platform():
    elf, info = re_lab_tool.ram_to_image("xbox", b"\x90" * 64, 0x10000)
    assert elf[:4] == b"\x7fELF"
    assert struct.unpack_from("<H", elf, 0x12)[0] == 3   # EM_386
    assert info["base"] == 0x10000


def test_xbox_main_ram_layout_is_64_mib_at_zero():
    # Original Xbox: 64 MiB of unified DDR SDRAM mapped at physical 0x0.
    assert re_lab_tool.ram_layout("xbox") == (0x00000000, 0x04000000)


def test_live_ram_range_accepts_and_rejects_xbox_ranges():
    default = re_lab_tool._live_ram_range(re_lab_tool.ExeIn(game_id="g", source="ram"), "xbox")
    assert default == (0x00000000, 0x04000000)

    in_range = re_lab_tool._live_ram_range(
        re_lab_tool.ExeIn(game_id="g", source="ram", ram_base=0x10000, ram_size=0x03FF0000), "xbox")
    assert in_range == (0x10000, 0x03FF0000)

    try:
        re_lab_tool._live_ram_range(
            re_lab_tool.ExeIn(game_id="g", source="ram", ram_base=0x0, ram_size=0x04000001), "xbox")
    except ValueError as exc:
        assert "outside the verified live platform layout" in str(exc)
    else:
        raise AssertionError("expected ValueError for a 64 MiB + 1 range")
