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
    struct.pack_into(">H", raw, 0x34, 0x1C)
    struct.pack_into(">H", raw, 0x36, first)      # first block
    struct.pack_into(">H", raw, 0x38, count)      # block count
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


REAL_CARD = r"D:\gBox\runtime\dolphin\Dolphin-x64\User\GC\MemoryCardA.USA.raw"


@pytest.mark.skipif(not __import__("pathlib").Path(REAL_CARD).is_file(), reason="the card is not on this machine")
def test_the_real_card_lists_the_three_psos_saves_with_real_blocks():
    """The card Dolphin actually wrote at 12:57 today: the PSO saves are there and they have data.

    The lane's reader reported every PSO entry at first block 0xFFFF and count 0 because it read the block fields at
    0x3A instead of 0x36/0x38. With the fields read correctly the entries chain contiguously (5+1, 6+4, 10+4, 14+3,
    17+11, 28+10), which is also the proof that the directory at 0x2000 is the right one.
    """
    card = M.read(REAL_CARD)
    saves = [e for e in M.saves(card) if e["game"] == "GPOE"]
    by_name = {e["name"]: (e["first_block"], e["blocks"]) for e in saves}
    assert by_name["PSO_SYSTEM"] == (14, 3)
    assert by_name["PSO_CHARACTER"] == (17, 11)
    assert by_name["PSO_GUILDCARD"] == (28, 10)
    starts = sorted(by_name.values())
    assert all(b[0] >= a[0] + a[1] for a, b in zip(starts, starts[1:])), starts   # contiguous allocation


@pytest.mark.skipif(not __import__("pathlib").Path(REAL_CARD).is_file(), reason="the card is not on this machine")
def test_the_character_save_begins_with_its_ascii_header():
    card = M.read(REAL_CARD)
    entry = next(e for e in M.saves(card) if e["name"] == "PSO_CHARACTER")
    data = card[entry["first_block"] * M.BLOCK: entry["first_block"] * M.BLOCK + entry["bytes"]]
    assert data[:0x20].startswith(b"PSO EPISODE I & II Plus")
    assert data[0x20:0x40].startswith(b"CHARACTER_FILE")


def test_a_two_megabyte_card_is_accepted(tmp_path):
    path = tmp_path / "small.raw"
    path.write_bytes(bytes(2 * 1024 * 1024))
    assert len(M.read(path)) == 2 * 1024 * 1024
