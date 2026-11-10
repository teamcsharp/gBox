import os
from pathlib import Path

import pytest

from gbox import kirby_ssu_inventory as K

ROM = Path(os.environ.get("KSSU_ROM", ""))


def test_classify_synthetic_lz10_and_raw_palette():
    # 4-byte header, size 3, one flag byte (all literals), 3 literals
    assert K.classify(bytes([0x10, 3, 0, 0, 0, 1, 2, 3])) == ("lz10", b"\x01\x02\x03")
    # raw BGR555 palette that happens to start 0x10 (col_firelion): absurd size => raw
    assert K.classify(bytes([0x10, 0x42, 0x42, 0x08]) + b"\x88" * 8)[0] == "raw"
    # plausible size but truncated copy token => invalid, not an exception
    assert K.classify(bytes([0x10, 9, 0, 0, 0x80, 0x00]))[0] == "lz10-invalid"


def test_bgr555_palette():
    assert K.bgr555_palette(b"\xff\x7f\x00\x00") == [(248, 248, 248), (0, 0, 0)]


@pytest.mark.skipif(not ROM.is_file(), reason="set KSSU_ROM to the extracted owned .nds")
def test_owned_rom_inventory():
    inv = K.inventory(ROM.read_bytes())
    assert inv["sha256"] == K.SHA256
    assert inv["files"] == 1886
    assert inv["kinds"] == {"lz10": 814, "raw": 1072, "lz10-invalid": 0}
    assert inv["target_decoded_size"] == 34816 and inv["target_tiles_4bpp"] == 1088
    assert inv["target_sha256"].startswith("e502f515")


def test_obj_header_synthetic_matches_obj_kirby1up_header():
    # header of rom/stay00/obj_kirby1up (296 B: 8 tiles*32 + d4=0x28)
    b = bytes.fromhex("050000000000080001000020280000002800000020000000") + b"\0" * 272
    h = K.obj_header(b)
    assert h["tiles"] == 8 and h["frames"] == 1 and h["flags"] == 0x2000 and h["size_ok"]
    assert K.obj_header(b"\x10" + b"\0" * 30) is None


@pytest.mark.skipif(not ROM.is_file(), reason="set KSSU_ROM to the extracted owned .nds")
def test_owned_rom_obj_census():
    c = K.obj_census(ROM.read_bytes())
    assert c["containers"] == 260 and c["strict"] == 140
    assert c["by_dir"]["rom/stay00"] == 6
