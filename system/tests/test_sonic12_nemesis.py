import hashlib
import os
from pathlib import Path

import pytest

from gbox import genesis_nemesis as nem
from gbox import sonic12_analysis as an


def test_roundtrip_synthetic():
    tiles = bytes((i * 7 + (i >> 3)) & 0xFF for i in range(32 * 5))
    for xor in (True, False):
        assert nem.decode(nem.encode(tiles, xor)) == tiles


def test_decode_table_stream():
    # header: 1 tile raw-mode, table: nybble 0 run 8 code '0' (len1); nybble 1 run 8 code '1'
    # 64 nybbles = 8 runs of 8: rows 00000000 x4 then 11111111 x4
    stream = bytes([0x00, 0x01, 0x80, 0x71, 0x00, 0x81, 0x71, 0x01, 0xFF, 0x0F])
    assert nem.decode(stream) == bytes(16) + b"\x11" * 16


def test_rejects_garbage():
    with pytest.raises(nem.NemesisError):
        nem.decode(b"\x00")


ROM = Path(os.environ.get("SONIC12_ROM", "work/rom/Sonic 1 and 2.bin"))


@pytest.mark.skipif(not ROM.exists(), reason="owned ROM not present")
def test_owned_rom_streams():
    rom = ROM.read_bytes()
    if hashlib.sha256(rom).hexdigest() != an.ROM_SHA256:
        pytest.skip("different build")
    assert an.check_rom(rom)["console"].startswith("SEGA GENESIS")
    for off, count in an.VERIFIED_NEMESIS.items():
        tiles, size = an.decode_at(rom, off)
        assert len(tiles) == count * 32
        assert nem.decode(nem.encode(tiles)) == tiles
