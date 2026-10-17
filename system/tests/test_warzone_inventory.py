"""Focused tests for gbox.warzone_inventory (WWF War Zone USA N64).

Parser-level tests run on synthetic bytes; the integration test runs against
the owned build when a local copy exists (skipped otherwise).
"""
from __future__ import annotations

import zlib
from pathlib import Path

import pytest

from gbox import warzone_inventory as wz

EXPECTED = wz.EXPECTED


def make_rom(**kw) -> bytes:
    rom = bytearray(EXPECTED["size"])
    rom[:4] = b"\x80\x37\x12\x40"
    rom[8:12] = (0x80000400).to_bytes(4, "big")
    rom[0x20:0x34] = b"WWF War Zone" + b" " * 8
    rom[0x3B:0x3F] = b"NWWE"
    for k, v in kw.items():
        if k == "code":
            rom[0x3B:0x3F] = v.encode()
        elif k == "name":
            rom[0x20:0x34] = v.encode().ljust(20, b" ")
    return bytes(rom)


def test_identify_rejects_wrong_size():
    rom = bytearray(EXPECTED["size"] - 4)
    with pytest.raises(ValueError, match="byte ROM"):
        wz.identify(rom)


def test_identify_rejects_other_builds():
    # Right shape and code, but synthetic content cannot carry this title's
    # hashes; the guard must refuse it.
    with pytest.raises(ValueError, match="not the WWF War Zone"):
        wz.identify(make_rom())
    with pytest.raises(ValueError, match="not the WWF War Zone"):
        wz.identify(make_rom(code="XXWE"))


def test_identify_reports_header_fields():
    # The fields the manifest relies on parse from a synthetic header.
    info = wz.header_fields(make_rom())
    assert info["internal_name"] == "WWF War Zone"
    assert info["game_code"] == "NWWE"
    assert info["entry"] == "0x80000400"


def test_scan_ascii_runs():
    rom = bytearray(4096)
    rom[0x100:0x109] = b"GOLDUST"
    rom[0x109:0x10C] = b"\x00\x01\x02"
    rom[0x10C:0x110] = b"KANE"
    runs = wz.scan_ascii(bytes(rom), 0x100, 0x110)
    assert runs == [{"offset": 0x100, "text": "GOLDUST"}, {"offset": 0x10C, "text": "KANE"}]


def _put_move(rom: bytearray, base: int, name: str) -> None:
    rec = name.encode("latin1").ljust(wz.MOVE_STRIDE - 1, b" ") + b"\0"
    assert len(rec) == wz.MOVE_STRIDE
    rom[base:base + wz.MOVE_STRIDE] = rec


def test_move_table_records():
    rom = bytearray(EXPECTED["size"])
    base = wz.MOVE_TABLE
    _put_move(rom, base, "STANDING MOONSAULT")
    _put_move(rom, base + 0x20, "LEG DROP")
    _put_move(rom, base + 0x40, "TOMBSTONE PILEDRIVER")
    # Walk-back must stop: the preceding record ends without a NUL.
    rom[base - 1] = 0x41
    table = wz.move_table(bytes(rom))
    assert table["base"] == base
    assert [r["name"] for r in table["records"]] == [
        "STANDING MOONSAULT", "LEG DROP", "TOMBSTONE PILEDRIVER",
    ]
    assert table["count"] == 3


def test_move_table_walkback_skips_zeros_and_terminator_ends_parse():
    rom = bytearray(EXPECTED["size"])
    base = wz.MOVE_TABLE
    _put_move(rom, base, "CHOKE SLAM")
    rom[base + 0x20:base + 0x40] = b"\x06" + b" " * 30 + b"\0"
    table = wz.move_table(bytes(rom))
    # The all-zero region before the table must not be swallowed by walk-back.
    assert table["base"] == base
    assert [r["name"] for r in table["records"]] == ["CHOKE SLAM"]
    assert table["count"] == 1


def test_venue_pointer_check():
    rom = bytearray(EXPECTED["size"])
    rom[wz.VENUE_REF:wz.VENUE_REF + 4] = (0x80BF2E00).to_bytes(4, "big")
    assert wz.venue_bank(bytes(rom))["matches_pointer"] is True
    rom[wz.VENUE_REF:wz.VENUE_REF + 4] = (0x80BF0000).to_bytes(4, "big")
    assert wz.venue_bank(bytes(rom))["matches_pointer"] is False


def test_crc32_helper():
    assert wz._crc32(b"") == "00000000"
    assert wz._crc32(b"WWF War Zone") == format(zlib.crc32(b"WWF War Zone") & 0xFFFFFFFF, "08X")


@pytest.mark.skipif(
    not Path("/home/ehm_eckx/gbox-cache/warzone/source.zip").exists(),
    reason="owned WWF War Zone (USA) zip not staged locally",
)
def test_inventory_owned_build():
    man = wz.inventory("/home/ehm_eckx/gbox-cache/warzone/source.zip")
    assert man["source"]["zip_sha256"] == wz.ZIP_SHA256
    assert man["source"]["normalized_z64"]["crc32"] == "2FBB5507"
    assert man["source"]["normalized_z64"]["game_code"] == "NWWE"
    moves = man["move_table"]
    assert moves["base"] == 0xB80BF4
    assert moves["count"] == 250
    assert moves["end"] == 0xB82B34
    names = [r["name"] for r in moves["records"]]
    assert names[0] == "PICK UP WEAPON" and names[-1] == "THE MOSH PIT"
    assert "TOMBSTONE PILEDRIVER" in names and "STONE COLD STUNNER" in names
    frags = man["name_bank"]["fragments"]
    texts = [f["text"] for f in frags]
    # Fragments absorb adjacent printable bytes, so match by substring.
    assert any("FAAROOQ" in t for t in texts)
    assert any("KANE" in t for t in texts)
    assert any("JOHNSON" in t for t in texts)
    assert any("HELMSLE" in t for t in texts)  # 'Y'→'v' substitution in-bank
    assert man["venue_bank"]["matches_pointer"] is True
    assert man["layout"]["tail_all_zero"] is True
