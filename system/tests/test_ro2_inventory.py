"""Focused tests for the RE Outbreak File #2 owned-source manifest."""
import hashlib
import struct
from pathlib import Path

import pytest

from gbox import ro2_inventory as inv

CHD = Path("/mnt/gbox/hyperspin/Arcade/collections/Sony PlayStation 2/roms/USA/"
           "Resident Evil Outbreak File #2 (USA).chd")


def _v5_header() -> bytes:
    """Hand-built MAME CHD v5 header (independent of the parser under test)."""
    h = bytearray(124)
    h[0:8] = b"MComprHD"
    struct.pack_into(">I", h, 8, 124)
    struct.pack_into(">I", h, 12, 5)
    h[16:20] = b"cdlz"
    h[20:24] = b"cdzl"
    h[24:28] = b"cdfl"
    h[28:32] = b"lcfd"
    struct.pack_into(">Q", h, 32, 5591427840)
    struct.pack_into(">Q", h, 40, 0xCFFA369D)
    struct.pack_into(">Q", h, 48, 0x7C)
    struct.pack_into(">I", h, 56, 19584)
    struct.pack_into(">I", h, 60, 2448)
    return bytes(h)


def test_chd_v5_header_parses():
    out = inv.parse_chd_header(_v5_header())
    assert out["version"] == 5
    assert out["logical_bytes"] == 5591427840
    assert out["hunk_bytes"] == 19584
    assert out["unit_bytes"] == 2448
    assert out["codecs"][:3] == ["cdlz", "cdzl", "cdfl"]


def test_chd_v5_header_agrees_with_gbox_reader():
    from gbox.chd import header as gbox_header
    assert gbox_header(_v5_header())["version"] == 5


def test_elf_info_parses_big_endian_mips():
    e = bytearray(52)
    e[0:4] = b"\x7fELF"
    e[4] = 1          # ELFCLASS32
    e[5] = 2          # ELFDATA2MSB
    struct.pack_into(">H", e, 16, 2)        # ET_EXEC
    struct.pack_into(">H", e, 18, 8)        # EM_MIPS
    struct.pack_into(">I", e, 24, 0x00100000)
    struct.pack_into(">H", e, 44, 9)        # e_phnum
    info = inv.elf_info(bytes(e))
    assert info["byte_order"] == "big"
    assert info["elf_machine"] == "EM_MIPS"
    assert info["e_entry"] == 0x00100000
    assert info["e_phnum"] == 9


def test_elf_info_rejects_non_elf():
    assert inv.elf_info(b"PS2\x00" + bytes(60)) is None


@pytest.mark.skipif(not CHD.exists(), reason="owned CHD not mounted")
def test_owned_build_manifest():
    man = inv.inventory(CHD)
    assert man["source"]["header"]["version"] == 5
    assert man["source"]["size_bytes"] == 3490296061
    assert man["source"]["header"]["logical_bytes"] == 5591427840
    assert man["counts"]["root_elf_members"] == 1
    assert man["counts"]["subdir_elf_members"] == 43
    assert man["counts"]["members"] == 80
    exe = man["executable"]
    assert exe["path"] == "SLUS_209.84"
    assert exe["size"] == 1482432
    assert exe["elf_machine"] == "EM_MIPS"
    assert exe["byte_order"] == "little"
    assert exe["sha256"] == "5c0411a26247ef9974cd94b844ac5aecbcbf4705db543f51814aeed89da0fd8d"
