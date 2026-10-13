"""WCW vs. nWo: World Tour (USA, NWNE rev 1) owned-build inventory (#1354)."""
from pathlib import Path

import pytest

from gbox import aki_wcw as W
from gbox import wcw_worldtour_inventory as I

ROMS = Path("/mnt/gbox/hyperspin/Arcade/collections/Nintendo 64/roms")
WT_ZIP = ROMS / "USA/WCW vs. nWo - World Tour (USA) (Rev A).zip"
WT_Z64_SHA256 = "3711c8838b18374d1c7be0192ad824082d33978f00b886d145bc55a782325d4d"
WT_ZIP_SHA256 = "25d2b6d2fccc76cf67ff7c63cd7f32116b649c43a0e2f157347ef8a92ee84f2d"


def test_wt_header_selects_worldtour_profile():
    rom = bytearray(0x1000)
    rom[0x3B:0x3F], rom[0x3F] = b"NWNE", 1
    p = W.profile(bytes(rom))
    assert p["layout"] == "wt" and (p["first"], p["ft"], p["nfiles"]) == (0x39500, 0x7C1C70, 0x157A)
    assert (p["nmodels"], p["groups"], p["bodies"]) == (19, 8, 44)
    assert [k for _r, _i, k in p["patch"]] == ["malloc", "ft_hi", "ft_lo", "total", "sizes", "loop_bytes", "bound",
                                               "body_hi", "body_lo"]


def test_container_reports_v64_member_despite_n64_extension(tmp_path):
    import zipfile
    v64 = bytearray(0x1000)
    v64[0:4] = b"\x37\x80\x40\x12"                      # byte-swapped word
    v64[0x20:0x34] = b"WCWvs.NWO:World Tour"
    v64[0x3B:0x3F] = b"NWNE"
    z = tmp_path / "wt.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("WCW vs. nWo - World Tour (USA) (Rev A).n64", bytes(v64))
    c = I.container(z)
    assert c["members"][0]["byte_order"].startswith("v64") and c["members"][0]["extension_matches"] is False
    assert c["members"][0]["name"].endswith(".n64")


def test_header_fields_from_a_synthetic_header():
    import hashlib
    rom = bytearray(0x1000)
    rom[0x20:0x34] = b"WCWvs.NWO:World Tour"
    rom[0x3B:0x3F] = b"NWNE"
    rom[0x3F] = 1
    h = I.header(bytes(rom))
    assert (h["code"], h["region"], h["rev"]) == ("NWNE", "USA", 1)
    assert h["sha256_z64"] == hashlib.sha256(bytes(rom)).hexdigest()


@pytest.mark.skipif(not WT_ZIP.exists(), reason="owned World Tour ROM not mounted")
def test_owned_worldtour_build_manifest_matches_the_known_build():
    from gbox import n64_rom
    rom = n64_rom.read(WT_ZIP)
    h = I.header(rom)
    assert (h["code"], h["rev"], h["region"]) == ("NWNE", 1, "USA")
    assert (h["crc1"], h["crc2"]) == ("71be60b9", "1ddbfb3c")
    assert h["sha256_z64"] == WT_Z64_SHA256
    assert I.container(WT_ZIP)["sha256"] == WT_ZIP_SHA256
    m = I.inventory(rom, WT_ZIP)
    assert m["profile"] == {"code": "NWNE", "rev": 1}
    assert m["file_table"]["files"] == 5498 and m["file_table"]["lzss"] > 1000
    r = m["roster"]
    assert (r["wrestlers"], r["costumes"]) == (45, 180)
    assert (r["part_models"], r["textures"], r["palettes"]) == (233, 580, 776)
    assert (r["parts_per_body"], r["bodies"]) == (19, 44)
    assert sorted(r["unnamed"]) == ["0x002", "0x601", "0x701"]
    # the free ROM tail behind the moved file table is the writer's appendable space
    tail_off, tail_len = m["layout"]["free_tail"]
    assert tail_off + tail_len == len(rom) and tail_len == len(rom) - 0x7C1C70
    hogan = next(w for w in m["wrestlers"] if w["name"] == "Hulk Hogan")
    assert len(hogan["costumes"]) == 4
    # 19 body parts + face (19) and head_back (20) model ids
    assert len(hogan["costumes"][0]["parts"]) == 21 and set(hogan["costumes"][0]["parts"]) >= {"0", "19", "20"}
    # every writer patch site holds the instruction the profile expects
    for ram, ins, _k in W.PROFILES[("NWNE", 1)]["patch"]:
        assert int.from_bytes(rom[W.Rom.r2r(ram):W.Rom.r2r(ram) + 4], "big") == ins
    # the manifest is deterministic byte-for-byte
    assert I.inventory(rom, WT_ZIP) == m
