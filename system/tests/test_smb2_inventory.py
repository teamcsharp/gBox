"""Focused tests for gbox.smb2_inventory (Super Mario Bros. 2 USA, NES MMC3).

The synthetic ROM mirrors the PRG0 code/table shapes so the locators are
tested without the owned cartridge; the owned-ROM test runs when the cached
HyperSpin zip (or GBOX_SMB2_SRC) is present.
"""
import io
import os
import struct
import zipfile
from pathlib import Path

import pytest

from gbox import smb2_inventory as inv

BANK = 0x2000
TILES = [0x00, 0x02, 0x04, 0x06, 0x0C, 0x0E, 0x10, 0x12, 0x00, 0x02, 0x08, 0x0A,
         0x0C, 0x0E, 0x14, 0x16, 0xFB, 0xFB, 0x2C, 0x2C, 0xFB, 0xFB, 0x2E, 0x2E,
         0x0C, 0x0E, 0x10, 0x12, 0x30, 0x30, 0x32, 0x32, 0x20, 0x22, 0x24, 0x26,
         0x00, 0x02, 0x28, 0x2A, 0x18, 0x1A, 0x1C, 0x1E, 0xB4, 0xB6]
PALETTES = [0x0F, 0x01, 0x16, 0x27, 0x0F, 0x06, 0x25, 0x36,
            0x0F, 0x01, 0x30, 0x27, 0x0F, 0x01, 0x2A, 0x36]
LOAD_CHR = [0xA5, 0x8F, 0x0A, 0x0D, 0x12, 0x06, 0xA8, 0xB9, 0x00, 0xF8, 0x8D, 0x2B, 0x06, 0x60]
CHR_LOOP = [0xA0, 0x05, 0x98, 0x09, 0x80, 0x8D, 0x00, 0x80, 0xB9, 0x29, 0x06,
            0x8D, 0x01, 0x80, 0x88, 0x10, 0xF3, 0x60]


def _rom(table=(0, 4, 2, 6, 3, 7, 1, 5), stat_n=24, extra_load=False) -> bytes:
    prg = bytearray(16 * BANK)
    chr_ = bytearray(128 * 0x400)
    f0 = 14 * BANK                                    # CPU $C000
    prg[f0 + 0x3800:f0 + 0x3808] = bytes(table)       # CHRBank_CharacterSize at $F800
    prg[f0 + 0x3810:f0 + 0x3810 + len(LOAD_CHR)] = bytes(LOAD_CHR)
    if extra_load:
        prg[f0 + 0x3A00:f0 + 0x3A00 + len(LOAD_CHR)] = bytes(LOAD_CHR)
    prg[f0 + 0x3900:f0 + 0x3900 + len(CHR_LOOP)] = bytes(CHR_LOOP)
    blob = inv.EYE_SIG + bytes(TILES)
    prg[f0 + 0x1000:f0 + 0x1000 + len(blob)] = blob
    prg[f0 + 0x1100:f0 + 0x1103] = bytes((0xBD, 0x0F, 0xD0))   # LDA CharacterTiles,X
    so = 10 * BANK + 0x200
    prg[so:so + 4] = bytes((0, 3 * stat_n, stat_n, 2 * stat_n))
    pal = so + 4 + 4 * stat_n
    prg[pal:pal + 16] = bytes(PALETTES)
    for page in range(8):
        for t in list(range(0x34)) + [0x3A]:          # $3A is drawn by no frame
            chr_[page * 0x400 + t * 16] = 0x80 | page
    return b"NES\x1a" + bytes((8, 16, 0x40, 0)) + bytes(8) + bytes(prg) + bytes(chr_)


def _zip(tmp_path: Path, rom: bytes) -> Path:
    p = tmp_path / "source.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Super Mario Bros. 2 (USA).nes", rom)
    p.write_bytes(buf.getvalue())
    return p


