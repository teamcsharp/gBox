import hashlib
import os
from pathlib import Path

import pytest
from gbox import cheats
from gbox import soulcalibur_unlock as SC


def entry(**changes):
    return {"handler": "1", "address": "3370494", "value": "1", "memory_search_size": "4",
            "big_endian": "false", "cheat_type": "1", **changes}


def test_search_finds_named_unlocks_without_unrelated_all_or_substrings():
    assert cheats.match_query("unlock every character", "Unlock Hwang", "") == 1
    assert cheats.match_query("unlock all characters", "Unlock All Characters", "") == 2
    assert cheats.match_query("unlock all characters", "Mission Codes-All Attacks Hurt P1", "") == 0
    assert cheats.match_query("lock", "Unlock Hwang", "") == 0
    assert cheats.match_query("8c336dfe", "Hwang", "8C336DFE 0001") == 1


def test_real_hwang_encoding_writes_two_bytes_and_preserves_neighbors():
    ops, bad = cheats.decode_native("dreamcast", entry())
    assert not bad and ops == [("w", 0x8c336dfe, b"\x01\x00")]
    memory = bytearray(b"\xaa" * 8)
    _, _, value = ops[0]
    memory[2:2+len(value)] = value
    assert memory == b"\xaa\xaa\x01\x00\xaa\xaa\xaa\xaa"


@pytest.mark.parametrize("enum,expected", [(3,b"\x78"),(4,b"\x78\x56"),(5,b"\x78\x56\x34\x12")])
def test_native_enum_is_log2_bits_and_value_truncation_matches_retroarch(enum, expected):
    ops, bad = cheats.decode_native("dreamcast", entry(memory_search_size=enum, value="0x12345678"))
    assert not bad and ops[0][2] == expected
    ops, bad = cheats.decode_native("dreamcast", entry(memory_search_size=enum, value="0x12345678", big_endian=True))
    assert not bad and ops[0][2] == expected[::-1]


def test_native_default_is_one_byte_and_base_zero_parsing():
    e = entry(address="020", value="0x1ff")
    del e["memory_search_size"]
    ops, bad = cheats.decode_native("dreamcast", e)
    assert not bad and ops == [("w", 0x8c000010, b"\xff")]


@pytest.mark.parametrize("changes", [
    {"handler":"0"}, {"handler":True}, {"cheat_type":"4"}, {"cheat_type":"2"},
    {"memory_search_size":"0"}, {"memory_search_size":"1"}, {"memory_search_size":"2"},
    {"memory_search_size":"6"}, {"memory_search_size":"bogus"}, {"memory_search_size":False},
    {"address":"-1"}, {"address":"0x1000000"}, {"address":"0xffffff"},
    {"address":"0x8c336dfe"}, {"address":None}, {"address":1.5},
    {"value":"-1"}, {"value":"0x100000000"}, {"value":"12garbage"}, {"value":True},
    {"repeat_count":"0"}, {"repeat_count":"2"}, {"repeat_add_to_address":"invalid"},
    {"repeat_add_to_value":"-1"}, {"rumble_type":"1"}, {"big_endian":"not-a-bool"},
])
def test_unhandled_or_invalid_entries_produce_no_partial_write(changes):
    ops, bad = cheats.decode_native("dreamcast", entry(**changes))
    assert not ops and bad


def test_exact_ram_end_allowed_but_never_wrapped():
    assert cheats.decode_native("dreamcast", entry(address="0xfffffe"))[0] == [("w",0x8cfffffe,b"\x01\x00")]
    assert cheats.decode_native("dreamcast", entry(address="0xffffff",memory_search_size=3))[0] == [("w",0x8cffffff,b"\x01")]
    for platform in ("naomi", "psx", "n64", "gamecube", ""):
        assert cheats.decode_native(platform, entry())[0] == []


def test_soulcalibur_profile_separates_database_encoding_from_gameplay():
    p = SC.profile()
    assert p["verified"] == [] and not p["gameplay_verified"] and not p["complete_unlock_profile"]
    assert set(p["database_entries"]) == {"Hwang", "Yoshimitsu", "Lizardman", "Siegfried", "Rock"}
    ops = SC.unlock_ops()
    assert len(ops) == 5
    assert all(o["width"] == 2 and o["hex_bytes"] == "0100" and not o["gameplay_verified"] for o in ops)


def test_installed_soulcalibur_database_encodings():
    path = Path(os.environ.get("GBOX_SOULCALIBUR_CHEAT_FILE", "/home/ehm_eckx/gBox/system/gbox-data/cheatdb/libretro-database/cht/Sega - Dreamcast/Soul Calibur.cht"))
    if not path.is_file():
        pytest.skip("installed cheat database not available")
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == SC.DATABASE_SHA256
    rows = cheats.parse_cht(data.decode())
    unlocks = [r for r in rows if r.get("desc", "").startswith("Unlock ")]
    assert len(unlocks) == 5
    for row in unlocks:
        name = row["desc"].removeprefix("Unlock ")
        ops, bad = cheats.decode_native("dreamcast", row)
        assert not bad and ops == [("w",0x8c000000+SC.UNLOCK_FLAGS[name],b"\x01\x00")]
        assert cheats.match_query("unlock every character",row["desc"],row.get("code", "")) > 0
