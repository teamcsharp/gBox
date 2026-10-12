"""Ocarina of Time live edits on every N64 NTSC revision (#1055/#1060/#1075/#1078/#1119/#1130): the operator's
OoT (USA) ROM is NTSC 1.0, and every zelda_oot / zelda op used to read the v1.2 SaveContext address and refuse it."""
import struct

import pytest

from gbox import oot, zelda_tool


class Fake:
    """RDRAM as a big-endian dict; read_memory / write_memory move 32-bit little-endian words like ParaLLEl."""

    def __init__(self, save=None, play=None, entrance=0x0211):
        self.mem = {}
        if save is not None:
            self.put(save + 0x1C, b"ZELDAZ")
            self.put(save + oot.S_ENTRANCE, struct.pack(">I", entrance))
            self.put(play + oot.P_NEXT_ENTRANCE, struct.pack(">H", entrance))

    def put(self, a, data):
        for i, b in enumerate(data):
            self.mem[a + i] = b

    def get(self, a, n):
        return bytes(self.mem.get(a + i, 0) for i in range(n))

    def read_memory(self, a, n):
        be = self.get(a, n)
        return b"".join(be[i:i + 4][::-1] for i in range(0, n, 4))

    def write_memory(self, a, data):
        self.put(a, b"".join(data[i:i + 4][::-1] for i in range(0, len(data), 4)))


@pytest.mark.parametrize("version", sorted(oot.LAYOUTS))
def test_layout_detects_each_revision(version):
    save, play = oot.LAYOUTS[version]
    ad = Fake(save, play)
    lay = oot.layout(ad)
    assert (lay["version"], lay["save"], lay["play"], lay["play_checked"]) == (version, save, play, True)
    assert oot.bases(ad) == (save, play) and oot.check(ad) is lay


def test_no_save_loaded_names_the_revisions():
    with pytest.raises(RuntimeError, match="load a file first.*ntsc-1.0.*ntsc-1.2"):
        oot.layout(Fake())


def test_marker_without_entrance_match_is_still_accepted():
    save, play = oot.LAYOUTS["ntsc-1.0"]
    ad = Fake(save, play)
    ad.put(play + oot.P_NEXT_ENTRANCE, struct.pack(">H", 0x0004))       # mid scene change
    lay = oot.layout(ad)
    assert lay["version"] == "ntsc-1.0" and lay["play_checked"] is False


def test_cached_layout_is_revalidated_when_the_rom_changes():
    s10, p10 = oot.LAYOUTS["ntsc-1.0"]
    ad = Fake(s10, p10)
    assert oot.layout(ad)["version"] == "ntsc-1.0"
    ad.put(s10 + 0x1C, b"\0" * 6)                                       # another ROM in the same session
    ad.put(oot.SAVE + 0x1C, b"ZELDAZ")
    assert oot.layout(ad)["version"] == "ntsc-1.2"


def test_skip_deku_tree_edits_the_ntsc10_save():
    s10, p10 = oot.LAYOUTS["ntsc-1.0"]
    ad = Fake(s10, p10)
    r = oot.skip_deku_tree(ad)
    assert r["verified"] and r["warp"] == "0x211"
    ev = struct.unpack(">H", ad.get(s10 + oot.S_EVENTCHKINF, 2))[0]
    assert ev >> 7 & 1 and ev >> 9 & 1                                   # Gohma beaten, in the 1.0 SaveContext
    assert struct.unpack(">H", ad.get(p10 + oot.P_NEXT_ENTRANCE, 2))[0] == 0x211
    assert not any(oot.SAVE <= a < oot.SAVE + oot.SAVE_SIZE for a in ad.mem)   # nothing landed at the 1.2 address
    assert "slingshot" in r["state"]["items"] and oot.state(ad)["deku_tree_done"]


def test_goto_and_items_follow_the_revision():
    s11, p11 = oot.LAYOUTS["ntsc-1.1"]
    ad = Fake(s11, p11)
    assert oot.give(ad, "hookshot", 1)["verified"]
    assert ad.get(s11 + oot.S_ITEMS + 9, 1) == b"\x0a"
    g = oot.goto(ad, "end of the shadow temple")
    assert g["place"] == "bongo bongo" and g["warp"] == "0x413"
    assert struct.unpack(">H", ad.get(p11 + oot.P_NEXT_ENTRANCE, 2))[0] == 0x413
    assert ad.get(p11 + oot.P_TRANSITION, 1) == bytes([oot.TRANS_START])


def test_zelda_tool_tables_remap_to_the_running_revision():
    s10, p10 = oot.LAYOUTS["ntsc-1.0"]
    ad = Fake(s10, p10)
    m = zelda_tool.Mem(ad, "n64")
    m.remap = oot.remap(ad)
    m.wr(oot.SAVE + 0x34, struct.pack(">H", 500))                       # rupees, written against the v1.2 table
    assert struct.unpack(">H", ad.get(s10 + 0x34, 2))[0] == 500
    assert m.rd(oot.SAVE + 0x34, 2) == struct.pack(">H", 500)
    assert m.log[-1]["addr"] == hex(oot.SAVE + 0x34)                     # the log keeps the table address
    code = 0x800A77BC                                                    # a code address is not moved
    assert m.remap(code) == code and m.remap(oot.SAVE + oot.SAVE_SIZE) == oot.SAVE + oot.SAVE_SIZE


def test_zelda_tool_run_on_ntsc10():
    s10, p10 = oot.LAYOUTS["ntsc-1.0"]
    ad = Fake(s10, p10)
    out = zelda_tool.run(ad, "Legend of Zelda, The: Ocarina of Time (USA)", "n64", op="rupees", count=321)
    assert out["game"] == "Ocarina of Time"
    assert struct.unpack(">H", ad.get(s10 + 0x34, 2))[0] == 321
    assert not any(oot.SAVE <= a < oot.SAVE + oot.SAVE_SIZE for a in ad.mem)
