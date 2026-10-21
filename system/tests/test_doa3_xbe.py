"""DOA3 XBE select-table and fighter display-name mapping.

Pins the two 19-entry select tables measured in the owned ``default.xbe`` (character-code table
at 0x1E7BD8, display-name table at 0x2FD650) and the nickname -> display-name mapping that the
cast layer reports for coverage. The four families whose code->name link still needs the XBE
character-table RE stage are reported as pending, never guessed.
"""
import pytest

from gbox import doa3_inventory as d3

REAL_XBE = ("/home/ehm_eckx/gBox_alt/gbox-cache/b8edf7040116f3aa/extract/"
            "Dead or Alive 3/default.xbe")

EXPECTED_DISPLAY = {
    "kasumi": "Kasumi", "ayane": "Ayane", "leifang": "Leifang", "tina": "Tina",
    "zack": "Zack", "bass": "Bass", "genfu": "Gen Fu", "bayman": "Bayman",
    "janlee": "Jann Lee", "tengu": "Tengu", "ryu": "Ryu Hayabusa",
    "karate": "Ein", "ninja": "Hayate", "suiken": "Brad Wong", "bosnin": "Genra",
    "sambo": "Leon", "hika": "Helena",
}
EXPECTED_PENDING = {"koryu", "gokei", "chin"}


def _code_sig() -> bytes:
    return b"".join(c.encode("latin-1") + b"\x00" for c in d3.XBE_SELECT_CODE_TABLE)


def _name_blob() -> bytes:
    return b"".join(n.upper().replace(" ", "-").encode("latin-1") + b"\x00"
                    for n in d3.XBE_SELECT_NAMES)


def test_display_mapping_and_pending_cover_every_family():
    # The 20 archive families are exactly the mapped + pending sets, no overlap.
    fams = {"zack", "tina", "janlee", "karate", "ryu", "kasumi", "genfu", "hika",
            "bayman", "bass", "ninja", "leifang", "ayane", "koryu", "tengu",
            "bosnin", "suiken", "gokei", "chin", "sambo"}
    assert set(d3.FIGHTER_DISPLAY) | set(d3.DISPLAY_MAPPING_PENDING) == fams
    assert set(d3.FIGHTER_DISPLAY) & set(d3.DISPLAY_MAPPING_PENDING) == set()
    assert d3.FIGHTER_DISPLAY == EXPECTED_DISPLAY
    assert set(d3.DISPLAY_MAPPING_PENDING) == EXPECTED_PENDING


def test_fighter_display_name():
    assert d3.fighter_display_name("kasumi") == "Kasumi"
    assert d3.fighter_display_name("ryu") == "Ryu Hayabusa"
    assert d3.fighter_display_name("karate") == "Ein"
    assert d3.fighter_display_name("hika") == "Helena"
    assert d3.fighter_display_name("koryu") is None
    assert d3.fighter_display_name("chin") is None
    assert d3.fighter_display_name("not-a-family") is None


def test_xbe_select_code_table_recovers_the_pinned_19_codes():
    buf = bytearray(d3.XBE_SELECT_CODE_TABLE_OFFSET + len(_code_sig()) + 8)
    buf[d3.XBE_SELECT_CODE_TABLE_OFFSET:
        d3.XBE_SELECT_CODE_TABLE_OFFSET + len(_code_sig())] = _code_sig()
    assert d3.xbe_select_code_table(bytes(buf)) == list(d3.XBE_SELECT_CODE_TABLE)


def test_xbe_select_code_table_rejects_foreign_build():
    with pytest.raises(ValueError):
        d3.xbe_select_code_table(b"XBEH" + b"\x00" * 4096)


def test_xbe_select_name_table_recovers_the_pinned_19_names():
    blob = bytearray(d3.XBE_SELECT_NAME_TABLE_OFFSET + len(_name_blob()) + 8)
    blob[d3.XBE_SELECT_NAME_TABLE_OFFSET:
         d3.XBE_SELECT_NAME_TABLE_OFFSET + len(_name_blob())] = _name_blob()
    got = d3.xbe_select_name_table(bytes(blob))
    assert got == [n.upper().replace(" ", "-") for n in d3.XBE_SELECT_NAMES]


def test_xbe_select_tables_against_owned_build():
    # Real-data check: only runs where the owned extracted build is cached.
    from pathlib import Path
    if not Path(REAL_XBE).is_file():
        pytest.skip("owned DOA3 default.xbe not cached")
    data = Path(REAL_XBE).read_bytes()
    codes = d3.xbe_select_code_table(data)
    assert codes == list(d3.XBE_SELECT_CODE_TABLE)
    names = d3.xbe_select_name_table(data)
    assert names == [n.upper().replace(" ", "-") for n in d3.XBE_SELECT_NAMES]
