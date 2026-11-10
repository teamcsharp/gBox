"""gbox.pso_dol: the flat address map for `PsoV3.dol`, checked against the real executable."""
from pathlib import Path

import pytest

from gbox import pso_dol as D

DISC = Path(r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz")


def make_dol(payload, code_start=0x100, image_base=0x8000C000):
    head = bytearray(code_start)
    head[0:4] = code_start.to_bytes(4, "big")
    head[0x48:0x4C] = image_base.to_bytes(4, "big")
    head[0x4C:0x50] = (image_base + 0x3000).to_bytes(4, "big")
    return bytes(head) + payload


def test_the_head_yields_the_code_start_and_base():
    h = D.header(make_dol(b"\x00" * 64))
    assert h["code_start"] == 0x100 and h["image_base"] == 0x8000C000 and h["flat"] is True
    assert D.is_flat() is True


def test_offsets_and_addresses_map_both_ways():
    dol = make_dol(b"ABCD" * 16)
    assert D.address_of(dol, 0x100) == 0x8000C000
    assert D.address_of(dol, 0x104) == 0x8000C004
    assert D.offset_of(dol, 0x8000C004) == 0x104
    assert D.offset_of(dol, 0x90000000) is None


def test_an_offset_outside_the_file_is_refused():
    dol = make_dol(b"\x00" * 16)
    with pytest.raises(D.DolError, match="outside the file"):
        D.address_of(dol, len(dol) + 8)


def test_a_string_is_found_with_its_address():
    dol = make_dol(b"xxmap_forest01_00o.dat\x00")
    got = D.find_string(dol, "map_forest01_00o.dat")
    assert got["offset"] == 0x102 and got["address"] == 0x8000C002
    assert D.find_string(dol, "not here") is None


def test_pointers_to_an_address_are_found():
    target = 0x8000C010
    dol = make_dol(target.to_bytes(4, "big") + b"\x00" * 8)
    hits = D.find_pointers(dol, target)
    assert len(hits) == 1 and hits[0]["offset"] == 0x100
    assert D.find_pointers(dol, 0x8000FFFF) == []


def test_a_file_too_small_for_the_head_is_refused():
    with pytest.raises(D.DolError, match="smaller than"):
        D.header(b"\x00" * 8)


@pytest.mark.skipif(not DISC.is_file(), reason="the disc is not on this machine")
def test_the_real_executable_agrees_with_the_ghidra_image_base():
    """The claim that matters: this file's base is 0x8000c000, which is the image_base the Ghidra export uses."""
    from gbox import gcdisc

    d = gcdisc.GCDisc(str(DISC))
    dol = d.read("PsoV3.dol")
    h = D.header(dol)
    assert h["image_base"] == 0x8000C000
    assert h["code_start"] == 0x100
    assert len(dol) == 5233088
    assert D.address_of(dol, 0x100) == 0x8000C000
    # the class names and map fragments the game assembles its file names from are in the image, at addresses
    door = D.find_string(dol, "TObjCityDoor")
    assert door is not None and door["address"] == 0x8000C000 + (0x438140 - 0x100)
    assert D.find_string(dol, "map_forest01")["offset"] == 0x43EB04
    assert D.find_string(dol, "map_") is not None
    # full file names are assembled, not stored: the literal does not occur
    assert D.find_string(dol, "map_forest01_00o.dat") is None
