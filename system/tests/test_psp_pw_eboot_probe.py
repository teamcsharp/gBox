import struct
from gbox.psp_pw_eboot_probe import string_xrefs, func_start, jump_table, cstr, load_image


def _w(op, rs=0, rt=0, imm=0):
    return struct.pack('<I', (op << 26) | (rs << 21) | (rt << 16) | (imm & 0xFFFF))


def test_xref_negative_lo_and_prologue():
    va = 0x380320
    hi = (va + 0x8000) >> 16          # 0x38, lo negative
    lo = va - (hi << 16)
    code = bytearray(0x400000)
    code[0x100:0x104] = struct.pack('<I', 0x27BDFF80)   # addiu sp,sp,-0x80
    code[0x110:0x114] = _w(0xF, 0, 2, hi)                # lui v0,hi
    code[0x114:0x118] = _w(9, 2, 4, lo)                  # addiu a0,v0,lo
    code[va:va + 9] = b'cmf_load\0'
    assert string_xrefs(bytes(code), va) == [0x110]
    assert func_start(bytes(code), 0x110) == 0x100
    assert cstr(bytes(code), va) == b'cmf_load'


def test_jump_table_and_load_image():
    code = struct.pack('<3I', 0x2a31f8, 0x2a3904, 0x2a38c8)
    assert jump_table(code, 0, 3) == [0x2a31f8, 0x2a3904, 0x2a38c8]
    elf = bytearray(0x200)
    elf[:4] = b'\x7fELF'
    struct.pack_into('<HH', elf, 16, 0xFFA0, 8)
    struct.pack_into('<I', elf, 28, 52)
    struct.pack_into('<H', elf, 44, 1)
    struct.pack_into('<8I', elf, 52, 1, 0xA0, 0, 0, 8, 16, 7, 16)
    elf[0xA0:0xA8] = b'ABCDEFGH'
    img, info = load_image(bytes(elf))
    assert img[:8] == b'ABCDEFGH' and len(img) == 16 and info['etype'] == 0xFFA0
