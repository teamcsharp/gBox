"""The GameCube memory card: what saves it holds, and whether the PSO ones have any data at all."""
import struct

import pytest

from gbox import pso_memcard as M


def _entry(game=b"GPOE", company=b"8P", name=b"PSO_CHARACTER", first=5, count=2, modified=0x3285614C):
    raw = bytearray(0x40)
    raw[0:4] = game
    raw[4:6] = company
    raw[6] = 0xFF
    raw[7] = len(name)
    raw[0x08:0x08 + len(name)] = name
    struct.pack_into(">I", raw, 0x28, modified)
    struct.pack_into(">I", raw, 0x2C, 0x40)
    struct.pack_into(">H", raw, 0x30, 2)
    struct.pack_into(">H", raw, 0x32, 3)
    raw[0x34] = 0x1C
    struct.pack_into(">H", raw, 0x36, 0x0E)
    struct.pack_into(">H", raw, 0x38, 3)
    struct.pack_into(">HH", raw, 0x3A, first, count)
    return bytes(raw)


def _card(*entries, bat_next=None):
    card = bytearray(M.CARD_SIZE)
    for i, raw in enumerate(entries):
        card[i * M.ENTRY:i * M.ENTRY + M.ENTRY] = raw
    for block, nxt in (bat_next or {}).items():
        struct.pack_into(">H", card, M.BAT + block * M.ENTRY, nxt)
    return bytes(card)


def test_a_card_entry_is_read_with_its_fields():
    found = M.entries(_card(_entry()))
    assert len(found) == 1
    e = found[0]
    assert e["game"] == "GPOE" and e["company"] == "8P" and e["name"] == "PSO_CHARACTER"
    assert e["first_block"] == 5 and e["blocks"] == 2 and e["bytes"] == 2 * M.BLOCK and e["has_data"] is True


def test_an_entry_with_no_blocks_is_reported_as_having_no_data():
    found = M.entries(_card(_entry(first=M.FIRST_BLOCK_FREE, count=0)))
    assert found[0]["has_data"] is False and M.chain(_card(_entry(first=0xFFFF, count=0)), found[0]) == []


def test_the_block_chain_follows_the_bat():
    card = _card(_entry(first=5, count=3), bat_next={5: 9, 9: 12, 12: 0xFFFF})
    entry = M.saves(card)[0]
    assert entry["chain"] == [5, 9, 12]


def test_a_chain_that_loops_stops_instead_of_spinning():
    card = _card(_entry(first=5, count=4), bat_next={5: 9, 9: 5})
    assert M.saves(card)[0]["chain"] == [5, 9]


def test_only_real_entries_are_listed():
    junk = bytes(0x40)
    card = _card(junk, _entry(name=b"PSO_SYSTEM", first=0xFFFF, count=0), junk)
    found = M.entries(card)
    assert [e["name"] for e in found] == ["PSO_SYSTEM"]


def test_the_lane_card_has_three_psos_saves_and_none_of_them_has_data():
    import pathlib
    path = pathlib.Path(r"D:\gBox\runtime\dolphin\Dolphin-x64\User\GC\MemoryCardA.USA.raw")
    if not path.is_file():
        pytest.skip("the card is not on this machine")
    card = M.read(path)
    found = M.saves(card, "GPOE")
    assert sorted(e["name"] for e in found) == ["PSO_CHARACTER", "PSO_GUILDCARD", "PSO_SYSTEM"]
    assert all(e["has_data"] is False and e["chain"] == [] for e in found)
