"""Analysis-stage probes for Yoshi's Story (USA) loaders (#1323)."""
import os
import struct
from pathlib import Path

import pytest

from gbox import yoshi_story_analysis as ya

ROM = Path(os.environ.get("GBOX_YS_ROM", Path.home() / "gBox_alt/gbox-cache/14da9d54679e0100/rom.z64"))


def test_gbi1_vtx_decodes_frame_prologue_load():
    v = ya.gbi1_vtx(0x0400617F, 0x03000200)
    assert v == {"v0": 0, "n": 24, "length": 0x180, "segment": 3, "offset": 0x200}
    with pytest.raises(ValueError):
        ya.gbi1_vtx(0xFD100000, 0x03000400)


def test_file_table_relocates_kind2_entries_only():
    vram = 0x800B4360
    rom = bytearray(0x100000)
    o = ya._ram(vram)
    struct.pack_into(">h", rom, o, 2)
    struct.pack_into(">IIBB", rom, o + 0x10, 0x10, 0x20, 2, 0)
    struct.pack_into(">IIBB", rom, o + 0x20, 0x30, 0x40, 1, 0)
    e = ya.file_table(bytes(rom), vram, 0xB58B0)
    assert [x["rom"] for x in e] == [0xB58C0, 0x30]
    struct.pack_into(">h", rom, o, 0)
    with pytest.raises(ValueError):
        ya.file_table(bytes(rom), vram, 0)


@pytest.fixture(scope="module")
def rom():
    if not ROM.exists():
        pytest.skip("owned Yoshi's Story ROM cache not present")
    data = ROM.read_bytes()
    if data[0x3B:0x3F] != b"NYSE":
        pytest.skip("cached ROM is not NYSE")
    return data


def test_owned_rom_boot_tables_are_the_audio_bank(rom):
    t = {x["role"]: x for x in ya.boot_file_tables(rom)}
    ib, st, sq = t["instrument_banks"], t["sample_tables"], t["sequences"]
    assert (ib["rom_base"], len(ib["entries"])) == (0xB58B0, 62)
    assert (st["rom_base"], len(st["entries"])) == (0xE1AD0, 2)
    assert (sq["rom_base"], len(sq["entries"])) == (0x4F3930, 65)
    # contiguous: banks end where samples start, samples end where sequences start
    end = lambda e: e[-1]["rom"] + e[-1]["size"]
    assert end(ib["entries"]) == 0xE1AD0
    assert end(st["entries"]) == 0x4F3930
    assert end(sq["entries"]) == 0x526EC0
    # every instrument bank but the first four (tables of contents) carries ADPCM books
    assert all(ya.audio_kind(rom, e) == "ctl" for e in ib["entries"][4:])


def test_owned_rom_loader_and_segment_facts(rom):
    a = ya.analysis(rom)
    assert a["decompress_stub_empty"] is True
    assert a["rom_copy"]["chunk"] == 0x400
    for s in a["slot_loaders"]:
        assert s["mode_bits_26_27"]
        kinds = [k for _, k in s["calls"]]
        assert kinds == ["decompress_stub", "rom_copy"]
    assert a["segment_setter"]["moveword"] == 0xBC
    words = struct.unpack(">%dI" % (len(rom) // 4), rom)
    assert not any((w >> 8) == 0xDB0600 for w in words)  # no GBI2 gSPSegment anywhere
