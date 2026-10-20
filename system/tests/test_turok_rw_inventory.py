"""Turok: Rage Wars (USA) cart inventory: synthetic structure + owned-ROM checks."""
import os
import struct
from pathlib import Path

import pytest

from gbox import turok_rw_inventory as rw

ROM_CACHE = Path.home() / "gBox_alt/gbox-cache" / "ab1614e77bd3b522" / "source.zip"
SOURCE = Path(os.environ.get("GBOX_TUROK_RW_SOURCE", ROM_CACHE))
SOURCE_SHA256 = "c2ff373e2f54b272775215258953c96223503c9764312a1ee4ee978670b02fb3"
ROM_SHA256 = "0433043aaba2649bdd1fe717c4020550ac663c0362527aa082490f5977a3e46b"


def _set(blocks: list[bytes]) -> bytes:
    hdr = 4 + 4 * (len(blocks) + 1)
    hdr = (hdr + 15) & ~15
    offs, pos = [], hdr
    for b in blocks:
        offs.append(pos)
        pos += len(b)
    offs.append(pos)
    out = struct.pack(f">I{len(offs)}I", len(blocks), *offs)
    return out.ljust(hdr, b"\0") + b"".join(blocks)


def test_find_cart_root_synthetic():
    obj = _set([b"I" * 8, b"G" * 8, b"A" * 8, b"S" * 8])
    root = _set([_set([obj])] + [b"x" * 8] * (rw.CART_ROOT_BLOCKS - 1))
    rom = b"\0" * 0x1000 + b"\0" * 0x40 + root
    assert rw.find_cart_root(rom) == 0x1040


def test_find_cart_root_rejects_wrong_block_count():
    obj = _set([b"I" * 8, b"G" * 8, b"A" * 8, b"S" * 8])
    root = _set([_set([obj])] + [b"x" * 8] * 20)  # Turok 2 shape: 21 blocks
    assert rw.find_cart_root(b"\0" * 0x1000 + root) is None


def test_select_names_stops_at_lowercase():
    blob = b"TUROK\0ADON\0\0\0capture \0FOO\0"
    rom = b"\0" * 0x10 + blob
    assert rw.select_names(rom, 0x10) == ["TUROK", "ADON"]


def test_header_requires_z64():
    with pytest.raises(ValueError):
        rw.header(b"\x37\x80\x40\x12" + b"\0" * 0x1000)


@pytest.mark.skipif(not SOURCE.exists(), reason="owned Rage Wars ROM not cached")
def test_owned_rom_inventory():
    import hashlib
    from gbox import n64_rom
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == SOURCE_SHA256
    rom = n64_rom.read(SOURCE)
    assert hashlib.sha256(rom).hexdigest() == ROM_SHA256
    h = rw.header(rom)
    assert (h["serial"], h["version"], h["ipl3_crc32"]) == ("NRWE", 0, "90bb6cb5")
    assert rw.find_cart_root(rom) == rw.CART_ROOT_OFFSET
    inv = rw.inventory(rom)
    go = inv["graphic_objects"]
    assert (go["total"], go["valid"], go["animated"]) == (347, 347, 90)
    assert go["geometry_parts_rnc_ok"] == 386 and not go["geometry_parts_fail"]
    assert go["geometry_unpacked_bytes"] == 954496
    p = go["objects"][174]
    assert (p["anim_type"], p["anims"], p["geometry_parts"]) == (1120, 44, 37)
    assert inv["object_types"]["n"] == 347
    ts = inv["texture_sets"]
    assert (ts["total"], ts["rnc_ok"], ts["rnc_fail"]) == (507, 507, [])
    assert ts["format_counts"] == {"CI8_RGBA": 272, "CI4_RGBA": 180, "CI4_IA": 55}
    assert inv["levels"] == {"total": 37, "blocks_per_level": {13: 37}}
    assert inv["characters"]["select_names"] == rw.SELECT_NAMES
    enum = inv["characters"]["player_character_enum"]
    assert enum["names"][0] == "PLAYER_CHARACTER_TUROK"
    assert "PLAYER_CHARACTER_SNIPER" in enum["names"]
    assert len(enum["offsets"]["PLAYER_CHARACTER_TUROK"]) == 2
