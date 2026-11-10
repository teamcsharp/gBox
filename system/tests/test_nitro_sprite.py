import os
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gbox.formats import nitro_sprite as ns  # noqa: E402

ROM = os.environ.get("PW_ROM", str(Path.home() / ".hermes/cache/scratch/pw/white.nds"))


def _nclr(words):
    ttlp = b"TTLP" + struct.pack("<IIIII", 0x18 + 2 * len(words), 3, 0, 2 * len(words), 0x10) + struct.pack(f"<{len(words)}H", *words)
    return b"RLCN" + b"\xff\xfe\x00\x01" + struct.pack("<IHH", 0x10 + len(ttlp), 0x10, 1) + ttlp


def test_ncgr_roundtrip_and_tiles():
    data = bytes(range(32)) * 2
    g = ns.parse_ncgr(ns.build_ncgr(data, 1, 2))
    assert (g["tiles_y"], g["tiles_x"], g["depth_bpp"], g["tile_count"]) == (1, 2, 4, 2)
    assert g["tile_data"] == data
    t = ns.tile_indices(g)
    assert len(t) == 2 and t[0][:4] == [0, 0, 1, 0]


def test_nclr_colors_and_rejects():
    p = ns.parse_nclr(_nclr([0x7FFF, 0x001F]))
    assert p["colors"][0] == (255, 255, 255) and p["colors"][1] == (255, 0, 0)
    with pytest.raises(ValueError):
        ns.parse_ncgr(b"XXXX" + bytes(40))


@pytest.mark.skipif(not os.path.exists(ROM), reason="owned ROM scratch copy absent")
def test_real_pokemon_white_battle_sprite_group():
    from gbox.formats.nitro import NitroROM, narc, lz11_decompress
    m = narc(NitroROM(open(ROM, "rb").read()).read("a/0/0/4"))
    assert len(m) == 14285
    front = ns.parse_ncgr(lz11_decompress(m[0][1]))
    assert (front["tiles_y"], front["tiles_x"], front["depth_bpp"], front["tile_count"]) == (12, 12, 4, 144)
    back = ns.parse_ncgr(lz11_decompress(m[2][1]))
    assert (back["tiles_y"], back["tiles_x"], back["tile_count"]) == (16, 32, 512)
    assert len(ns.parse_nclr(m[18][1])["colors"]) == 16
