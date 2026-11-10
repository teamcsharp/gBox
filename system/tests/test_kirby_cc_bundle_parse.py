import glob
import os
import struct

import pytest

from gbox.formats import kirby_cc
from gbox.formats.nitro import NitroROM


def _bundle(chunks=(b"\x01" * 8, b"\x00" * 4), blocks=2, bad_term=False):
    """Independent construction of the documented kind-6 layout."""
    payload = b""
    for i, c in enumerate(chunks):
        payload += struct.pack("<H", len(c)) + c + (b"\xff\xff" if i else b"")
    block_start = 12 + len(payload)
    body = payload + b"".join(bytes([i]) * 16 for i in range(blocks))
    dir_start = 12 + len(body)
    body += b"".join(struct.pack("<3I", block_start + 16 * i, 12, 100 * i) for i in range(blocks))
    size = 12 + len(body)
    table = b"".join(struct.pack("<I", dir_start + 12 * i) for i in range(blocks)) + struct.pack("<I", 1 if bad_term else 0)
    return struct.pack("<3I", 6, blocks, size) + body + table


def test_parse_bundle_synthetic():
    p = kirby_cc.parse_bundle(_bundle())
    assert p["count"] == 2 and len(p["blocks"]) == 2 and p["blocks"][1] == b"\x01" * 16
    assert p["chunks"] == [(14, 8), (24, 4)] and p["records"][1][1] == 12


def test_parse_bundle_rejects_malformed():
    assert kirby_cc.parse_bundle(_bundle(bad_term=True)) is None
    assert kirby_cc.parse_bundle(b"\x00" * 8) is None
    assert kirby_cc.parse_bundle(_bundle()[:-1]) is None
    bad = bytearray(_bundle()); struct.pack_into("<H", bad, 12, 9999)
    assert kirby_cc.parse_bundle(bytes(bad)) is None


_ROMS = glob.glob(os.path.expanduser("~/.hermes/cache/scratch/kirby_cc/*.nds"))


@pytest.mark.skipif(not _ROMS, reason="owned ROM not extracted")
def test_owned_rom_all_character_bundles_parse():
    rom = NitroROM(open(_ROMS[0], "rb").read())
    n = 0
    for fid, path in rom.names.items():
        if path.rsplit("/", 1)[-1].startswith(kirby_cc.CHARACTER_PREFIXES):
            blob = rom.file(fid)
            if len(blob) >= 4 and struct.unpack_from("<I", blob)[0] == 6:
                assert kirby_cc.parse_bundle(blob) is not None, path
                n += 1
    assert n == 72
    ball = kirby_cc.parse_bundle(rom.file(next(f for f, p in rom.names.items() if p.endswith("kbynml_0000_bnd.bin"))))
    assert ball["count"] == 9 and ball["block_start"] == 5172 and ball["offset_table"][0] == 5316
