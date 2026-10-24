import struct

from gbox import gs2_loader_xref as x


def _lui(rt, imm): return (0x0F << 26) | (rt << 16) | imm
def _addiu(rt, rs, imm): return (0x09 << 26) | (rs << 21) | (rt << 16) | (imm & 0xFFFF)
def _lw(rt, rs, imm): return (0x23 << 26) | (rs << 21) | (rt << 16) | (imm & 0xFFFF)


def build_elf(code_words, strings_at):
    """ELF32 LE MIPS: seg0 (RX) code at 0x100000, seg1 (R) data at 0x200000."""
    code = struct.pack(f"<{len(code_words)}I", *code_words)
    data = b"".join(s.encode() + b"\0" for s in strings_at)
    off0, off1 = 0x80, 0x80 + len(code) + 0x10
    hdr = bytearray(0x80)
    hdr[:4] = b"\x7fELF"; hdr[4] = 1; hdr[5] = 1; hdr[6] = 1
    struct.pack_into("<HHI", hdr, 0x10, 2, 8, 1)
    struct.pack_into("<II", hdr, 0x18, 0x100000, 0x34)
    struct.pack_into("<HH", hdr, 0x2A, 32, 2)
    struct.pack_into("<8I", hdr, 0x34, 1, off0, 0x100000, 0x100000, len(code), len(code), 5, 16)
    struct.pack_into("<8I", hdr, 0x54, 1, off1, 0x200000, 0x200000, len(data), len(data), 4, 16)
    return bytes(hdr) + code + b"\0" * 0x10 + data


def test_xref_exact():
    words = [_addiu(29, 29, -32), _lui(4, 0x20), _addiu(4, 4, 4), 0x03E00008, 0]
    elf = x.parse_elf(build_elf(words, ["pad", "SYSTEM.AFS"]))
    rep = x.report(elf, ["SYSTEM.AFS"])["SYSTEM.AFS"]
    assert rep[0]["vaddr"] == 0x200004
    assert rep[0]["refs"] == [{"pc": 0x100008, "func_start": 0x100000}]


def test_load_form_and_negative_lo():
    # lui v0,0x21 ; lw v0,-0x7ffc(v0) -> 0x210000-0x7ffc? use target 0x208004
    words = [_addiu(29, 29, -16), _lui(2, 0x21), _lw(2, 2, -0x7FFC)]
    elf = x.parse_elf(build_elf(words, []))
    assert x.find_code_refs(elf, 0x210000 - 0x7FFC) == [0x100008]


def test_rejects_non_mips():
    bad = bytearray(build_elf([0], []))
    struct.pack_into("<H", bad, 0x12, 3)
    try:
        x.parse_elf(bytes(bad))
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_callees_decode_jal():
    jal = (3 << 26) | (0x100020 >> 2)
    elf = x.parse_elf(build_elf([_addiu(29, 29, -16), jal, 0], []))
    assert x.callees(elf, 0x100000, 12) == [0x100020]


def test_real_sles_50650_symbols_if_present():
    import hashlib
    import os
    import pytest
    p = os.path.expanduser("~/gbox-cache/ps2/5ec1d297cb44b3ea/SLES_506.50")
    if not os.path.exists(p):
        pytest.skip("owned executable not staged on this host")
    data = open(p, "rb").read()
    assert hashlib.sha256(data).hexdigest().startswith("cae6ae75")
    elf = x.parse_elf(data)
    syms = {s["name"]: s for s in x.read_symbols(elf) if s["type"] == 2}
    for n in ("bhReadPlayerData", "bhMlbBinRealize", "bhMnbBinRealize", "npSkinConvert", "Model_Read_Set"):
        assert n in syms
    tree = x.call_tree(elf, list(syms.values()), ["bhReadPlayerData"])
    assert "bhMlbBinRealize" in tree["bhReadPlayerData"]["calls"]
    # file-table string pointers: SYSTEM.AFS name string is reachable via data pointer table
    (off, va), = x.find_string(elf, b"SYSTEM.AFS")
    assert va == 0x3EF698
