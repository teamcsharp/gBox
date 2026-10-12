"""RE2 Dual Shock (PSX, Claire disc) executable probe: loader tables and constraints.

Synthetic tests always run; the owned-disc tests need the chdman-extracted image
(``GBOX_RE2PSX_BIN``, default ``~/gbox-cache/2d8ef2bdbd4a58fd/disc.bin``).
"""

import hashlib
import os
import struct

import pytest

from gbox import re2psx_exe as R

BIN = os.environ.get("GBOX_RE2PSX_BIN",
                     os.path.expanduser("~/gbox-cache/2d8ef2bdbd4a58fd/disc.bin"))


def _exe(text: bytes, t_addr: int = 0x80010000, pc0: int = 0x80010000) -> bytes:
    hdr = bytearray(0x800)
    hdr[:8] = b"PS-X EXE"
    struct.pack_into("<10I", hdr, 0x10, pc0, 0, t_addr, len(text), 0, 0, 0, 0, 0x801FFFF0, 0)
    hdr[0x4C:0x4C + 9] = b"Sony test"
    return bytes(hdr) + text


def test_parse_header_and_bad_magic():
    h = R.parse_psx_exe(_exe(b"\0" * 16, pc0=0x800783C0))
    assert h["t_addr"] == 0x80010000 and h["t_size"] == 16 and h["pc0"] == 0x800783C0
    assert h["region"] == "Sony test"
    with pytest.raises(ValueError):
        R.parse_psx_exe(b"NOT-EXE!" + b"\0" * 0x800)


def test_hilo_jal_and_register_tracking():
    words = [
        0x27BDFFD8,  # addiu sp, sp, -0x28   (function entry)
        0x3C05801B,  # lui a1, 0x801b
        0x34A5FA14,  # ori a1, a1, 0xfa14    -> 0x801bfa14
        0x3C01800A,  # lui at, 0x800a
        0x00220821,  # addu at, at, v0
        0x94243FA0,  # lhu a0, 0x3fa0(at)    -> 0x800a3fa0
        0x0C004BEE,  # jal 0x80012fb8
        0x24060001,  # addiu a2, zero, 1
        0x3C02800A,  # lui v0, 0x800a
        0x2442885C,  # addiu v0, v0, -0x77a4 -> 0x8009885c
    ]
    exe = R.Exe(_exe(struct.pack("<%dI" % len(words), *words)))
    refs = R.find_hilo_refs(exe, 0x80098000, 0x800A4000)
    assert [(r["op"], r["addr"]) for r in refs] == [("lhu", 0x800A3FA0), ("addiu", 0x8009885C)]
    assert R.find_jal_callers(exe, R.CD_LOAD_FILE_VA) == [0x80010018]
    assert R.function_start(exe, 0x80010014) == 0x80010000
    sites = R.player_loader_sites(exe)
    assert sites == [{"function": 0x80010000, "lhu": 0x80010014, "call": 0x80010018,
                      "target": R.CD_LOAD_FILE_VA, "dest": 0x801BFA14}]


def test_file_table_synthetic_with_form2_record():
    entries = [{"name": "B.XAS", "lba": 20, "size": 4096},
               {"name": "A.BIN", "lba": 10, "size": 100},
               {"name": "A2.BIN", "lba": 11, "size": 5000}]
    table = struct.pack("<8I", 100, 10 | 0xA8 << 24, 5000, 11 | 0x8E << 24,
                        2 * R.RAW_FORM2_SECTOR, 20 | 0xFF << 24, 2, 0x40043)
    exe = R.Exe(_exe(b"\0" * 8 + table))
    tab = R.find_file_table(exe, entries)
    assert tab["base"] == 0x80010008 and tab["matched"] == 3
    assert tab["index"] == {"A.BIN": 0, "A2.BIN": 1, "B.XAS": 2}
    assert R.table_record(exe, tab["base"], 1) == {"index": 1, "size": 5000, "lba": 11, "tag": 0x8E}


def test_forward_copy_gap():
    assert R.PLD_RESIDENT_MAX == 0xDA00
    assert R.forward_copy_safe(0xDA00) and not R.forward_copy_safe(0xDA01)


@pytest.fixture(scope="module")
def owned():
    if not os.path.exists(BIN):
        pytest.skip("owned RE2 Claire disc image not extracted")
    from gbox.psxdisc import RawBin

    rb = RawBin(BIN, writable=False)
    entries = [{"name": k, "lba": v[0], "size": v[1]} for k, v in rb.files.items()]
    data = rb.read("SLUS_007.56")
    exe = R.Exe(data)
    return rb, entries, data, exe, R.find_file_table(exe, entries)


def test_owned_sector_table_and_pld_slots(owned):
    rb, entries, data, exe, tab = owned
    assert hashlib.sha256(data).hexdigest() == R.EXE_SHA256
    assert exe.hdr["pc0"] == 0x800783C0 and exe.hdr["t_size"] == 0xF0800
    assert tab["base"] == R.FILE_TABLE_VA
    assert len(entries) == 861 and tab["count"] == tab["matched"] == 858
    assert tab["unmatched"] == ["SYSTEM.CNF", "SLUS_007.56", "ZNULL.DAT"]
    slots = R.pld_slots(exe, tab)
    assert [s["file_no"] for s in slots] == [474, 495, 516, 517, 518, 519, 520, 521, 522,
                                            523, 524, 525, 547, 557, 561, 582]
    assert [s["name"] for s in slots] == ["PL1/PLD/PL%02X.PLD" % i for i in range(16)]
    for s in slots:
        lba, size = rb.files[s["name"]]
        assert (s["lba"], s["size"]) == (lba, size) and size <= s["capacity"]
    assert (slots[1]["size"], slots[1]["capacity"]) == (146852, 72 * 2048)


def test_owned_player_loader_sites(owned):
    _, _, _, exe, _ = owned
    sites = R.player_loader_sites(exe)
    assert {(s["function"], s["target"], s["dest"]) for s in sites} == {
        (R.PLAYER_LOADER_VA, R.CD_LOAD_FILE_VA, R.PLD_LOAD_BUF),
        (R.PLAYER_LOADER_ALT_VA, R.CD_LOAD_FILE_VA, 0x80198000)}
    # load_file reads the sector table (size word at $gp = 0x8009885c)
    refs = R.find_hilo_refs(exe, R.FILE_TABLE_VA, R.FILE_TABLE_VA + 8)
    assert any(R.function_start(exe, r["use"]) == R.CD_LOAD_FILE_VA for r in refs)
    # the room setup is the only caller of the player loader
    calls = R.find_jal_callers(exe, R.PLAYER_LOADER_VA)
    assert [R.function_start(exe, c) for c in calls] == [R.ROOM_PLAYER_SETUP_VA]


def test_owned_plds_fit_resident_gap(owned):
    rb, _, _, exe, tab = owned
    for s in R.pld_slots(exe, tab):
        d = rb.read(s["name"])
        dir_off, count = struct.unpack_from("<II", d, 0)
        offs = struct.unpack_from("<%dI" % count, d, dir_off)
        assert count == 4 and list(offs) == sorted(offs), s["name"]
        assert R.forward_copy_safe(offs[3]), (s["name"], hex(offs[3]))
