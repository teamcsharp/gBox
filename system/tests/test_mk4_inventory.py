"""Focused tests for gbox.mk4_inventory (Mortal Kombat 4 USA, N64 NM4E rev 0)."""
from __future__ import annotations

import os
from pathlib import Path
import struct

import pytest

from gbox import mk4_inventory as mk4

SOURCE = Path(os.environ.get(
    "GBOX_MK4_SOURCE",
    "/mnt/gbox/hyperspin/Arcade/collections/Nintendo 64/roms/USA/Mortal Kombat 4 (USA).zip"))


def test_check_build_refuses_other_roms():
    src = {"z64_sha1": "0" * 40, "z64_md5": mk4.KNOWN["z64_md5"],
           "z64_size": mk4.KNOWN["z64_size"]}
    with pytest.raises(mk4.WrongBuild):
        mk4.check_build(src, {"game_code": "NM4E", "version": 0})
    good = {k: mk4.KNOWN[k] for k in ("z64_sha1", "z64_md5", "z64_size")}
    with pytest.raises(mk4.WrongBuild):
        mk4.check_build(good, {"game_code": "NM4P", "version": 0})
    mk4.check_build(good, {"game_code": "NM4E", "version": 0})


def test_patch_table_walk_stops_at_garbage():
    # anchor + two valid pairs, then a bad pair ends the table on the left/right
    rom = bytearray(mk4.PATCH_ANCHOR + 0x1000)
    pairs = [(0x1FFD10, 0x1EE794), (0x1FFD14, 0x1EE77C), (0x1FFD18, 0x1EEE24)]
    for k, (a, b) in enumerate(pairs):
        struct.pack_into(">2I", rom, mk4.PATCH_ANCHOR + 8 * (k - 2), a, b)
    struct.pack_into(">2I", rom, mk4.PATCH_ANCHOR + 8, 0, 0)  # right sentinel
    t = mk4.patch_table(bytes(rom))
    assert (t["start"], t["end"], t["entries"]) == (mk4.PATCH_ANCHOR - 16, mk4.PATCH_ANCHOR + 8, 3)
    assert t["rom_slots"] == 3 and t["ram_slots"] == 0


def test_bios_names_are_the_15_story_fighters():
    rom = bytearray(0x50000)
    for off, name in sorted(mk4.BIO_NAMES.items()):
        rom[off:off + len(name)] = name.encode() + b"\x00"
    fighters = mk4.bios(bytes(rom))
    assert [f["name"] for f in fighters] == [
        "SCORPION", "RAIDEN", "SONYA BLADE", "LIU KANG", "SUB ZERO", "FUJIN",
        "SHINNOK", "QUAN CHI", "REPTILE", "KAI", "TANYA", "JAX", "REIKO",
        "JOHNNY CAGE", "JAREK"]
    assert fighters[0]["offset"] == 0x4B4C8


def test_entropy_uniform_vs_empty():
    assert mk4.entropy(b"\x00" * 4096) == 0.0
    assert abs(mk4.entropy(bytes(range(256)) * 16) - 8.0) < 1e-9


@pytest.mark.skipif(not SOURCE.is_file(), reason="owned MK4 USA zip not reachable")
def test_owned_build_inventory(monkeypatch, tmp_path):
    monkeypatch.setenv("GBOX_N64_ROM_CACHE", str(tmp_path))
    m = mk4.inventory(SOURCE)
    s = m["source"]
    assert s["sha256"] == mk4.OWNED_ZIP_SHA256
    assert s["byte_order"] == "v64" and s["member_size"] == 0x1000000
    assert s["member"] == "Mortal Kombat 4 (USA).n64"
    assert s["z64_sha256"] == "ea908a1f790340dc34f1056c4799f7d0984048d90344607f2910d96abf036478"
    assert s["z64_sha1"] == mk4.KNOWN["z64_sha1"]
    h = m["header"]
    assert (h["game_code"], h["version"], h["internal_name"]) == ("NM4E", 0, "MORTAL KOMBAT 4")
    assert m["boot"]["cic"] == "6102" and m["boot"]["ipl3_crc32"] == "90bb6cb5"
    assert m["entry"]["main"] == 0x80000450 and m["entry"]["bss_start"] == 0x80050800
    lay = m["layout"]
    assert lay["boot"] == {"start": 0x1000, "end": 0x12FDB8}
    pt = lay["patch_table"]
    assert (pt["start"], pt["end"]) == (0x12FDB8, 0x132800) and pt["entries"] == 1353
    assert pt["rom_slots"] > 200 and pt["ram_values"] > 0
    assert lay["padding"] == [0xEB0000, 0x1000000]
    assert len(lay["audio_banks"]) == 41
    assert lay["audio_banks"][0] == 0x249880  # start of the "N64 WaveTables" header
    buckets = lay["assets"]["buckets"]
    assert any(b["kind"] == "low" for b in buckets)
    assert any(b["kind"] == "high" for b in buckets)
    chars = m["characters"]
    assert len(chars["story_fighters"]) == 15
    assert chars["full_roster"] == chars["story_fighters"] + ["GORO", "NOOB SAIBOT"]
    assert chars["goro_bio_offset"] == 0x4CB40 and chars["noob_saibot_kode_offset"] == 0x121349
    assert m["launch"]["platform"] == "n64" and m["launch"]["cic"] == "6102"
    assert m["next_step"].startswith("analysis:")
