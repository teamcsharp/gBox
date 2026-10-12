"""WWF No Mercy (USA) Rev A analysis probe (#1329): the game's CI8/CI4 texture rule, the shared CI4 neck, the
class-dependent neck palette and the instruction sites pinned to the owned build."""
import hashlib
import struct
import zipfile
from pathlib import Path

import numpy as np
import pytest

from gbox import aki_wrestling as A
from gbox import nomercy_analysis as N

SRC = Path.home() / "gbox-cache/23a346e48b6368a6/source.zip"     # owned WWF No Mercy (USA) (Rev A) zip copy
Z64_SHA = "fc561fce443010b114cc8ea41226772b7b2a2d33055be163fad91ac9c3b096cb"
owned = pytest.mark.skipif(not SRC.exists(), reason="owned No Mercy ROM is not on this machine")


def _pal(n: int) -> bytes:
    """n distinct opaque RGBA5551 colours (big-endian), padded to a 512-byte palette file."""
    w = [((i % 32) << 11) | (((i * 7) % 32) << 6) | (((i * 3) % 32) << 1) | 1 for i in range(n)]
    return b"".join(struct.pack(">H", c) for c in w).ljust(512, b"\0")


def test_format_follows_header_byte_2():
    assert A.tex_format(bytes([7, 7, 1, 0, 0, 0, 3, 3]) + bytes(64)) == "ci8"
    assert A.tex_format(bytes([7, 7, 0, 0x20, 1, 1, 3, 3]) + bytes(32)) == "ci4"
    assert A.tex_format(bytes([7, 7, 0, 0x10, 0, 0, 3, 3]) + bytes(64)) == "ci4"     # byte 2 decides, not the size
    for bad in (bytes([7, 7, 1, 0, 0, 0, 3, 3]) + bytes(63), bytes([7, 7, 0, 0x20, 0, 0, 3, 3]) + bytes(31), b"\x07\x07"):
        with pytest.raises(ValueError):
            A.tex_format(bad)


def test_ci4_decodes_high_nibble_first_on_the_first_16_colours():
    pix = bytes(((2 * i) % 16) << 4 | (2 * i + 1) % 16 for i in range(32))
    tex = bytes([7, 7, 0, 0x20, 1, 1, 3, 3]) + pix                                   # neck-like header: 32 colours
    pal = _pal(32)
    img = A.tex_decode(tex, pal)
    colours = A.rgba5551(np.frombuffer(pal[:64], ">u2"))
    assert img.shape == (8, 8, 4)
    assert (img.reshape(64, 4) == colours[np.arange(64) % 16]).all()
    used = {tuple(c) for c in img.reshape(64, 4).tolist()}
    assert not used & {tuple(c) for c in colours[16:].tolist()}                     # the second bank is never read
    assert (A.ci8_decode(tex, pal) == img).all()                                    # old entry point accepts CI4


def test_ci8_decode_is_unchanged():
    idx = np.random.default_rng(1).integers(0, 256, (16, 32), dtype=np.uint8)
    tex = struct.pack(">BBHBBBB", 31, 15, 256, 1, 1, 5, 4) + idx.tobytes()
    pal = _pal(256)
    assert (A.tex_decode(tex, pal) == A.rgba5551(np.frombuffer(pal, ">u2"))[idx]).all()


def test_load_rom_normalizes_zip_members(tmp_path):
    z64 = b"\x80\x37\x12\x40" + bytes(range(256)) * 4 + bytes(4)
    for name, data in (("a.z64", z64), ("b.n64", np.frombuffer(z64, np.uint16).byteswap().tobytes()),
                       ("c.n64", np.frombuffer(z64, np.uint32).byteswap().tobytes())):
        zp = tmp_path / f"{name}.zip"
        with zipfile.ZipFile(zp, "w") as f:
            f.writestr(name, data)
        assert N.load_rom(zp) == z64


def test_check_sites_names_a_changed_instruction():
    rom = bytearray(0x60000)
    for ram, word, _ in N.SITES:
        struct.pack_into(">I", rom, A._ram2rom(ram), word)
    assert N.check_sites(bytes(rom)) == {"checked": len(N.SITES), "mismatches": []}
    struct.pack_into(">I", rom, A._ram2rom(0x8000D84C), 0)
    assert [m["ram"] for m in N.check_sites(bytes(rom))["mismatches"]] == ["0x8000D84C"]


@owned
def test_owned_build_sites_textures_and_neck_palettes():
    rom = N.load_rom(SRC)
    assert hashlib.sha256(rom).hexdigest() == Z64_SHA
    assert N.check_sites(rom) == {"checked": len(N.SITES), "mismatches": []}
    s = N.texture_survey(rom)
    assert s["decode_failures"] == []
    assert s["formats"]["ci8"] >= 287 and s["formats"]["ci4"] >= 1
    assert s["costumes_class_lt6"] > 0 and s["costumes_class_ge6"] > 0
    neck = {c["palette"]: c for c in s["ci4"] if c["texture"] == "0x1F6A"}
    assert set(neck) == {"0x1F6B", "0x1F6D"}
    ft = A.FileTable(rom)
    for pal_id, c in neck.items():
        assert c["size"] == [8, 8] and c["header_colours"] == 32 and c["bytes"] == 40 and c["colours_used"] == 1
        first = A.rgba5551(np.frombuffer(ft.get(int(pal_id, 16))[:2], ">u2"))[0].tolist()
        assert c["first_colour"] == first                                            # every texel is index 0
    cs = A.costumes(rom, ft)
    for k in range(0, len(cs), 4):
        cls = N.body_class(rom, cs[k][0])
        assert A.part_list_static(rom, k // 4 + 1, 0)[0x20] == [0x14FF, 0x1F6A, 0x1F6D if cls >= 6 else 0x1F6B]
