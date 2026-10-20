"""Tests for gbox.smb3_analysis: SMB3 (NES) player-sprite code analysis (#1328).

The synthetic tests use the byte-exact Rev 0 routines, so they run without
the ROM.  The owned-ROM tests use ``GBOX_SMB3_SRC`` (default: the gBox cache
copy of the owned hyperspin zip) and skip when it is absent.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("capstone")

from gbox import smb3_analysis as ana  # noqa: E402
from gbox import smb3_inventory as inv  # noqa: E402

SRC = Path(os.environ.get("GBOX_SMB3_SRC",
                          str(Path.home() / "gBox_alt/gbox-cache/213e4208929ec3e9/source.zip")))
SRC_SHA256 = "4938974428c867c5ec074b8853b496f91bd82014c2cddf9245a6d1a77eb39cfd"
needs_rom = pytest.mark.skipif(not SRC.is_file(), reason="owned SMB3 source not cached")

# Rev 0 bytes: PT2_Full_CHRROM_Switch loop, Player_Draw head, PowerUp_Palettes
# and Level_SetPlayerPUpPal.
MMC3_LOOP = bytes.fromhex("a005 98 0940 8d0080 b91907 8d0180 88 10f1")
PLAYER_DRAW = bytes.fromhex("a6ee bd37ce 8500 a4ed b998ce 18 6500 8d1b07")
PALETTES = bytes.fromhex("0016360f 002a360f 00273616 00000000 002a360f 0017360f 0030270f 0000100f")
SET_PAL = bytes.fromhex(
    "a007 ad7a05 d00e a5ed a8 c903 f004 c902 1003 ac2607 ae0003 8a 18 6906 8d0003"
    " a93f 9d0103 a911 9d0203 a903 9d0303 a900 9d0703 98 0a 0a a8"
    " b92aa5 9d0403 8dd207 b92ba5 9d0503 8dd307 b92ca5 9d0603 8dd407 60")


def _put(prg: bytearray, bank: int, off: int, blob: bytes) -> None:
    prg[bank * 0x2000 + off: bank * 0x2000 + off + len(blob)] = blob


def test_synthetic_mmc3_layout_from_loop():
    prg = bytearray(0x40000)
    _put(prg, 31, 0x1FAD, MMC3_LOOP)
    lay = ana.mmc3_layout(bytes(prg))
    assert lay["routine"] == 0xFFAD and lay["pattable_bank_sel"] == 0x0719
    assert (lay["prg_mode"], lay["chr_mode"]) == (1, 0)
    assert lay["chr_windows"][2] == {"reg": 2, "ram": 0x071B, "ppu": 0x1000, "size": 0x400}
    assert ana.chr_reg(lay, 0x1A80) == 4 and lay["cpu_windows"]["$C000"] == "R6"


def test_synthetic_player_draw_and_palette_rules():
    prg = bytearray(0x40000)
    _put(prg, 31, 0x1FAD, MMC3_LOOP)
    _put(prg, 29, 0x0E9F, PLAYER_DRAW)
    _put(prg, 29, 0x1240, bytes.fromhex("209fce"))
    _put(prg, 8, 0x0529, PALETTES + SET_PAL)
    prg = bytes(prg)
    lay = ana.mmc3_layout(prg)
    tables = {"prg_bank": 29, "frame_page_off": {"cpu": 0xCE37}, "pup_root_page": {"cpu": 0xCE98}}
    draw = ana.player_draw(prg, tables, lay)
    assert (draw["entry"], draw["frame_zp"], draw["suit_zp"]) == (0xCE9F, 0xEE, 0xED)
    assert (draw["bank_store"], draw["chr_reg"], draw["ppu"]) == (0x071B, 2, 0x1000)
    assert draw["callers"] == [0xD240]
    rules = ana.palette_rules(prg, draw)
    assert (rules["bank"], rules["entry"], rules["table_cpu"]) == (8, 0xA549, 0xA529)
    assert (rules["ppu"], rules["run"]) == (0x3F11, 3)
    assert rules["palette_buffer"] == [0x07D2, 0x07D3, 0x07D4]
    assert (rules["raccoon_suit"], rules["fire_suit"], rules["statue_index"]) == (3, 2, 7)
    # small/big/leaf follow Player_Current, the rest ignore it.
    assert [ana.palette_index(rules, s, 1) for s in range(7)] == [1, 1, 2, 1, 4, 5, 6]
    assert ana.colours(rules, 0, 1, statue=True) == [0x00, 0x10, 0x0F]


@pytest.fixture(scope="module")
def report():
    if not SRC.is_file():
        pytest.skip("owned SMB3 source not cached")
    return ana.analyze(SRC)


@needs_rom
def test_rev0_identity_and_code_trace(report):
    assert report["source"]["sha256"] == SRC_SHA256
    assert report["identity"]["match"] and report["identity"]["revision"] == "Rev 0 (PRG0)"
    lay, draw = report["mmc3"], report["player_draw"]
    assert lay["bank"] == 31 and lay["pattable_bank_sel"] == 0x0719
    assert (lay["prg_mode"], lay["chr_mode"]) == (1, 0)
    assert (draw["bank"], draw["entry"]) == (29, 0xCE9F)
    assert (draw["bank_store"], draw["chr_reg"], draw["ppu"]) == (0x071B, 2, 0x1000)
    assert 0xD240 in draw["callers"] and len(draw["callers"]) >= 6
    # The inventory's table xrefs sit inside the traced routine.
    assert report["table_xrefs"]["sppf_table"][0]["cpu"] == 0xCF1E


@needs_rom
def test_rev0_palette_rules(report):
    pal = report["palettes"]
    assert (pal["bank"], pal["entry"], pal["table_prg_offset"]) == (8, 0xA549, 0x10529)
    assert (pal["ppu"], pal["run"], pal["player_current"]) == (0x3F11, 3, 0x0726)
    by = pal["by_suit"]
    for suit in ("small", "big", "leaf"):
        assert by[suit]["mario"]["colours"] == [0x16, 0x36, 0x0F]
        assert by[suit]["luigi"]["colours"] == [0x2A, 0x36, 0x0F]
    expect = {"fire": [0x27, 0x36, 0x16], "frog": [0x2A, 0x36, 0x0F],
              "tanooki": [0x17, 0x36, 0x0F], "hammer": [0x30, 0x27, 0x0F]}
    for suit, col in expect.items():
        assert by[suit]["mario"]["colours"] == by[suit]["luigi"]["colours"] == col


@needs_rom
def test_rev0_kuribo_shoe_shared_page(report):
    k, obj = report["kuribo"], report["object_chr_request"]
    assert k["frames"] == [0x18, 0x19, 0x43, 0x44]
    assert k["patterns"] == [0xA9, 0xAB, 0xAD] and k["pattern_regs"] == [4]
    assert (obj["bank"], obj["site"], obj["store"]) == (0, 0xCA72, 0x071D)
    assert (k["object_bank"], k["request"], k["chr_reg"], k["page"]) == (2, 0x0B, 4, 0x0B)
    assert k["blank_tiles"] == []
    assert report["probe"]["kuribo_big"]["bottom_opaque"] > 0
    assert report["probe"]["kuribo_big"]["bottom_opaque_without_shared"] == 0


@needs_rom
def test_rev0_grow_override_pages(report):
    g = report["grow"]
    assert (g["site"], g["even_base"], g["odd_base"]) == (0xD240, 0x54, 0x44)
    assert (g["ora_imm_cpu"], g["sbc_imm_cpu"]) == (0xD249, 0xD24F)
    assert g["grow_frames"] == [0x0E, 0x27] * 3 + [0x0B, 0x27] * 3
    assert {s["page"] & 0xFC for s in g["steps"] if s["frame"] == 0x27} == {0x44}


@needs_rom
def test_rev0_probe_one_frame_per_powerup(report):
    pr = report["probe"]
    for s, suit in enumerate(inv.POWERUPS):
        m, lu = pr[f"{suit}/mario"], pr[f"{suit}/luigi"]
        assert m["frame"] == ana.PROBE_FRAMES[suit] and m["opaque_pixels"] > 100
        assert set(m["indices_used"]) <= {1, 2, 3} and m["index_sha256"] == lu["index_sha256"]
        if suit in ("small", "big", "leaf"):
            assert m["rgb_sha256"] != lu["rgb_sha256"]
        else:
            assert m["rgb_sha256"] == lu["rgb_sha256"]
    assert pr["small/mario"]["page"] != pr["big/mario"]["page"]


@needs_rom
def test_cli_writes_report_and_sheet(tmp_path):
    out, png = tmp_path / "a.json", tmp_path / "s.png"
    ana.main([str(SRC), "--out", str(out), "--png", str(png)])
    rep = json.loads(out.read_text())
    assert rep["stage"] == "analysis" and len(rep["constraints"]) == 7
    blob = png.read_bytes()
    assert blob[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = int.from_bytes(blob[16:20], "big"), int.from_bytes(blob[20:24], "big")
    assert (w, h) == (inv.FRAMES * 26, len(inv.POWERUPS) * 2 * 34)
