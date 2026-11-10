"""Same-size player-container member replacement (NB2003 writer step).

Fixtures streamed from the owned GCZ into gbox-cache (absent -> skip).
"""
import os
import struct
import zlib

import pytest

from gbox.nb2003_gtd import parse_gtd, serialize_gtd, set_character_block
from gbox.nb2003_mod import central_records, find_member, replace_member
from gbox.nfl_blitz_2003 import extract_member, load_container, scan_zip

FX = os.path.expanduser("~/gbox-cache/research/nb2003_reader_fixtures_2360/")


def _rd(n):
    try:
        with open(FX + n, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


ZIP, ZIH, GTD = (_rd("nb2003_players.zip"), _rd("nb2003_players.ziH"),
                 _rd("nb2003_ape.gtd"))
pytestmark = pytest.mark.skipif(None in (ZIP, ZIH, GTD), reason="fixtures absent")


def _modified_gtd():
    gf = parse_gtd(GTD)
    leaf = gf.leaf(0x0800FFFF, 1, 32)[0]
    from gbox.nb2003_gtd import character_block
    name, data = character_block(leaf)
    data = list(data)
    data[100] = data[100] + 1.0 if data[100] == data[100] else 1.0
    out = serialize_gtd(set_character_block(gf, data=data))
    assert out != GTD and len(out) == len(GTD)
    return out


def test_all_296_crc_verify_and_target_is_ape_gtd():
    table, members = load_container(ZIP, ZIH)
    assert len(members) == 296
    for m in members:
        extract_member(ZIP, m)  # raises on CRC/size mismatch
    assert extract_member(ZIP, find_member(ZIP, "ape.gtd")) == GTD
    assert set(central_records(ZIP)) == {m.name for m in members}


def test_noop_replace_is_byte_identical():
    assert replace_member(ZIP, "ape.gtd", GTD) == ZIP


def test_changed_gtd_only_target_changes():
    new = _modified_gtd()
    out = replace_member(ZIP, "ape.gtd", new)
    assert len(out) == len(ZIP)
    members = scan_zip(out)
    assert len(members) == 296
    same = 0
    for m in members:
        data = extract_member(out, m)  # CRC verifies incl. updated one
        if m.name == "ape.gtd":
            assert data == new
        else:
            assert data == extract_member(ZIP, find_member(ZIP, m.name))
            same += 1
    assert same == 295
    # central directory CRC updated for target only
    cd_old, cd_new = central_records(ZIP), central_records(out)
    off = cd_new["ape.gtd"]
    assert struct.unpack_from("<I", out, off + 16)[0] == zlib.crc32(new)
    diff = [i for i in range(len(ZIP)) if ZIP[i] != out[i]]
    t = find_member(ZIP, "ape.gtd")
    outside = [i for i in diff if not (t.data_offset <= i < t.data_offset + t.file_size)]
    assert len(outside) <= 8  # local-header CRC (4) + central CRC (4)


def test_size_change_and_unknown_member_rejected():
    with pytest.raises(ValueError):
        replace_member(ZIP, "ape.gtd", GTD + b"\0")
    with pytest.raises(KeyError):
        replace_member(ZIP, "nope.gtd", b"")
