import struct
import zipfile
from pathlib import Path

import pytest

from gbox import n64_rom, oot_inventory as OI, oot_swap

OWNED = Path.home() / "gBox_alt/gbox-cache/1aa2e4bb5797493f/source.zip"


def _object_with_tail_skeleton() -> bytes:
    """Three 12-byte limbs, their pointer table, then a 12-byte FlexSkeletonHeader that ENDS the object."""
    limbs = [((0, 0, 0), 1, 0xFF, 0x06000100), ((10, 0, 0), 0xFF, 2, 0), ((0, 10, 0), 0xFF, 0xFF, 0x06000108)]
    d = bytearray()
    for (x, y, z), ch, sb, dl in limbs:
        d += struct.pack(">hhhBBI", x, y, z, ch, sb, dl)
    d += struct.pack(">3I", 0x06000000, 0x0600000C, 0x06000018)       # limb table at 0x24
    d += struct.pack(">IB3xB3x", 0x06000024, 3, 2)                   # header at 0x30, last 12 bytes
    assert len(d) == 0x3C
    return bytes(d)


def test_skeleton_header_at_object_end_is_found():
    obj = _object_with_tail_skeleton()
    assert OI.find_skeletons(obj) == [0x30]
    assert oot_swap.find_skeletons(obj) == [0x30]                    # the swap scan had an off-by-one here
    s = OI.skeleton_summary(obj, 0x30)
    assert (s["limbs"], s["lod"], s["limbs_with_dl"], s["flex_dlcount"]) == (3, False, 2, 2)


def test_bad_sibling_index_is_rejected():
    obj = bytearray(_object_with_tail_skeleton())
    obj[0x0C + 7] = 9                                                 # limb 1 sibling -> 9 of 3
    assert OI.find_skeletons(bytes(obj)) == []


def test_count_animations_matches_limb_count():
    limbs = 3
    data = struct.pack(">8h", 0, 1, 2, 3, 4, 5, 6, 7)                 # frame data at 0x00
    idx = struct.pack(f">{3 * (limbs + 1)}H", *([1] * 3 * (limbs + 1)))  # joint indices at 0x10
    hdr = struct.pack(">hhIIH2x", 5, 0, 0x06000000, 0x06000010, 1)     # AnimationHeader at 0x28
    obj = data + idx + hdr + bytes(16)
    assert OI.count_animations(obj, limbs) == 1
    assert OI.count_animations(obj, 30) == 0


def test_link_animation_headers_bounded_by_link_animetion():
    keep = struct.pack(">hhI", 10, 0, 0x07000000) + struct.pack(">hhI", 10, 0, 0x07001000) + bytes(8)
    per = 22 * 6 + 2
    assert OI.link_animation_headers(keep, 10 * per) == 1
    assert OI.link_animation_headers(keep, 0x1000 + 10 * per) == 2


def test_v64_member_is_reported_and_normalized(tmp_path):
    z64 = b"\x80\x37\x12\x40" + bytes(range(4, 64))
    v64 = bytes(b for i in range(0, len(z64), 2) for b in (z64[i + 1], z64[i]))
    p = tmp_path / "g.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("Game (USA).n64", v64)                            # No-Intro names it .n64 but stores v64
    member, raw = OI.raw_source(p)
    assert member == "Game (USA).n64" and OI.byte_order(raw) == "v64 (halfword-swapped)"
    assert n64_rom.normalize(raw) == z64


@pytest.mark.skipif(not OWNED.is_file(), reason="owned OoT USA Rev B ROM not cached on this host")
def test_owned_rev_b_inventory():
    m = OI.inventory(OWNED, objects=False)
    assert m["source"]["version"] == "ntsc-1.2" and m["source"]["version_by_md5"]
    assert m["source"]["normalized_md5"] == "57a9719ad547c516342e1a15d5c28c3d"
    assert m["header"]["game_code"] == "CZLE" and m["header"]["revision"] == 2 and m["launch"]["crc_valid"]
    assert m["layout"]["files"] == 1510 and m["layout"]["gObjectTable"] == "code+0xE7F68"
    for age, off in (("adult", "0x377F4"), ("child", "0x2CF6C")):
        L = m["link"][age]
        assert L["skeleton"]["offset"] == off and L["skeleton"]["limbs"] == 21
        assert L["found_by_scan"] and L["writer_offset_ok"]
