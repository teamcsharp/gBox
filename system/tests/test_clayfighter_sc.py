"""Focused tests for gbox/clayfighter_sc.py (request #487)."""

import hashlib
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gbox import clayfighter_sc as cf  # noqa: E402

ROM = os.path.expanduser(
    "~/gBox_alt/gbox-cache/f87ec3e2f6b266a1/unpacked/Clay Fighter - Sculptor's Cut (USA).n64"
)


@pytest.fixture(scope="module")
def rom():
    if not os.path.exists(ROM):
        pytest.skip("owned ROM not present in cache")
    return cf.load_rom(ROM)


def test_load_and_identity(rom):
    assert len(rom) == cf.ROM_SIZE
    assert hashlib.sha256(rom).hexdigest() == cf.ROM_SHA256
    assert hashlib.md5(rom).hexdigest() == cf.ROM_MD5
    assert rom[0x8:0xC] == b"\x80\x00\x04\x00"  # entry 0x80000400


def test_ram_delta_mapping(rom):
    # code at ROM 0x1000 executes at RDRAM 0x80000400
    assert 0x1000 + cf.ROM_TO_RAM_DELTA == 0x80000400
    # the name table pointer entries must point into the string region
    for e in cf.roster(rom):
        assert 0x800C5000 <= e["name_ptr"] <= 0x800C6000


def test_roster_table(rom):
    ro = cf.roster(rom)
    assert len(ro) == cf.CHARACTER_COUNT
    assert [e["code"] for e in ro] == [c for c, _ in cf.ROSTER]
    assert ro[0]["code"] == "CHAR_BMF"  # default player-1 actor


def test_display_names_descending(rom):
    dn = cf.display_names(rom)
    assert dn == [d for _, d in cf.ROSTER][::-1]


def test_char_hooks_in_code(rom):
    hooks = cf.char_hooks(rom)
    assert len(hooks) == cf.CHARACTER_COUNT
    for h in hooks:
        assert 0x80004000 <= h["fn2"] <= 0x800A0000, h


def test_bmf_bio_record(rom):
    bio = cf.parse_bmf_bio(rom)
    assert bio["name"] == "Bad Mr. Frosty"
    assert bio["code"] == "BMF"
    assert len(bio["stats"]) == 10
    assert len(bio["frame_offsets"]) >= 16
    # frame offsets must be ascending within each run (sprite frame bank)
    runs, run = [], []
    for v in bio["frame_offsets"]:
        if run and v < run[-1]:
            runs.append(run)
            run = []
        run.append(v)
    runs.append(run)
    assert any(len(r) >= 16 for r in runs)


def test_validate(rom):
    res = cf.validate(rom)
    assert res["ok"], res["problems"]
