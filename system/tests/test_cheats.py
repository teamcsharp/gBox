from gbox import cheats
from gbox import soulcalibur_unlock as SC


def test_match_query_tokenizes_unlock_request():
    # 'unlock all characters' must surface the per-character unlock codes, not return nothing.
    assert cheats.match_query("unlock all characters", "Unlock Hwang", "addr 3370494 = 1") == 1
    assert cheats.match_query("unlock all characters", "Mission Codes-All Attacks Hurt P1", "") == 1
    assert cheats.match_query("unlock all characters", "Infinite Health P1", "") == 0
    # A row matching more tokens ranks above a row matching one.
    assert cheats.match_query("unlock all characters", "Unlock All Characters", "") == 3


def test_decode_native_dreamcast_offset():
    e = {"address": "3370494", "value": "1", "memory_search_size": "4",
         "big_endian": "false", "cheat_type": "1"}
    ops, bad = cheats.decode_native("dreamcast", e)
    assert not bad and ops == [("w", 0x8C336DFE, b"\x01\x00\x00\x00")]


def test_decode_native_widths_and_endian():
    ops, bad = cheats.decode_native("dreamcast", {"address": "16", "value": "1",
                                                  "memory_search_size": "1", "big_endian": "true"})
    assert not bad and ops == [("w", 0x8C000010, b"\x01")]
    ops, bad = cheats.decode_native("dreamcast", {"address": "32", "value": "2",
                                                  "memory_search_size": "2", "big_endian": "false"})
    assert not bad and ops == [("w", 0x8C000020, b"\x02\x00")]


def test_decode_native_unsupported_stays_emulator():
    assert cheats.decode_native("dreamcast", {"address": "1", "value": "1", "cheat_type": "4"})[1]
    assert cheats.decode_native("dreamcast", {"address": "1", "value": "1", "memory_search_size": "3"})[1]
    assert cheats.decode_native("dreamcast", {"address": "", "value": "1"})[1]


def test_soulcalibur_profile_self_describing():
    p = SC.profile()
    assert p["total_unlockable"] == 9
    assert set(p["verified"]) == {"Hwang", "Yoshimitsu", "Lizardman", "Siegfried", "Rock"}
    assert set(p["missing"]) == {"Seung Mina", "Cervantes", "Edge Master", "Inferno"}


def test_soulcalibur_unlock_ops_are_cached_ram_writes():
    ops = SC.unlock_ops()
    assert len(ops) == 5
    assert all(o["value"] == 1 and (o["address"] >> 24) == 0x8C for o in ops)
