"""Thrasher PSX disc inventory: synthetic tests always run; the owned-disc test needs GBOX_THRASHER_BIN."""
import os
import struct

import pytest

from gbox import thrasher_inventory as T

BIN = os.environ.get("GBOX_THRASHER_BIN",
                     "/mnt/gbox/quickswap2/Emulation/_psx/Thrasher - Skate and Destroy (USA).bin")


def _exe(t_size=16):
    h = bytearray(0x800)
    h[:8] = b"PS-X EXE"
    struct.pack_into("<4I", h, 0x10, 0x80010000, 0, 0x8000F800, t_size)
    struct.pack_into("<I", h, 0x30, 0x801FFF00)
    return bytes(h) + b"\0" * t_size


def test_parse_exe():
    r = T.parse_psx_exe(_exe())
    assert r["pc0"] == 0x80010000 and r["t_addr"] == 0x8000F800 and r["sp_base"] == 0x801FFF00 and r["text_fits"]
    assert not T.parse_psx_exe(_exe()[:0x800 + 4])["text_fits"]
    with pytest.raises(ValueError):
        T.parse_psx_exe(b"nope" * 300)


def test_system_cnf():
    c = T.parse_system_cnf(b"BOOT = cdrom:\\slus_009.35;1\r\nSTACK = 801FFF00\r\n\x1a")
    assert c["BOOT"].lower().endswith("slus_009.35;1") and c["STACK"] == "801FFF00"


@pytest.mark.parametrize("name,cat", [
    ("SYSTEM.CNF", "boot_cnf"), ("SLUS_009.35", "boot_exe"), ("PLAYMOV.EXE", "exe"),
    ("ASSETS/MOTION.ZAL", "shared_zal"), ("ASSETS/LA_VEN.ZAL", "level_zal"),
    ("AUDIO/SFXCHR03.ZSD", "sfx_char"), ("AUDIO/SFXLEV11.ZSD", "sfx_level"), ("AUDIO/SFXGAME.ZSD", "sfx_common"),
    ("AUDIO/MUSIC.ZSD", "music"), ("AUDIO/SPEECH.ZSD", "speech"), ("MOVIE/INTRO.STR", "movie"),
    ("PADDING.NUL", "pad"), ("AITEXT.BIN", "data")])
def test_classify(name, cat):
    assert T.classify(name) == cat


def test_inventory_and_cities():
    files = {"ASSETS/NY_SUB.ZAL;1": (10, 100), "ASSETS/SF_HILL.ZAL": (20, 50), "AUDIO/SFXCHR00.ZSD": (30, 5)}
    inv = T.inventory(files)
    assert inv["n_files"] == 3 and inv["characters"] == 1
    assert [x["city"] for x in inv["levels"]] == ["New York", "San Francisco"]
    assert inv["categories"]["level_zal"]["bytes"] == 150


@pytest.mark.skipif(not os.path.exists(BIN), reason="owned Thrasher disc image not available")
def test_owned_disc():
    from gbox.psxdisc import RawBin
    d = RawBin(BIN, writable=False)
    try:
        r = T.probe(d)
    finally:
        d.close()
    assert r["n_files"] == 62 and r["characters"] == 7
    assert r["boot_exe"]["sha256"] == T.BOOT_SHA256
    assert r["boot_exe"]["t_addr"] == 0x80010000 and r["boot_exe"]["pc0"] == 0x8005D1B0
    assert r["boot_exe"]["t_size"] == 503808 and r["boot_exe"]["sp_base"] == 0x801FFF00
    assert r["boot_exe"]["text_fits"] and r["system_cnf"]["BOOT"].lower().endswith("slus_009.35;1")
    assert len(r["levels"]) == 12 and all(r["zal_magic_ok"].values())
