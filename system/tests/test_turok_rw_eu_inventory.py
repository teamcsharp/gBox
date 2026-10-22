"""Turok: Rage Wars (Europe, NRWP) cart inventory: owned-ROM checks.

The Europe catalog entry is a different build from the USA one
(gbox.turok_rw_inventory): PAL video, no debug symbol records and a
relocated character-select table.  These tests pin the Europe facts that
were measured from the owned bytes.
"""
import functools
import hashlib
import os
from pathlib import Path

import pytest

from gbox import turok_rw_eu_inventory as eu

MOUNT = Path("/mnt/gbox/hyperspin/Arcade/collections/Nintendo 64/roms/"
             "Europe/Turok - Rage Wars (Europe).zip")
CACHE = Path.home() / "gbox-cache" / "f275116453c8709d" / "source.zip"
SOURCE = Path(os.environ.get("GBOX_TUROK_RW_EU_SOURCE")
              or (CACHE if CACHE.exists() else MOUNT))

SOURCE_SHA256 = "2e253f919835ff6b680fb88969b1eff17debc62d6242dc9f39ecb73947a09b06"
ROM_SHA256 = "d763cbbe485a5f9e1b7be97d5ac16735087e23d0bb62c05dc844e01b7e1156d1"
# SHA-1 over the decompressed geometry parts of GraphicObject 174, as
# measured on the owned Europe image (identical to the USA build's object).
OBJ174_GEOMETRY_SHA1 = "b2dab07a5212f7377a8557a23aa6bfb960bef93e"
OBJ174_UNPACKED_BYTES = 237968

_USA_LOCAL = CACHE.parent / "usa_source.zip"
USA_MOUNT = Path(os.environ.get("GBOX_TUROK_RW_US_SOURCE")
                 or (_USA_LOCAL if _USA_LOCAL.exists()
                     else Path("/mnt/gbox/hyperspin/Arcade/collections/Nintendo 64/roms/"
                               "USA/Turok - Rage Wars (USA).zip")))


@functools.lru_cache(maxsize=1)
def _rom():
    from gbox import n64_rom
    return n64_rom.read(SOURCE)


def _table(names):
    """A roster table laid out like the ROM's: NUL separated, 4-byte aligned."""
    out = b""
    for name in names:
        out += name.encode("ascii") + b"\0"
        while len(out) % 4:
            out += b"\0"
    return out


def test_roster_table_discovery_is_offset_independent():
    names = ["TUROK", "MANTID DRONE", "CAMPAIGNER", "FIREBORN", "ADON",
             "GUARDIAN", "RAPTOR", "MANTID MITES"]
    rom = b"\0" * 0x40 + _table(names)
    tables = eu.find_roster_tables(rom)
    assert [t["offset"] for t in tables] == [0x40]
    assert tables[0]["names"] == names


def test_english_roster_is_recognised():
    rom = b"\0" * 0x100 + _table(eu.ENGLISH_ROSTER)
    tables = eu.find_roster_tables(rom)
    assert tables and tables[0]["english"]
    assert tables[0]["offset"] == 0x100


def test_english_roster_is_not_confused_with_a_localised_table():
    italian = ["TUROK", "RONZIO MANTIDE", "CAMPAIGNER", "FIGLIO DEL FUOCO",
               "SOLFATO MANTIDE", "ADON", "GUARDIANO", "RAPTOR"]
    rom = b"\0" * 0x40 + _table(italian)
    tables = eu.find_roster_tables(rom)
    assert tables and not tables[0]["english"]


def test_manifest_requires_a_z64_image():
    from gbox import n64_rom
    # A v64 (byte-swapped) image is normalised to z64; a non-N64 blob is rejected.
    assert n64_rom.normalize(b"\x37\x80\x40\x12" + b"\0" * 16)[:4] == b"\x80\x37\x12\x40"
    with pytest.raises(ValueError):
        n64_rom.normalize(b"\x00\x00\x00\x00" + b"\0" * 16)


