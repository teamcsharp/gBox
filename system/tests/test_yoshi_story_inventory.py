import hashlib
import struct
import zipfile
from pathlib import Path

import pytest

from gbox import yoshi_story_inventory as ys

OWNED = Path("/mnt/gbox/hyperspin/Arcade/collections/Nintendo 64/roms/USA/Yoshi's Story (USA) (En,Ja).zip")


def _cmd(w0, w1):
    return struct.pack(">II", w0, w1)


def _frame(tile_offsets=(0x6C00, 0x9E00), tlut=True):
    dl = b""
    if tlut:
        dl += _cmd(0xFD100000, 0x03000400) + _cmd(0xE8000000, 0) + _cmd(0xF0000000, 0x073FC000)
    for off in tile_offsets:
        dl += _cmd(0xFD500000, 0x03000000 | off)          # SETTIMG CI 16b (loadblock trick)
        dl += _cmd(0xF5500000, 0x07080200)                # SETTILE load tile 7
        dl += _cmd(0xF3000000, 0x0772ABE7)                # LOADBLOCK lrs=0x72A -> 0x72B texels
        dl += _cmd(0xF5480600, 0x00080200)                # SETTILE render tile 0: CI 8b
        dl += _cmd(0xB1000204, 0x00000406)                # TRI2
    dl += _cmd(0xB8000000, 0)
    return dl.ljust(ys.FRAME_ALIGN, b"\0")


def _rom(frames_at, code=b"NYSE"):
    rom = bytearray(0x200000)
    rom[:4] = b"\x80\x37\x12\x40"
    rom[8:12] = bytes.fromhex("80200400")
    rom[0x20:0x34] = b"YOSHI STORY".ljust(20)
    rom[0x3B:0x3F] = code
    for off, data in frames_at:
        rom[off:off + len(data)] = data
    return bytes(rom)


def test_header_reads_game_code_and_entry():
    h = ys.header(_rom([]))
    assert h["game_code"] == "NYSE" and h["title"] == "YOSHI STORY" and h["entry"] == "80200400"


def test_parse_frame_decodes_tlut_tiles_and_render_format():
    rom = _rom([(0x100000, _frame())])
    f = ys.parse_frame(rom, 0x100000)
    assert f["tlut"] == {"seg3": 0x400, "colors": 256}
    assert [t["seg3"] for t in f["tiles"]] == [0x6C00, 0x9E00]
    assert all(t["render"] == "CI8" for t in f["tiles"])
    assert f["tiles"][0]["texels"] == 0x72B and f["tris"] == 4
    assert f["seg3_end"] == 0x9E00 + 0x72B * 2


def test_records_without_tlut_or_outside_seg3_buffer_are_rejected():
    rom = _rom([(0x100000, _frame(tlut=False)), (0x100400, _frame((0x12000,)))])
    assert ys.parse_frame(rom, 0x100000) is None
    assert ys.parse_frame(rom, 0x100400) is None


def test_frames_group_into_contiguous_banks():
    rom = _rom([(0x100000, _frame()), (0x100400, _frame()), (0x100800, _frame()), (0x180000, _frame())])
    frames = ys.sprite_frames(rom, start=0x1000)
    banks = ys.frame_banks(frames)
    assert [(b["rom"], b["frames"]) for b in banks] == [(0x100000, 3), (0x180000, 1)]
    assert banks[0]["tiles"] == 6


def test_callers_finds_jal_sites_in_main(tmp_path):
    rom = bytearray(_rom([]))
    rom[0x2000:0x2004] = struct.pack(">I", ys._jal(0x8007DF0C))
    assert ys.callers(bytes(rom), 0x8007DF0C, end=0x3000) == [0x2000 + ys.MAIN_ROM_TO_VRAM]


def test_inventory_reads_word_swapped_zip_and_rejects_other_games(tmp_path):
    rom = _rom([(0x100000, _frame())])
    n64 = bytearray(len(rom))
    n64[0::4], n64[1::4], n64[2::4], n64[3::4] = rom[3::4], rom[2::4], rom[1::4], rom[0::4]
    z = tmp_path / "y.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("Yoshi's Story (USA) (En,Ja).n64", bytes(n64))
    inv = ys.inventory(z)
    assert inv["rom"]["sha256"] == hashlib.sha256(rom).hexdigest()
    assert inv["source"]["sha256"] == hashlib.sha256(z.read_bytes()).hexdigest()
    assert inv["sprites"]["frames"] == 1 and inv["rom"]["decomp_us_build"] is False
    other = tmp_path / "o.z64"
    other.write_bytes(_rom([], code=b"NSME"))
    with pytest.raises(ValueError):
        ys.inventory(other)


@pytest.mark.skipif(not OWNED.exists(), reason="owned ROM not mounted")
def test_owned_rom_matches_decomp_build_and_sprite_bank():
    inv = ys.inventory(OWNED)
    assert inv["source"]["sha256"] == "17d79406ae10c2a1311c78db68cf35bdcdf24e0e07427b698839005ec15d41e0"
    assert inv["rom"]["md5"] == ys.DECOMP_US_MD5 and inv["rom"]["byte_order"] == "container"
    s = inv["sprites"]
    assert (s["frames"], s["tiles"], s["formats"]) == (1187, 7092, {"CI8": 7092})
    assert [(b["rom"], b["end"]) for b in s["banks"]] == [(0x9E6C00, 0xB0F800)]
    assert inv["loader_evidence"]["DmaMgr_RequestSync"]["callers"] == ["0x800675b8", "0x800816c4"]
