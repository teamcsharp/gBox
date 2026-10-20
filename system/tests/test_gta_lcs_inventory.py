"""LCS PS2 owned-source inventory (#1313): pure parsers, plus the exact owned build when it is on this machine."""
import struct
from pathlib import Path

import pytest

from gbox.gta_lcs_inventory import classify_special, inventory, parse_dir, parse_system_cnf

ISO = Path.home() / "gBox_alt/gbox-cache/modbase/002b9dca58a18ea1/Grand Theft Auto - Liberty City Stories (USA).iso"
ISO_SHA256 = "9e45271f8835f6b77213c8a7ff3bd1e4307fffa9c3f4434cf8498a5a7b59c4fe"
CHD_SHA256 = "77b5f5c9a0e26045f7ea27fe945ab1dcb65dbc4b41a32979cf156a7fe481e7ca"


def test_system_cnf_names_the_boot_executable():
    c = parse_system_cnf("BOOT2 = cdrom0:\\SLUS_214.23;1\r\nVER = 1.01\r\nVMODE = NTSC\r\n")
    assert c == {"boot": "cdrom0:\\SLUS_214.23;1", "executable": "SLUS_214.23", "ver": "1.01", "vmode": "NTSC"}


def test_directory_entries_stop_at_the_first_blank_record():
    rec = lambda s, n, name: struct.pack("<II", s, n) + name.encode().ljust(24, b"\0")
    blob = rec(0, 1490, "biker.ifp") + rec(1490, 1, "biker.cut") + bytes(32) + rec(9, 9, "junk.dat")
    assert parse_dir(blob) == [{"name": "biker.ifp", "sector": 0, "sectors": 1490},
                               {"name": "biker.cut", "sector": 1490, "sectors": 1}]


@pytest.mark.parametrize("name,role", [
    ("player", "player_base"), ("plr", "player_outfit"), ("plr3", "player_outfit"), ("plr16", "player_outfit"),
    ("player10", "player_alt"), ("toni_A1", "player_alt"), ("csplr3", "cutscene_player"),
    ("csplayer12", "cutscene_player"), ("cstoni_a", "cutscene_player"), ("cscheryl", "cutscene"),
    ("csphone", "cutscene"), ("Donovan", "story"), ("playersdoor", "story")])
def test_special_model_roles(name, role):
    assert classify_special(name) == role


@pytest.mark.skipif(not ISO.exists(), reason="owned LCS USA disc image not on this machine")
def test_owned_usa_disc_inventory():
    m = inventory(ISO, rom_sha256=CHD_SHA256, iso_sha256=ISO_SHA256)
    assert m["blockers"] == []
    assert m["boot"]["executable"] == "SLUS_214.23" and m["boot"]["executable_size"] == 2994708
    assert m["source"]["iso_sectors"] == 1958016                      # the CHD's MODE1 frame count
    assert m["game_dtz"]["model_infos"] == 4118 and m["ped_model_infos"]["count"] == 107
    assert m["cutscene_anims"]["by_extension"] == {"ifp": 24, "cut": 24, "dat": 24}
    sm = {e["name"]: e for e in m["special_models"]["entries"]}
    assert m["special_models"]["count"] == 160
    for k in ["player", "plr"] + [f"plr{i}" for i in range(2, 17)]:   # every outfit the player slot can load
        e = sm[k]
        assert e["kind"] == "ped" and e["layout"] == "ped_mdl" and e["bones"] == 24, k
        assert e["txd"] and e["txd"]["textures"], k
    assert sm["plr3"]["textures"] == ["IG_Toni_Traveller_body", "IG_Toni_Traveller_head"]
    # cutscene characters are bare element groups (no CColModel) with a 53-node face rig
    assert sm["csplr3"]["layout"] == "clump" and sm["csplr3"]["kind"] == "ped" and sm["csplr3"]["bones"] == 53
    assert sm["cscheryl"]["kind"] == "ped"
    assert sm["cs9mm"]["kind"] == "skinned_object" and sm["cs9mm"]["bones"] == 2
    assert sm["playersdoor"]["kind"] == "object"
