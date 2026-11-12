"""Tests for gbox.tetris_psp_lu (LU package + LUSIZES.TBL parser).

Owned-ROM assertions use the byte-verified layout recorded in
gbox/tetris_psp_lu.py (GLOBAL.PSP lba 75616, 7312512 B, 256-entry pair
table, 14 live entries; LUSIZES.TBL 187 lines).
"""
import os
import struct

import pytest

from gbox import tetris_psp_lu as m

ROM = os.environ.get("TETRIS_PSP_CSO", "/mnt/gbox/hyperspin/Arcade/collections/Sony PlayStation Minis/roms/Tetris (USA).cso")
pytestmark = [pytest.mark.skipif(not os.path.exists(ROM), reason="Tetris PSP CISO not present")]

GLOBAL_SHA256 = "d49d54ee6ec41ecae17a9e7a3ae2a935f44bf2c8decf0c7bc32060d241409fcf"


def build_lu(live=(1, 5, 0x50), n_table=4):
    """Synthetic LU: header + n_table 8B pairs starting at 0x40.
    `live` is a list of (idx, a, b) non-hole entries."""
    buf = bytearray(m.HEADER_SIZE + n_table * 8 + 16)
    buf[0:4] = m.LU_MAGIC
    struct.pack_into("<III", buf, 4, 1, 0, 0x00010004)
    buf[0x10:0x10 + 6] = b"global"
    buf[0x1C:0x1C + 6] = b"tetris"
    struct.pack_into("<I", buf, 0x30, 1)
    buf[0x38:0x38 + 5] = b"Build"
    for i in range(n_table):
        struct.pack_into("<II", buf, 0x40 + i * 8, 0, 0xFFFFFFFF)
    for idx, a, b in live:
        struct.pack_into("<II", buf, 0x40 + idx * 8, a, b)
    return bytes(buf)


def test_parse_lu_synthetic():
    data = build_lu(live=[(1, 5, 0x50)], n_table=4)
    h = m.parse_lu_header(data)
    assert h.ver == 1 and h.flags == 0 and h.f0c == 0x00010004
    assert h.name1 == "global" and h.name2 == "tetris"
    assert h.section_count == 1 and h.section_name == "Build"
    assert h.table_end == 0x50 and h.table_entries == 2  # (0x50-0x40)//8
    assert h.live_pairs == [(1, 5, 0x50)] and h.holes == 1
    assert h.data_start == 0x50


def test_parse_lu_bad_magic_and_short():
    with pytest.raises(m.LuError):
        m.parse_lu_header(b"XXXX" + b"\0" * 60)
    with pytest.raises(m.LuError):
        m.parse_lu_header(bytes(m.HEADER_SIZE - 1))


def test_parse_lusizes_synthetic():
    data = (
        '"tetris\\global\\en\\global.psp"=2128\r\n'
        '"tetris\\global\\global.sbk"=631616\r\n'
        '"tetris\\readbg\\fr\\readbg.psp"=7616\r\n'
    ).encode()
    sizes, n = m.parse_lusizes_tbl(data)
    assert n == 3
    assert sizes == {
        "global/en/global.psp": 2128,
        "global/global.sbk": 631616,
        "readbg/fr/readbg.psp": 7616,
    }
    assert m.map_lusizes_path("global/en/global.psp") == "/PSP_GAME/USRDIR/TETRIS/GLOBAL/EN/GLOBAL.PSP"


def test_parse_lusizes_bad_line():
    with pytest.raises(m.LuError):
        m.parse_lusizes_tbl(b'tetris\\a.psp=5\r\n')


def test_owned_global_psp_header():
    rep = m.lu_report(ROM)
    assert rep["sha256"] == GLOBAL_SHA256
    assert rep["lba"] == 75616 and rep["size"] == 7312512
    h = rep["lu"]
    assert (h.ver, h.flags, h.f0c) == (1, 0, 0x00010004)
    assert h.name1 == "global" and h.name2 == "tetris"
    assert h.section_count == 1 and h.section_name == "Build"
    assert h.table_end == 0x840 and h.table_entries == 256
    assert h.data_start == 0x840


def test_owned_live_pairs():
    rep = m.lu_report(ROM)
    h = rep["lu"]
    assert [i for i, _, _ in h.live_pairs] == [19, 23, 32, 34, 38, 39, 40, 41, 42, 43, 67, 89, 90, 99]
    assert h.live_pairs[0] == (19, 1, 0x840)
    assert h.live_pairs[1] == (23, 47, 0x850)
    assert h.holes == 256 - len(h.live_pairs)


def test_owned_lusizes():
    rep = m.lu_report(ROM)
    assert rep["lusizes_lines"] == 187
    ls = rep["lusizes"]
    assert ls["global/global.psp"] == 7312512  # matches owned GLOBAL.PSP size
    assert ls["global/en/global.psp"] == 2128
    assert ls["global/global.sbk"] == 631616
    assert sum(1 for k in ls if k.endswith(".psp")) == 186  # matches ISO .PSP count
    assert m.map_lusizes_path("global/global.psp") == "/PSP_GAME/USRDIR/TETRIS/GLOBAL/GLOBAL.PSP"
