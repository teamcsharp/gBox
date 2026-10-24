"""mm_inventory: owned-source inventory for Majora's Mask (USA, N64). Unit tests run on synthetic data; the
real-ROM integration test is opt-in through GBOX_MM_SOURCE (the owned zip path)."""

import json
import struct

import pytest

from gbox import mm_inventory as mm


def _header(title: bytes = b"ZELDA MAJORA'S MASK", crc=(0x5354631C, 0x03A2DEF0)) -> bytes:
    h = bytearray(0x40)
    h[0x10:0x18] = struct.pack(">II", *crc)
    h[0x20:0x34] = title
    h[0x3B] = ord("N")
    h[0x3E] = 0x45
    return bytes(h)


def test_identity_reads_the_header():
    ident = mm.identity(_header() + b"\x00" * 16)
    assert ident["title"] == "ZELDA MAJORA'S MASK"
    assert ident["crc"] == ["0x5354631c", "0x3a2def0"]
    assert ident["cic"] == "N"
    assert ident["region_byte"] == "0x45"
    assert ident["is_usa_retail"] is False          # random payload: not a known retail md5


def test_us_retail_md5s_are_known():
    assert mm.MM_US_MD5["2a0a8acb61538235bc1094d297fb6556"] == "mm-n64-us-compressed"
    assert mm.MM_US_MD5["f46493eaa0628827dbd6ad3ecd8d65d6"] == "mm-n64-us"


def test_dmadata_parse_and_terminator():
    data = bytearray(0x1A500 + 4 * 16)
    data[:4] = b"\x80\x37\x12\x40"
    struct.pack_into(">4I", data, 0x1A500, 0x1000, 0x2000, 0x1000, 0)         # raw file
    struct.pack_into(">4I", data, 0x1A510, 0x2000, 0x3000, 0x2000, 0x2400)   # Yaz0 file
    assert mm.dmadata(bytes(data)) == [(0x1000, 0x2000, 0x1000, 0), (0x2000, 0x3000, 0x2000, 0x2400)]


def test_object_sections_roundtrip():
    ids = struct.pack(">HHH", 0x0001, 0x0004, 0x000B) + b"\x00\x00"         # ids + terminator -> count at 0x8
    offs = struct.pack(">IIII", 28, 36, 44, 76)                              # index ends at 0x1C, file is 76 bytes
    obj = ids + struct.pack(">I", 3) + offs + bytes(76 - 28)
    sec = mm.object_sections(obj)
    assert sec["ids"] == [1, 4, 11]
    assert sec["count"] == 3
    assert sec["index_at"] == 8
    assert sec["offsets"][-1] == len(obj)


def test_object_sections_rejects_non_objects():
    with pytest.raises(ValueError):
        mm.object_sections(b"\x00" * 64)


def test_character_and_mask_tables_are_sane():
    keys = [c[0] for c in mm.CHARACTERS]
    assert keys == ["link_human", "link_fierce_deity", "link_goron", "link_zora", "link_deku", "epona_link"]
    oids = [c[1] for c in mm.CHARACTERS] + [m[1] for m in mm.MASKS]
    assert len(set(oids)) == len(oids)                 # distinct ids
    assert all(0 < o < mm.OBJECT_ID_MAX for o in oids)
    assert mm.CHARACTERS[0][1] == 0x011 and mm.CHARACTERS[1][1] == 0x010   # decomp include/tables/object_table.h


@pytest.mark.skipif(not __import__("os").environ.get("GBOX_MM_SOURCE"), reason="set GBOX_MM_SOURCE to the owned zip")
def test_real_rom_inventory():
    src = __import__("os").environ["GBOX_MM_SOURCE"]
    m = mm.inventory(src)
    assert m["rom"]["variant"] == "mm-n64-us-compressed"
    assert m["dmadata"]["entries"] == 1552
    assert m["object_table"]["in_code_dma_index"] == 31
    for c in m["playable_forms"].values():
        assert c["size_raw"] > 0


def _synthetic_player_object(pad: int = 0) -> bytes:
    """21 standard-ish limbs (16-byte LOD) + limb table + flex header at the tail, like ZAPD output."""
    n = 21
    limbs = bytearray()
    for i in range(n):
        child = i + 1 if i < n - 1 else 0xFF
        limbs += struct.pack(">hhhBBII", 0, 0, 0, child, 0xFF, 0, 0)
    tbl = b"".join(struct.pack(">I", 0x06000000 + 16 * i) for i in range(n))
    obj = bytearray(limbs) + tbl
    hdr_at = len(obj) + pad
    obj += b"\x00" * pad + struct.pack(">IBBBBBBBB", 0x06000000 + len(limbs), n, 0, 0, 0, 18, 0, 0, 0)
    return bytes(obj + b"\x00" * ((-len(obj)) % 16)), hdr_at


@pytest.mark.parametrize("pad", [0, 12])
def test_tail_skeleton_finds_zapd_header(pad):
    obj, hdr = _synthetic_player_object(pad)
    assert mm.tail_skeleton(obj) == hdr


def test_tail_skeleton_rejects_non_skeleton():
    assert mm.tail_skeleton(b"\x00" * 0x100) is None


@pytest.mark.skipif(not __import__("os").environ.get("GBOX_MM_ROM"), reason="set GBOX_MM_ROM to the owned .z64")
def test_real_rom_player_skeletons():
    rom = mm.Rom(open(__import__("os").environ["GBOX_MM_ROM"], "rb").read())
    rom.object_table()
    from gbox.oot_writer import skeleton
    for key in ("link_human", "link_fierce_deity", "link_goron", "link_zora", "link_deku"):
        obj_id = next(c[1] for c in mm.CHARACTERS if c[0] == key)
        obj = rom.object(obj_id)
        sk = skeleton(obj, mm.tail_skeleton(obj))
        assert sk["count"] == 21 and sk["dlcount"] == 18 and sk["lod"]
        assert [(l["child"], l["sibling"]) for l in sk["limbs"]][:3] == [(1, 255), (2, 9), (3, 255)]
