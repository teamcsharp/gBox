"""Tests for gbox.ssb64_inventory: LBTableEntry parsing, table location,
VPK0 decoding and the fighter file map."""
import os
import struct

import pytest

from gbox import ssb64_inventory as s


def entry(offset=0, compressed=0, rint=0xFFFF, csize=16, rext=0xFFFF, dsize=16):
    flags = (0x80000000 if compressed else 0) | (offset & 0x7FFFFFFF)
    return struct.pack(">IHHHH", flags, rint, csize, rext, dsize)


class BitWriter:
    """MSB-first bit writer matching the VPK0 stream order."""

    def __init__(self):
        self.bits = []

    def write(self, value, count):
        for i in range(count - 1, -1, -1):
            self.bits.append((value >> i) & 1)

    def bytes(self):
        out = bytearray((len(self.bits) + 7) // 8)
        for i, bit in enumerate(self.bits):
            out[i >> 3] |= bit << (7 - (i & 7))
        return bytes(out)


def vpk0_stream(size, sample_method, offsets_tree, lengths_tree, data):
    """Encode a VPK0 stream: "vpk0" magic, u32 BE size, u8 sample method,
    two trees (list of (is_node, value) tuples plus the trailing end
    marker), then data bit chunks. Tree leaf values are bit counts."""
    w = BitWriter()
    w.write(0x76706B30, 32)  # b"vpk0"
    w.write(size, 32)
    w.write(sample_method, 8)
    for tree in (offsets_tree, lengths_tree):
        for is_node, value in tree:
            w.write(1 if is_node else 0, 1)
            if not is_node:
                w.write(value, 8)
        w.write(1, 1)  # node with <2 entries on the stack ends the tree
    for value, count in data:
        w.write(value, count)
    return w.bytes()


# Trees whose single leaf encodes values in 0 bits (all-zero code).
LEAF0 = [(False, 0)]


def test_parse_entry_fields():
    e = s.parse_entry(entry(offset=0x1234, compressed=1, rint=3, csize=20,
                             rext=7, dsize=40), 0)
    assert e.data_offset == 0x1234
    assert e.is_compressed is True
    assert e.reloc_intern == 3
    assert e.reloc_extern == 7
    assert e.compressed_size == 20
    assert e.decompressed_size == 40
    assert e.stored_bytes == 80
    assert e.decompressed_bytes == 160


def test_parse_entry_rejects_short():
    with pytest.raises(ValueError):
        s.parse_entry(b"\x00" * 11, 0)


def test_entry_plausibility_rules():
    good = s.parse_entry(entry(), 0)
    assert s._entry_plausible(good, 0x200000, 0x1AC870)
    # data_begin + data_offset + stored_bytes must fit data_end.
    over = s.parse_entry(entry(offset=0x200000, csize=0x2000), 0)
    assert not s._entry_plausible(over, 0x200000, 0)
    zero = s.parse_entry(entry(csize=0), 0)
    assert not s._entry_plausible(zero, 0x200000, 0)
    bad_reloc = s.parse_entry(entry(csize=16, rint=17), 0)
    assert not s._entry_plausible(bad_reloc, 0x200000, 0)


def test_vpk0_roundtrip_literals():
    payload = b"\x01\x02\x03\x04"
    data = []
    for byte in payload:
        data += [(0, 1), (byte, 8)]
    stream = vpk0_stream(len(payload), 0, LEAF0, LEAF0, data)
    assert s.vpk0_decode(stream, len(payload)) == payload


def test_vpk0_backreference():
    # "ABAB": literal A, literal B, backref dist 2 len 2.
    # Trees: single leaves with 2-bit values; the backref codes are
    # offset value 2 (2 bits) then length value 2 (2 bits).
    data = [(0, 1), (0x41, 8), (0, 1), (0x42, 8), (1, 1), (2, 2), (2, 2)]
    stream = vpk0_stream(4, 0, [(False, 2)], [(False, 2)], data)
    assert s.vpk0_decode(stream, 4) == b"ABAB"


def test_vpk0_header_mismatch_rejected():
    data = [(0, 1), (0x41, 8)]
    stream = vpk0_stream(8, 0, LEAF0, LEAF0, data)
    assert s.vpk0_decode(stream, 8) is None


def test_vpk0_bad_backref_rejected():
    # Backref distance larger than the output so far.
    data = [(1, 1), (2, 2), (2, 2)]
    stream = vpk0_stream(4, 0, [(False, 2)], [(False, 2)], data)
    assert s.vpk0_decode(stream, 4) is None


def test_load_names_from_data_file():
    names = s.load_names()
    assert names.get(0) == "MNCommon"
    assert names.get(202) == "MarioMainMotion"
    assert names.get(203) == "MarioMain"
    assert names.get(250) == "BossMain"
    assert len(names) >= 2000


def test_fighter_map_covers_twelve_roster():
    fighters = {k: s.FIGHTERS[k] for k in s.ROSTER}
    assert len(fighters) == 12
    assert fighters["mario"] == (215, 217)   # US 202..204 shifted +13
    assert fighters["ness"] == (251, 253)    # US 238..240 shifted +13
    assert s.FIGHTERS["boss"] == (262, 263)  # US 249..250 shifted +13
    assert s.FIGHTERS["mario"] == (s.us_to_eur(202), s.us_to_eur(204))
    assert len(s.POLYGON_TEAM) == 12
    for (lo, hi) in fighters.values():
        assert 215 <= lo <= hi <= 261


# ---- region detection / USA numbering (#1605) ----------------------------

def _header(cart=b"NALE"):
    rom = bytearray(0x40)
    rom[:4] = b"\x80\x37\x12\x40"
    rom[0x20:0x34] = b"SMASH BROTHERS      "
    rom[0x3B:0x3F] = cart
    return bytes(rom)


def test_detect_region_from_cart_id():
    assert s.detect_region(_header(b"NALE")) == "us"
    assert s.detect_region(_header(b"NALP")) == "eur"
    with pytest.raises(ValueError):
        s.detect_region(_header(b"NALJ"))      # Japan: different table
    with pytest.raises(ValueError):
        s.detect_region(_header(b"NSME"))      # not SSB64
    with pytest.raises(ValueError):
        s.detect_region(b"\x37\x80\x40\x12" + _header()[4:])  # byte-swapped


def test_us_ids_are_decomp_ids_and_eur_is_shifted():
    assert s.to_us_id("us", 202) == 202
    assert s.to_us_id("eur", 215) == 202
    assert s.fighters_for("us")["mario"] == (202, 204)
    assert s.fighters_for("eur")["mario"] == (215, 217)
    assert s.fighters_for("us")["boss"] == (249, 250)
    names = s.load_names()
    for fighter, (lo, hi) in s.fighters_for("us").items():
        for fid in range(lo, hi + 1):
            assert names[s.to_us_id("us", fid)].lower().lstrip("nmg").startswith(
                fighter.lstrip("nmg")[:4]), (fighter, fid, names[fid])


US_ROM = os.environ.get("GBOX_SSB64_US_ROM")


@pytest.mark.skipif(not US_ROM or not os.path.isfile(US_ROM or ""),
                    reason="owned SSB64 USA z64 not available (GBOX_SSB64_US_ROM)")
def test_owned_usa_rom_inventory():
    m = s.inventory(US_ROM, verify=True)
    assert m["region"] == "us" and m["cart_id"] == "NALE"
    assert m["decomp_baserom"] is True
    assert m["table_addr"] == 0x1AC870 and m["file_count"] == s.US_FILE_COUNT
    assert m["decode"] == {"ok": 2132, "failed": 0}
    links = m["fighter_links"]
    assert links["mario"]["main"] == 203 and links["mario"]["models"] == [296]
    assert links["link"]["linked"]["324"] == "LinkModel"
    assert links["boss"]["models"] == [344]
    for fighter in s.ROSTER:
        assert links[fighter]["models"], fighter
