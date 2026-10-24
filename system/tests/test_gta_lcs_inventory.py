"""LCS PS2 owned-source inventory (#1313): pure parsers, plus the exact owned build when it is on this machine."""
import struct
from pathlib import Path

import pytest

from gbox.gta_lcs_inventory import anim_blocks, classify_special, inventory, parse_dir, parse_system_cnf
from gbox.gta_stories_models import LcsDisc

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


@pytest.mark.skipif(not ISO.exists(), reason="owned LCS USA disc image not on this machine")
def test_owned_player_load_path_slot_0_plr3_and_txd_56():
    # the analysis stage's probe: the player is special model slot 0, TXD slot 56, story start plr3
    disc = LcsDisc(ISO)
    mi = disc.model_info(0)
    assert mi and mi["type"] == 7 and mi["txd_slot"] == 56           # slot 56 = 'player' TXD (IMG sector 0)
    assert disc.txd_name(56) == "player"
    e = disc.special("plr3")
    # a CDirectory entry as FindItem (0x1450D8) reads it: {u32 sector, u32 sectors, char name[24]}
    g = disc.game
    assert e["dir_offset"] > 0 and g.b[e["dir_offset"] + 8:e["dir_offset"] + 13] == b"plr3\0"
    assert e["sectors"] > 0 and e["sector"] > 0
    # slot 0's streaming size is 0: the player loads by name from the special-model directory
    s, n = disc.streaming(0)
    assert (s, n) == (0, 0)


@pytest.mark.skipif(not ISO.exists(), reason="owned LCS USA disc image not on this machine")
def test_owned_dtz_ped_animation_tables():
    # the ped animations are GAME.DTZ blocks behind the GTAG hdr[0x18] animation-manager struct
    disc = LcsDisc(ISO)
    ab = anim_blocks(disc)
    g = disc.game
    assert ab["manager"] == 0x4A1C14                       # dispatch target of the DTZ loader 0x1045A8
    assert (ab["num_anims"], ab["num_blocks"]) == (444, 55)
    assert ab["blocks_base"] < ab["anims_base"] < 0x395098 + 444 * 0x24
    # block-name dir: 0x28-byte entries, packed name at +0
    assert g.b[ab["blocks_base"] + 0x28:ab["blocks_base"] + 0x28 + 8] == b"baseball"
    # anim table: 0x24-byte entries {u32 key_data_ptr, name..., u32 bones, f32 frame_time}
    assert g.b[ab["anims_base"] + 4:ab["anims_base"] + 4 + 6] == b"abseil"
    e = ab["anims_base"] + 3 * 0x24
    assert g.b[e + 4:e + 4 + 11] == b"BIKE_elbowL" and g.b[e + 15] == 0
    data = struct.unpack_from("<I", g.b, ab["anims_base"])[0]
    assert 0 < data < len(g.b)                            # key data lives inside GAME.DTZ itself


@pytest.mark.skipif(not ISO.exists(), reason="owned LCS USA disc image not on this machine")
def test_owned_plr3_noop_roundtrip_writer(tmp_path):
    # writer stage, no-op: plr3.mdl with its own geometry block, its textures re-encoded unchanged, and the IMG
    # patch with the original bytes all reproduce the owned disc
    import numpy as np
    from gbox.gta_stories_models import Reloc, patch_iso, read_chk, read_ped, replace_chk, replace_geometry, txd_for
    disc = LcsDisc(ISO)
    e = disc.special("plr3")
    orig = disc.file_at(e["sector"])
    r = Reloc(orig)
    a = r.u32(r.u32(0x24) + 8) - 0x1C
    g = r.u32(a + 0x14) + 0x20
    block = orig[g:g + (r.u32(g + 16) & 0xFFFFF)]
    assert replace_geometry(orig, block) == orig
    assert len(read_ped(orig).bone_names()) == 24
    # a grown block still parses and keeps the bones
    grown = replace_geometry(orig, block + bytes(64))
    assert len(grown) == len(orig) + 64 and len(read_ped(grown).bone_names()) == 24
    ts, tn = txd_for(disc, "plr3")
    chk = disc.file_at(ts)
    texs = read_chk(chk)
    new = replace_chk(chk, {t.name: t.rgba for t in texs})
    assert len(new) == len(chk)
    assert all(np.array_equal(t.rgba, u.rgba) for t, u in zip(texs, read_chk(new)))
    assert len(orig) <= e["sectors"] * 2048 and len(chk) <= tn * 2048
    # patch_iso with the unchanged bytes leaves the image identical (sparse stand-in holding only the two slots)
    fake = tmp_path / "fake.iso"
    with open(fake, "wb") as f:
        f.truncate((disc.img_lba + ts + tn + 1) * 2048)
        for sec, n in ((e["sector"], e["sectors"]), (ts, tn)):
            f.seek((disc.img_lba + sec) * 2048)
            f.write(disc.img_read(sec, n))
    before = fake.read_bytes()
    patch_iso(fake, disc, [(e["sector"], e["sectors"], orig), (ts, tn, chk)])
    assert fake.read_bytes() == before
