import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from gbox import smb3_inventory as si

REAL = Path.home() / "gBox_alt/gbox-cache/213e4208929ec3e9/source.zip"


def synth_rom(table_at=29 * 0x2000 + 0x0C00):
    prg = bytearray(16 * si.PRG_UNIT)
    chr_ = bytearray(16 * si.CHR_UNIT)
    offsets = table_at
    table = offsets + si.FRAMES
    page_off = table + si.FRAMES * 6
    root = page_off + si.FRAMES + si.DRAW_OFFSETS
    for i in range(si.FRAMES):
        prg[offsets + i] = 3 * i + 2
        prg[table + 6 * i: table + 6 * i + 6] = bytes((0x01, 0x03, si.HIDDEN, 0x05, 0x07, 0xA9))
        prg[page_off + i] = min(3, i // 21)
    prg[root:root + 7] = si.ROOT_SIG
    bank = 29 * 0x2000

    def cpu(o):
        return 0xC000 + o - bank

    code = bank + 0x1000
    t4 = cpu(table) - 4
    prg[code:code + 6] = bytes((0xA9, t4 & 0xFF, 0x85, 0x10, 0xA9, t4 >> 8))
    prg[code + 6:code + 9] = bytes((0xBD, cpu(offsets) & 0xFF, cpu(offsets) >> 8))
    prg[code + 9:code + 12] = bytes((0xBD, cpu(page_off) & 0xFF, cpu(page_off) >> 8))
    prg[code + 12:code + 15] = bytes((0xB9, cpu(root) & 0xFF, cpu(root) >> 8))
    # Page 0x50, tile 0: solid colour 3 on the top row.
    chr_[0x50 * si.CHR_PAGE] = 0xFF
    chr_[0x50 * si.CHR_PAGE + 8] = 0xFF
    hdr = bytes((0x4E, 0x45, 0x53, 0x1A, 16, 16, 0x40, 0, 0, 0, 0, 0, 0, 0, 0, 0))
    return hdr + bytes(prg) + bytes(chr_), (offsets, table, page_off, root)


def test_parse_ines_mmc3():
    data, _ = synth_rom()
    h = si.parse_ines(data)
    assert h["mapper"] == 4 and h["mapper_name"] == "MMC3"
    assert h["prg_size"] == 0x40000 and h["chr_size"] == 0x20000
    assert h["mirroring"] == "horizontal" and not h["battery"] and not h["trainer"]
    assert h["trailing_bytes"] == 0
    with pytest.raises(ValueError):
        si.parse_ines(b"XXXX" + data[4:])
    with pytest.raises(ValueError):
        si.parse_ines(data[:1000])


def test_locate_tables_and_xrefs():
    data, (offsets, table, page_off, root) = synth_rom()
    prg, _ = si.split(data, si.parse_ines(data))
    t = si.locate_player_tables(prg)
    assert t["prg_bank"] == 29
    assert t["sppf_offsets"]["prg_offset"] == offsets
    assert t["sppf_table"]["cpu"] == 0xCC00 + si.FRAMES
    assert t["pup_root_page"]["prg_offset"] == root
    assert t["root_pages"]["small"] == 0x50 and t["root_pages"]["hammer"] == 0x44
    x = t["xrefs"]
    assert [r["cpu"] for r in x["sppf_table"]] == [0xD000]
    assert [r["op"] for r in x["sppf_offsets"]] == ["LDA,X"]
    assert [r["op"] for r in x["pup_root_page"]] == ["LDA,Y"]
    assert len(x["frame_page_off"]) == 1


def test_locate_rejects_broken_offsets():
    data, (offsets, *_rest) = synth_rom()
    prg = bytearray(si.split(data, si.parse_ines(data))[0])
    prg[offsets + 5] ^= 1
    with pytest.raises(ValueError):
        si.locate_player_tables(bytes(prg))


def test_player_inventory_pages_and_shared_patterns():
    data, _ = synth_rom()
    prg, chr_ = si.split(data, si.parse_ines(data))
    inv = si.player_inventory(prg, chr_, si.locate_player_tables(prg))
    small = inv["powerups"]["small"]
    assert small["pages"] == [0x50, 0x51, 0x52, 0x53]
    assert small["chr_offsets"][0] == 0x50 * 0x400
    f0 = small["frames"][0]["sprites"]
    assert [s["slot"] for s in f0] == [0, 1, 3, 4, 5]  # slot 2 hidden
    assert f0[-1]["page"] is None  # $A9 lives in the shared $1800 page
    assert inv["shared_page_patterns"] == [0xA9]
    assert si.pattern_page(0x50, 0x03, None) == (0x50, 0x02)
    assert si.pattern_page(0x50, 0xAB, 0x4E) == (0x4E, 0x2A)


def test_tile_decode_and_png():
    data, _ = synth_rom()
    prg, chr_ = si.split(data, si.parse_ines(data))
    assert si.tile(chr_, 0x50 * 64)[0] == [3] * 8
    assert si.tile(chr_, 0x50 * 64)[1] == [0] * 8
    inv = si.player_inventory(prg, chr_, si.locate_player_tables(prg))
    w, h, px = si.render_sheet(chr_, inv)
    png = si.png_bytes(w, h, px)
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and w == si.FRAMES * 26 and h == 7 * 34
    assert px[3] == 255  # frame 0 top-left pixel is opaque colour 3


def test_identify_and_zip_source(tmp_path):
    data, _ = synth_rom()
    z = tmp_path / "game.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("game.nes", data)
    got, info = si.read_source(z)
    assert got == data and info["member"] == "game.nes"
    assert info["sha256"] == hashlib.sha256(z.read_bytes()).hexdigest()
    ident = si.identify(data[16:])
    assert ident["match"] is False and len(ident["sha256"]) == 64


@pytest.mark.skipif(not REAL.exists(), reason="owned SMB3 ROM not cached")
def test_owned_rom_rev0():
    m = si.inventory(REAL)
    assert m["identity"]["match"] and m["identity"]["revision"] == "Rev 0 (PRG0)"
    assert m["identity"]["crc32"] == "a0b0b742"
    assert m["player_tables"]["sppf_table"]["cpu"] == 0xCC51
    assert m["player_tables"]["xrefs"]["sppf_table"][0]["cpu"] == 0xCF1E
    pu = m["player"]["powerups"]
    assert pu["tanooki"]["pages"] == [64, 65, 66, 67]
    assert pu["leaf"]["pages"] == [0, 1, 2, 3]
    json.dumps(m, default=str)