def test_synthetic_tables_and_roster(tmp_path):
    m = inv.inventory(_zip(tmp_path, _rom()))
    assert m["identity"]["match"] is False
    assert m["ines"]["mapper"] == 4 and m["chr_page_count"] == 128
    load = m["chr_banking"]["load_character_chr_banks"]
    assert load["table"]["cpu"] == 0xF800 and load["routine"]["cpu"] == 0xF810
    assert (load["current_character_ram"], load["player_size_ram"], load["sprite_chr1_ram"]) == (0x8F, 0x612, 0x62B)
    assert m["chr_banking"]["sprite_page"] == {
        "register": "R2", "ppu": 0x0000, "chr_a12_inversion": True,
        "note": "1 KB character page at the sprite pattern table"}
    assert {r["character"]: r["pages"] for r in m["roster"]} == {
        "Mario": {"big": 0, "small": 4}, "Princess": {"big": 2, "small": 6},
        "Toad": {"big": 3, "small": 7}, "Luigi": {"big": 1, "small": 5}}
    assert m["frames"]["walk1"] == [0, 2, 4, 6] and m["frames"]["duck"] == [0xFB, 0xFB, 0x2C, 0x2C]
    assert m["tables"]["princess_float_body"] == [0xB4, 0xB6]
    assert m["tables"]["character_tiles"]["cpu"] == 0xD00F
    assert {"cpu": 0xD100, "op": "LDA,X", "operand": 0xD00F} in m["tables"]["xrefs"]
    assert m["palette_tables"]["stats_block_size"] == 24
    assert m["player"]["Luigi"]["palette"] == [0x0F, 0x01, 0x2A, 0x36]
    assert m["player"]["Toad"]["eye_tile"] == 0xFB
    big = m["player"]["Mario"]["sizes"]["big"]
    assert big["rom_offset"] == 16 + 0x20000 and big["unreferenced_nonblank_tiles"] == [0x3A]
    assert len(big["frames"]) == 11


def test_png_sheet_and_cli(tmp_path):
    src = _zip(tmp_path, _rom())
    out, png = tmp_path / "m.json", tmp_path / "sheet.png"
    assert inv.main([str(src), "--out", str(out), "--png", str(png)]) == 0
    data = png.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", data[16:24])
    assert (w, h) == (11 * 18, 8 * 34)
    assert '"game_id": "768145c187bf6dd0"' in out.read_text()


def test_ambiguous_or_invalid_tables_raise(tmp_path):
    with pytest.raises(ValueError, match="2 candidates"):
        inv.inventory(_zip(tmp_path, _rom(extra_load=True)))
    with pytest.raises(ValueError, match="0 candidates"):
        inv.inventory(_zip(tmp_path, _rom(table=(0, 0, 2, 6, 3, 7, 1, 5))))


OWNED = Path(os.environ.get("GBOX_SMB2_SRC", str(Path.home() / "gBox_alt/gbox-cache/768145c187bf6dd0/source.zip")))


@pytest.mark.skipif(not OWNED.exists(), reason="owned SMB2 source not cached")
def test_owned_rom_inventory():
    m = inv.inventory(OWNED)
    if OWNED.name == "source.zip":
        assert m["source"]["sha256"] == inv.OWNED_SOURCE_SHA256
    assert m["identity"]["match"] and m["identity"]["revision"] == "Rev 0 (PRG0)"
    assert m["identity"]["sha1"] == "43ac7c7aaf1846ead7b544302bb9131e4964fd32"
    assert {r["character"]: r["pages"] for r in m["roster"]} == {
        "Mario": {"big": 0, "small": 4}, "Princess": {"big": 2, "small": 6},
        "Toad": {"big": 3, "small": 7}, "Luigi": {"big": 1, "small": 5}}
    assert m["chr_banking"]["sprite_page"]["ppu"] == 0x0000
    assert m["player"]["Mario"]["palette"] == [0x0F, 0x01, 0x16, 0x27]
    assert m["frames"]["climb"] == [0x18, 0x1A, 0x1C, 0x1E]


def test_short_prg_or_chr_raise_valueerror():
    for n in (0, BANK, 2 * BANK + 1):
        with pytest.raises(ValueError):
            inv.locate_chr_bank_select(bytes(n))
    rom = _rom()
    prg, chr_ = rom[16:16 + 16 * BANK], rom[16 + 16 * BANK:]
    banks = inv.locate_chr_bank_select(prg)
    tiles = inv.locate_character_tiles(prg)
    pal = inv.locate_character_palette(prg)
    with pytest.raises(ValueError):
        inv.player_inventory(chr_[:7 * 0x400], banks, tiles, pal)
