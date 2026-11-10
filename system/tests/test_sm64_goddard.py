import os, struct, pytest
from gbox import sm64_goddard as G

ROM = os.environ.get('SM64_ROM', os.path.expanduser('~/agent-work/ports/Super Mario 64 (USA).z64'))


def _synthetic():
    rom = bytearray(0x24A320)
    for i in range(3):
        o = 0x23A000 + i * G.TILE_BYTES
        for p in range(G.TILE_W * G.TILE_H):
            struct.pack_into('>H', rom, o + 2 * p, G.BG if p % 3 else 0xFFFF)
    return bytes(rom)


def test_finds_only_tiles_in_synthetic_rom():
    assert G.find_tiles(_synthetic()) == [0x23A000, 0x23A800, 0x23B000]


def test_short_rom_returns_nothing():
    assert G.find_tiles(b'\0' * 100) == []


def test_decode_tile_alpha_and_size():
    px = G.decode_tile(_synthetic(), 0x23A000)
    assert len(px) == 1024 and px[0] == (255, 255, 255, 255) and px[1][3] == 0


@pytest.mark.skipif(not os.path.exists(ROM), reason='owned ROM not present')
def test_real_rom_bank_is_inside_raw_goddard_region():
    t = G.find_tiles(open(ROM, 'rb').read())
    assert len(t) >= 8 and min(t) >= 0x239800 and max(t) < 0x242000
