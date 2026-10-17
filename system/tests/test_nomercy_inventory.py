"""gbox.nomercy_inventory (#1329): owned-build identity, boot-code profile checks and the asset inventory."""
import hashlib
import struct
import zipfile
from pathlib import Path

import pytest

from gbox import nomercy_inventory as I

SRC = Path.home() / "gbox-cache/23a346e48b6368a6/source.zip"     # owned WWF No Mercy (USA) (Rev A) zip copy


def _put(buf: bytearray, ram: int, w: int) -> None:
    struct.pack_into(">I", buf, I.ram2rom(ram), w)


def test_container_flags_v64_data_in_an_n64_named_member(tmp_path):
    z = tmp_path / "g.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("Game (USA).n64", b"\x37\x80\x40\x12" + bytes(60))
    c = I.container(z)
    assert c["sha256"] == hashlib.sha256(z.read_bytes()).hexdigest()
    (m,) = c["members"]
    assert m["byte_order"].startswith("v64") and m["extension_matches"] is False
    raw = tmp_path / "g.z64"
    raw.write_bytes(b"\x80\x37\x12\x40" + bytes(60))
    assert I.container(raw)["byte_order"].startswith("z64")


def test_code_refs_reads_the_writer_patch_sites():
    rom = bytearray(I.ram2rom(I.SITES["bound"]) + 4)
    _put(rom, I.SITES["ft_hi"], 0x3C04016C)               # lui   a0, 0x016c
    _put(rom, I.SITES["ft_lo"], 0x248431D8)               # addiu a0, a0, 0x31d8
    _put(rom, I.SITES["bound"], 0x2C424C03)               # sltiu v0, v0, 0x4c03
    r = I.code_refs(bytes(rom))
    assert r["ok"] and r["ft_rom"] == 0x16C31D8 and r["entries"] == 0x4C03
    assert not I.code_refs(bytes(len(rom)))["ok"]         # another build: no lui/addiu/sltiu at the sites
    assert I._pair(0x3C04001C, 0x2484D150) == 0x1BD150    # addiu sign-extends: 0x1c0000 - 0x2eb0
    assert I._pair(0x3C04001B, 0x3484D150) == 0x1BD150    # ori does not


def test_imm_pairs_and_region_refs_find_code_dma_sources():
    rom = bytearray(0x1200)
    struct.pack_into(">III", rom, 0x1000, 0x3C05001C, 0, 0x24A5D150)   # lui a1,0x1c; nop; addiu a1,a1,-0x2eb0
    struct.pack_into(">II", rom, 0x1010, 0x3C060000, 0x34C61100)       # lui a2,0; ori a2,a2,0x1100
    rom[0x1100:0x1100 + 14] = b"N64 WaveTables"
    pairs = I.imm_pairs(bytes(rom), 0x1000, 0x1020)
    assert I.lui_pairs(bytes(rom), 0x1BD150, 0x1000, 0x1020) == [0x80000400]
    (ref,) = I.region_refs(bytes(rom), pairs, 0x1080, 0x1200)
    assert ref["rom"] == "0x1100" and ref["kind"].startswith("sound bank .tbl") and ref["refs"] == ["0x80000410"]


def test_tex_format_decides_by_size_like_the_revenge_reader():
    assert I.tex_format(bytes([7, 7, 1, 0, 0, 0, 3, 3]) + bytes(64))["fmt"] == "ci8"
    ci4 = bytes([7, 7, 0, 32, 0, 0, 3, 3]) + bytes(32)    # the shared neck texture 0x1F6A: 2 x 16 colours, 40 bytes
    f = I.tex_format(ci4)
    assert f["fmt"] == "ci4" and f["colours"] == 32 and f["size_ok"]
    assert I.tex_format(ci4[:20])["fmt"] == "truncated"
    assert I.tex_format(b"\0\0")["size_ok"] is False


def test_tail_free_counts_the_fill_run():
    assert I.tail_free(b"abc" + b"\xff" * 5, 1) == {"from": 1, "fill": 255, "free": 5, "all_fill": False}
    assert I.tail_free(b"\xff" * 4, 0)["all_fill"]


def test_inventory_refuses_other_games_and_gbox_mods(monkeypatch):
    monkeypatch.setattr(I.A, "profile", lambda rom: {"game": "revenge"})
    with pytest.raises(ValueError, match="not a No Mercy build"):
        I.inventory(bytes(0x100))
    monkeypatch.setattr(I.A, "profile", lambda rom: {"game": "nomercy"})
    monkeypatch.setattr(I.A, "modded", lambda rom: {"ft": 1})
    with pytest.raises(ValueError, match="gBox-written mod"):
        I.inventory(bytes(0x100))


@pytest.mark.skipif(not SRC.exists(), reason="owned No Mercy ROM is not on this machine")
def test_owned_rom_inventory_matches_the_writer_profile():
    from gbox import n64_rom
    m = I.inventory(n64_rom.read(SRC), SRC)
    b = m["build"]
    assert (b["code"], b["rev"], b["region"]) == ("NW4E", 1, "USA") and b["cic"].startswith("6102")
    assert m["source"]["members"][0]["byte_order"].startswith("v64")
    assert m["code_refs"]["ok"] and m["code_refs"]["first_file_refs"]
    ft = m["file_table"]
    assert ft["entries"] == 0x4C03 and ft["monotonic"] and ft["assets_end_at_table"]
    r = m["roster"]
    assert r["blocks"] == 65 and r["registered"] == 64 and r["unregistered"] == ["Original A"] and r["costume_file_ok"]
    a = m["assets"]
    assert not a["models"]["unparsable"] and a["models"]["max_vertices"] <= a["models"]["writer_limits"][0]
    assert [t["id"] for t in a["textures"]["not_ci8"]] == [0x1F6A]
    assert any(x["kind"].startswith("sound bank") for x in m["layout"]["after_table"]["code_refs"])
    assert m["wrestlers"][1]["ring_names"][2] == "STONE COLD"
