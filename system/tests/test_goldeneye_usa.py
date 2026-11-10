"""USA build profile for the GoldenEye reader (owned-ROM test; skipped if absent)."""
import hashlib
import os
from pathlib import Path

import pytest

from gbox import goldeneye_files as gf
from gbox import goldeneye_reader as gr

USA_ROM = Path(os.environ.get("GE_USA_ROM", Path.home() / ".hermes/cache/scratch/usa_rom.z64"))


def test_profiles_keyed_by_sha():
    assert gf.PROFILES[gf.PAL_Z64_SHA256] is gf.PAL_PROFILE
    assert gf.PROFILES[gf.USA_Z64_SHA256] is gf.USA_PROFILE
    assert gf.PAL_PROFILE.data_seg_rom == 0x1F850 and gf.PAL_PROFILE.data_vram == 0x8001EC50
    assert gf.PAL_PROFILE.g_textures_data_off == gr.G_TEXTURES_DATA_OFF
    assert gf.PAL_PROFILE.images_rom_start == gr.IMAGES_ROM_START


@pytest.fixture(scope="module")
def usa():
    if not USA_ROM.exists():
        pytest.skip("owned USA ROM not available")
    raw = USA_ROM.read_bytes()
    if hashlib.sha256(raw).hexdigest() != gf.USA_Z64_SHA256:
        pytest.skip("not the pinned USA z64")
    return gf.GoldenEyeROM.from_bytes(raw)


def test_usa_tables(usa):
    assert usa.profile.name == "USA"
    assert len(usa.data) == 0x3C550
    assert len(usa.body_table()) == 80
    assert len(usa.file_table()) == 727


def test_usa_images_pinned(usa):
    sizes = gr.g_textures(usa)
    assert len(sizes) == 2698 and sum(sizes) == 0x2EEF18
    assert sizes[:3] == [0x754, 0x16A, 0x974]  # n64decomp imagelist, build independent


def test_usa_all_characters_textures_match_model_records(usa):
    total = 0
    for b in usa.body_table():
        doc = gr.read_character(usa, b.filename)
        for t in doc["textures"]:
            d = gr.decode_model_texture(usa, t["index"])
            assert d["pixels"] is not None, (b.filename, t["index"])
            assert (d["width"], d["height"]) == (t["w"], t["h"]), (b.filename, t["index"])
            total += 1
    assert total == 836
