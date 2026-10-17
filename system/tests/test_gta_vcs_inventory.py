"""Focused tests for gbox.gta_vcs_inventory (#1376).

The synthetic tests always run. The disc-backed test runs only when the owned VCS ISO is staged
(GBOX_VCS_ISO, default ~/gbox-cache/ps2/6f5a05916536492b/disc.iso, extracted from the catalog CHD
sha256 e21887a8...8884 with `chdman extractcd`).
"""
import os
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import gta_vcs_inventory as inv
from gbox.gta_stories_models import read_chk, write_chk

ISO = Path(os.environ.get("GBOX_VCS_ISO", str(Path.home() / "gbox-cache/ps2/6f5a05916536492b/disc.iso")))


def test_system_cnf_boot2():
    cnf = inv.parse_system_cnf("BOOT2 = cdrom0:\\SLUS_215.90;1\r\nVER = 1.00\r\nVMODE = NTSC\r\n")
    assert cnf["executable"] == inv.EXPECTED_BOOT
    assert (cnf["ver"], cnf["vmode"]) == ("1.00", "NTSC")


def _rec(sector, sectors, name):
    return struct.pack("<II", sector, sectors) + (name.encode() + b"\0mdl\0").ljust(24, b"\0")


def test_special_dir_longest_run_and_roles():
    junk = b"\x01" * 37 + _rec(9, 1, "stray") + b"\xff" * 40
    run = [_rec(311, 486, "special01"), _rec(14734, 26, "WMYGO"), _rec(18918, 73, "csplr"),
           _rec(19267, 71, "CSPlr12"), _rec(16872, 63, "CSFrank"), _rec(23779, 23, "CS_uzi")]
    d = junk + b"".join(run) + b"\0" * 64
    sd = inv.find_special_dir(d)
    assert [e["name"] for e in sd] == ["special01", "WMYGO", "csplr", "CSPlr12", "CSFrank", "CS_uzi"]
    assert (sd[0]["sector"], sd[0]["sectors"], sd[0]["dir_offset"]) == (311, 486, len(junk))
    assert [inv.classify_special(e["name"]) for e in sd] == [
        "special_slot", "story", "cutscene_player", "cutscene_player", "cutscene_ped", "cutscene_prop"]
    assert inv.find_special_dir(b"\0" * 256) == []


def test_parse_dir_mocap():
    rows = [(0, 3, b"BRYB1.CAM"), (3, 9, b"BRYB1.CUT"), (12, 40, b"BRYB1.ANIM")]
    d = b"".join(struct.pack("<II", s, n) + nm.ljust(24, b"\0") for s, n, nm in rows) + b"\0" * 32
    assert [(e["name"], e["sector"], e["sectors"]) for e in inv.parse_dir(d)] == [
        ("BRYB1.CAM", 0, 3), ("BRYB1.CUT", 3, 9), ("BRYB1.ANIM", 12, 40)]


def test_texlist_headers_match_lcs_reader():
    img = np.zeros((16, 16, 4), np.uint8)
    img[..., 0] = np.arange(16, dtype=np.uint8)[None, :] * 16
    img[..., 3] = 255
    chk = write_chk([("ig_vance_head_new", img), ("cop_pouch", img[::-1].copy())], depth=8)
    heads = inv.texlist_headers(chk)
    ref = read_chk(chk)
    assert [h["name"] for h in heads] == [t.name for t in ref] and len(heads) == 2
    assert [(h["w"], h["h"], h["depth"]) for h in heads] == [(t.width, t.height, t.depth) for t in ref]
    with pytest.raises(ValueError):
        inv.texlist_headers(b"ldm\0" + b"\0" * 60)


def test_elf_info_mips_load_segment():
    ident = b"\x7fELF" + bytes([1, 1, 1, 0]) + b"\0" * 8
    hdr = ident + struct.pack("<HHIIIIIHHHHHH", 2, 8, 1, 0x00100008, 52, 0, 0, 52, 32, 1, 40, 0, 0)
    ph = struct.pack("<8I", 1, 0x1000, 0x00100000, 0x00100000, 0x2000, 0x3000, 7, 0x10)
    e = inv.elf_info(hdr + ph)
    assert e["mips"] and e["entry"] == "0x00100008"
    assert e["load_segments"] == [{"offset": 0x1000, "vaddr": "0x00100000", "filesz": 0x2000, "memsz": 0x3000,
                                   "flags": 7}]
    with pytest.raises(ValueError):
        inv.elf_info(b"\0" * 64)


@pytest.mark.skipif(not ISO.exists(), reason="owned VCS ISO not staged")
def test_owned_disc_inventory():
    man = inv.build_manifest(ISO, hash_sources=False)
    assert man["boot"]["executable"] == "SLUS_215.90" and man["boot"]["matches"]
    assert man["boot"]["sha256"] == "3b43be57d60a29df35e41504d67bbf728d5ce2fc5aab6bbf928cbbc5963fe547"
    assert man["boot"]["elf"]["mips"]
    assert man["containers"]["file_count"] == 341
    c = man["characters"]
    assert c["model_infos"]["count_field"] == 7941 and len(c["peds"]) == 161
    assert c["player_model_info"] == {"index": 0, "hash": "0xb5ab388c", "type": 7, "txd_slot": 5, "txd": "plr"}
    assert len(c["special_dir"]) == 102 and c["special_dir"][0]["name"] == "special01"
    assert all(e["chunk"] == "mdl" for e in c["special_dir"])
    assert c["special_roles"]["cutscene_player"] == 14
    assert (c["img"]["mdl"], c["img"]["txd"]) == (757, 823)
    first = c["player_candidates"][0]
    assert (first["sector"], first["txd_sector"]) == (23, 0)
    assert first["sha256"] == "7cc7d77d5ac0875aeb6c19b01c6355ba14d67f566ceb906de347bbe43452790c"
    assert man["cutscenes"]["cutscenes"] == 49
    assert set(man["lcs_reader"]["read_ped"]) == {"WMYGO", "Frank", "Janet", "LouA"}