@pytest.mark.skipif(not SOURCE.exists(), reason="owned Europe Rage Wars ROM not reachable")
def test_owned_europe_rom_identity():
    from gbox import n64_rom
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == SOURCE_SHA256
    rom = n64_rom.read(SOURCE)
    assert hashlib.sha256(rom).hexdigest() == ROM_SHA256
    h = eu.rw.header(rom)
    assert (h["serial"], h["version"], h["ipl3_crc32"]) == ("NRWP", 0, "90bb6cb5")
    assert h["name"] == "Turok: Rage Wars"


@pytest.mark.skipif(not SOURCE.exists(), reason="owned Europe Rage Wars ROM not reachable")
def test_owned_europe_container_inventory():
    from gbox import turok_rw_inventory as rw
    rom = _rom()
    assert rw.find_cart_root(rom) == rw.CART_ROOT_OFFSET == 0x50F768
    inv = rw.inventory(rom)
    go = inv["graphic_objects"]
    assert (go["total"], go["valid"], go["animated"]) == (347, 347, 90)
    assert go["geometry_parts_rnc_ok"] == 386 and not go["geometry_parts_fail"]
    assert go["geometry_unpacked_bytes"] == 954496
    assert inv["object_types"]["n"] == 347
    ts = inv["texture_sets"]
    assert (ts["total"], ts["rnc_ok"], ts["rnc_fail"]) == (507, 507, [])
    assert ts["format_counts"] == {"CI8_RGBA": 272, "CI4_RGBA": 180, "CI4_IA": 55}
    assert inv["levels"] == {"total": 37, "blocks_per_level": {13: 37}}
    assert inv["cart_end"] == 0x7A0B00


@pytest.mark.skipif(not SOURCE.exists(), reason="owned Europe Rage Wars ROM not reachable")
def test_owned_europe_roster_tables():
    rom = _rom()
    roster = eu.select_roster(rom)
    # The PAL build relocates the select table; it is found by scanning.
    assert roster["english_offset"] == 0xD0A58
    assert roster["english_copies"] == [0xD0A58, 0xD52A8, 0x162358, 0x166D40]
    assert roster["names"] == eu.ENGLISH_ROSTER
    # French, Italian and Spanish copies of the same table are also present.
    assert len(roster["localised_tables"]) >= 4
    # The USA build's debug symbol records are absent from the PAL build.
    assert eu.player_character_enum(rom, 0x50F768)["present"] is False


@pytest.mark.skipif(not SOURCE.exists(), reason="owned Europe Rage Wars ROM not reachable")
def test_owned_europe_target_asset_is_object_174():
    rom = _rom()
    asset = eu.target_asset(rom, 174)
    assert (asset["index"], asset["anim_type"], asset["anims"]) == (174, 1120, 44)
    assert asset["geometry_parts"] == 37
    assert asset["geometry_unpacked_bytes"] == OBJ174_UNPACKED_BYTES
    assert asset["geometry_sha1"] == OBJ174_GEOMETRY_SHA1
    assert all(p["rnc_method"] == 1 for p in asset["parts"])
    assert not [p for p in asset["parts"] if "error" in p]
    # Every part offset stays inside the cartridge image.
    assert all(p["rom"] + p["packed_size"] <= len(rom) for p in asset["parts"])


@pytest.mark.skipif(not USA_MOUNT.exists(), reason="USA comparison ROM not reachable")
def test_europe_target_asset_matches_the_usa_build():
    """Compatibility is measured, not assumed: object 174 is byte-identical."""
    from gbox import n64_rom
    eu_asset = eu.target_asset(_rom(), 174)
    us_asset = eu.target_asset(n64_rom.read(USA_MOUNT), 174)
    assert eu_asset["geometry_sha1"] == us_asset["geometry_sha1"]
    assert [p["unpacked_sha256"] for p in eu_asset["parts"]] == \
           [p["unpacked_sha256"] for p in us_asset["parts"]]
