"""Turok: Dinosaur Hunter (NTUE Rev B) cart inventory and RNC decoders.

Fixtures are real blocks extracted from the owned ROM (v1.2 z64), embedded
here so the decoders are exercised without the ROM present.  Each decode is
checked against the block's own header CRC-16, so a wrong bit reader cannot
pass silently.
"""
import os

import pytest

from gbox import turok_inventory as ti


# Geometry indexed set of graphic object 1 (ROM 0x2C48), RNC method 2:
# { count=2, offsets 0x10/0x18/0x70 } -> 112 bytes unpacked.
RNC2_GEOMETRY = bytes.fromhex(
    "524e4302000000700000002fc341abcf020119000002c703101c031803727003c4"
    "0001c91758930f033823200330e30348d0032b004d0433e7083f189e03130800"
)

# A SoundEffects sub-block (ROM 0x414128), RNC method 1:
# { count=5 } indexed set -> 216 bytes unpacked.
RNC1_SOUNDSUB = bytes.fromhex(
    "524e4301000000d800000065932721f4000194101a42042234336544464400ba"
    "00452205209148385060241270d8718a042c6a03c50980a8e4d2441957158392"
    "c4ccab8c449301512b5702ff8076fe7f8061fc44bcd2c15fa410065ee910bfb6"
    "696cb1c4a339272eec949cf8d5a33c7fc1f201a4473c01"
)


def test_crc16_check_value():
    assert ti.crc16(b"123456789") == 0xBB3D


def test_decode_rnc2_geometry_fixture():
    out = ti.decode_rnc(RNC2_GEOMETRY)
    assert len(out) == 112
    assert out[:4] == b"\x00\x00\x00\x02"
    blocks = ti.parse_indexed(out, 0)
    assert blocks == [(0x10, 8), (0x18, 88)]


def test_decode_rnc1_sound_sub_fixture():
    out = ti.decode_rnc(RNC1_SOUNDSUB)
    assert len(out) == 216
    blocks = ti.parse_indexed(out, 0)
    assert blocks is not None and len(blocks) == 5


def test_decode_rnc_rejects_corruption():
    corrupt = bytearray(RNC2_GEOMETRY)
    corrupt[-1] ^= 0xFF
    with pytest.raises(ValueError):
        ti.decode_rnc(bytes(corrupt))


def test_decode_rnc_rejects_bad_magic():
    with pytest.raises(ValueError):
        ti.decode_rnc(b"XYZ\x01" + RNC2_GEOMETRY[4:])


def test_canonical_codes_reversed_for_low_bit_first():
    codes = ti._canonical_codes([2, 1, 2])
    assert codes == [(2, 1), (1, 0), (2, 3)]


def test_parse_indexed_rejects_junk():
    assert ti.parse_indexed(b"\x00\x00\x00\x02\xff\xff\xff\xff", 0) is None
    assert ti.parse_indexed(b"\x00\x00\x00\x00", 0) is None  # zero blocks
    assert ti.parse_indexed(b"", 0) is None


def test_parse_indexed_synthetic():
    # count 2, offsets 0x14 / 0x18 / 0x1C, two 4-byte blocks (28 bytes total)
    body = (
        b"\x00\x00\x00\x02"
        b"\x00\x00\x00\x14" b"\x00\x00\x00\x18" b"\x00\x00\x00\x1c"
        b"AAAA" b"BBBB" b"CCCC" b"DDDD"
    )
    assert ti.parse_indexed(body, 0) == [(0x14, 4), (0x18, 4)]


@pytest.mark.skipif(
    not os.path.exists(os.path.expanduser("~/gbox-cache/34ab9ef38aebcaac/rom.z64")),
    reason="owned ROM not staged on this host",
)
def test_cart_root_from_owned_rom():
    rom = open(os.path.expanduser("~/gbox-cache/34ab9ef38aebcaac/rom.z64"), "rb").read()
    inv = ti.inventory(rom)
    assert inv["cart_root"] == 0x1F00
    colls = inv["collections"]
    assert set(colls) == set(ti.CART_ROOT_NAMES)
    assert colls["GraphicObjects"]["blocks"] == 674
    assert colls["TextureSets"]["blocks"] == 1033
    assert colls["Levels"]["blocks"] == 51
    for name in ("ObjectAttributes", "ParticleEffects", "SoundEffects"):
        assert colls[name]["crc_ok"] is True, name
    go = inv["graphic_objects"]
    assert go["total"] == 674 and go["valid"] == 674
    ts = inv["texture_sets"]
    assert ts["total"] == 1033 and ts["valid"] == 1033 and ts["crc_failures"] == 0
    lv = inv["levels"]
    assert lv["total"] == 51 and lv["valid"] == 51
