"""Paper Mario (USA) inventory (#1673): Yay0 codec unit tests + owned-ROM inventory pins (skip without the ROM)."""
import os
import struct
from pathlib import Path

import pytest

from gbox import pm_inventory as pm

ROM = Path(os.environ.get("GBOX_PM_US_ROM", Path.home() / "gBox_alt/gbox-cache/b74d223b195befba/rom.z64"))
SRC = Path(os.environ.get("GBOX_PM_US_SRC", Path.home() / "gBox_alt/gbox-cache/b74d223b195befba/source.zip"))


def _yay0(size, masks, links, chunk):
    link_off = 0x10 + 4 * len(masks)
    chunk_off = link_off + 2 * len(links)
    return (b"Yay0" + struct.pack(">III", size, link_off, chunk_off) + b"".join(struct.pack(">I", m) for m in masks)
            + b"".join(struct.pack(">H", v) for v in links) + bytes(chunk))


def test_yay0_short_backref():
    # literals A B C, copy dist 3 len 6, literal X
    blob = _yay0(10, [0b11101 << 27], [(4 << 12) | 2], b"ABCX")
    assert pm.yay0_decompress(blob) == b"ABCABCABCX"


def test_yay0_long_backref_and_offset():
    # literal A, then n==0 form: length = chunk byte + 0x12 (2 + 0x12 = 20), dist 1
    blob = _yay0(21, [0x80000000], [0x0000], b"A\x02")
    assert pm.yay0_decompress(b"pad!" + blob, 4) == b"A" * 21


def test_yay0_rejects_bad_magic_and_backref():
    with pytest.raises(ValueError):
        pm.yay0_decompress(b"Yaz0" + bytes(12))
    with pytest.raises(ValueError):
        pm.yay0_decompress(_yay0(4, [0], [0x2005], b""))


def test_offset_list_terminates():
    d = struct.pack(">IIII", 4, 8, 0xFFFFFFFF, 7)
    assert pm.offset_list(d, 0) == [4, 8]
    with pytest.raises(ValueError):
        pm.offset_list(struct.pack(">II", 1, 2), 0)


@pytest.fixture(scope="module")
def rom():
    if not ROM.exists():
        pytest.skip("owned Paper Mario (USA) ROM not cached (GBOX_PM_US_ROM)")
    return ROM.read_bytes()


def test_identify_us_build(rom):
    i = pm.identify(rom)
    assert i["sha1"] == "3837f44cda784b466c9a2d99df70d77c322b97a0"
    assert i["md5"] == "a722f8161ff489943191330bf8416496"
    assert (i["code"], i["version"], i["entry"], i["title"]) == ("NMQE", 0, "0x80125c00", "PAPER MARIO")
    assert i["known"]["decomp"] == "us"


def test_sprite_bank(rom):
    s = pm.sprites(rom)
    h = s["header"]
    assert h["build_date"] == "00/07/03 15:47"
    assert (h["player_rasters"], h["player_yay0"], h["npc_yay0"], h["end"]) == (0x1943020, 0x19E0970, 0x19E67B8, 0x1B82208)  # end = splat pad_1B82208
    assert len(s["player"]) == 13 and len(s["npc"]) == 233
    m1 = s["player"][0]
    assert (m1["name"], m1["rasters"], m1["palettes"], m1["animations"], m1["variations"]) == ("Mario1", 87, 26, 51, 6)
    g = s["npc"][0]
    assert (g["name"], g["sprite_id"], g["rasters"], g["palettes"], g["animations"]) == ("WorldGoombario", 1, 15, 5, 11)
    pr = s["player_rasters"]
    assert pr["raster_sets"] == 13 and pr["load_descriptors"] == 718 and pr["descriptors_out_of_range"] == []
    assert sum(p["rasters"] for p in s["npc"]) == 5615


def test_mapfs(rom):
    fs = pm.mapfs(rom)
    assert len(fs) == 1033 and sum(f["yay0"] for f in fs) == 1005
    party = [f for f in fs if f["name"].startswith("party_")]
    assert len(party) == 8
    kooper = next(f for f in fs if f["name"] == "party_kameki")
    assert len(pm.yay0_decompress(rom, kooper["rom"])) == kooper["size"]


def test_inventory_from_owned_zip(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOX_N64_ROM_CACHE", str(tmp_path))
    if not SRC.exists():
        pytest.skip("owned Paper Mario (USA) zip not cached (GBOX_PM_US_SRC)")
    m = pm.inventory(SRC)
    assert m["source"]["member"] == "Paper Mario (USA).n64" and m["source"]["member_byte_order"] == "v64"
    assert m["characters"]["player_sprites"] == 13 and m["characters"]["npc_sprites"] == 233
