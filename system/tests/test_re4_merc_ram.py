"""Mercenaries state from RAM: layouts from the G4BE08 decompilation, checked against a stand-in memory.

The values here are the ones a round report has been inferring from screenshots - above all `rank` - so the tests care
about the two ways that can go wrong: reading the wrong field, and accepting an address that is not the work block.
"""
import struct

import pytest

from gbox import re4_merc_ram as M


class Mem:
    """A flat memory the reader can `rd` from, with writes dropped outside its span."""

    def __init__(self, base=0x80271AEC, size=0x100):
        self.base = base
        self.data = bytearray(size)

    def addr(self, offset):
        return self.base + offset

    def put(self, offset, value, kind="<I"):
        struct.pack_into(kind, self.data, offset, value)

    def rd(self, address, length):
        offset = address - self.base
        if offset < 0 or offset + length > len(self.data):
            raise OSError(f"unmapped read at {address:#x}")
        return bytes(self.data[offset:offset + length])


@pytest.fixture
def merc():
    mem = Mem()
    mem.put(0x00, 184_500)          # score
    mem.put(0x04, 12_345)           # time, 1/100 s
    mem.put(0x08, 41, "<i")         # maxCombo
    mem.put(0x0C, 63, "<i")         # kill
    mem.put(0x10, 4, "<i")          # mode -> Wesker
    mem.put(0x14, 5, "<i")          # rank -> S
    mem.put(0x18, 200_000)          # hiScore
    mem.put(0x1C, 2, "<i")          # hiMode
    mem.put(0x20, 1, "<i")          # newRecord
    mem.put(0x24, 184_500)          # work score
    mem.put(0x28, 12, "<i")         # combo
    mem.put(0x2C, 300, "<i")        # comboTimer
    mem.put(0x38, 63, "<i")         # kill
    mem.put(0x40, 41, "<i")         # maxCombo
    mem.put(0x58, 4, "<i")          # mode
    mem.put(0x5C, 2, "<i")          # stage -> Base
    mem.put(0x78, 30_000)           # ClearScore
    return mem


def test_the_rank_is_read_and_named(merc):
    block = M.result_info(merc, merc.base)
    assert block["rank"] == 5 and block["rank_name"] == "S"
    assert block["character"] == "Wesker"
    assert (block["score"], block["time"], block["max_combo"], block["kill"]) == (184_500, 12_345, 41, 63)
    assert block["hi_score"] == 200_000 and block["new_record"] == 1


def test_the_rank_names_cover_the_whole_enum():
    assert [M.rank_name(i) for i in range(6)] == ["N", "D", "C", "B", "A", "S"]
    assert M.rank_name(6) is None and M.rank_name(-1) is None and M.rank_name(None) is None


def test_the_work_block_has_the_combo_and_the_stage(merc):
    state = M.work_state(merc, merc.base)
    assert state["combo"] == 12 and state["combo_timer"] == 300 and state["max_combo"] == 41
    assert state["stage"] == 2 and state["stage_name"] == "Base"
    assert state["clear_score"] == 30_000


def test_an_implausible_address_is_rejected_and_the_next_candidate_used(merc):
    """The point of `find_base`: a wrong address must not be reported as the work block."""
    assert M.plausible(merc, 0x80271AEC - 0x100) is False           # unmapped -> not plausible
    wrong = 0x80271AEC - 0x14                                       # a self-consistent but wrong window
    found = M.find_base(merc, [wrong, merc.base])
    assert found["found"] is True and found["base"] == merc.base
    assert found["tried"] == [wrong, merc.base]


def test_a_rank_out_of_range_makes_the_base_implausible(merc):
    merc.put(0x14, 9, "<i")                                          # no such rank
    assert M.plausible(merc, merc.base) is False
    assert M.find_base(merc, [merc.base])["found"] is False


def test_an_out_of_range_character_or_stage_is_reported_as_none(merc):
    merc.put(0x10, 99, "<i")
    merc.put(0x58, 99, "<i")
    merc.put(0x5C, 99, "<i")
    block = M.result_info(merc, merc.base)
    state = M.work_state(merc, merc.base)
    assert block["character"] is None and state["stage_name"] is None
