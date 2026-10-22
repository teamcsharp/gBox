"""Inventory stage: Metroid Prime - Hunters (USA) (NDS, fe580e2ad4ec0052)."""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gbox.metroidprime_hunters_inventory as mph  # noqa: E402

ROM = (os.environ.get("GBOX_MPH_ROM")
       or "/home/ehm_eckx/.hermes/cache/scratch/mph/0367 - Metroid Prime Hunters (U)(WRG).nds")
ARCHIVE = (os.environ.get("GBOX_MPH_7Z")
           or "/mnt/gbox/hyperspin/Arcade/collections/Nintendo DS/roms/Metroid Prime - Hunters (USA).7z")


@pytest.fixture(scope="module")
def rom_pair():
    if not Path(ROM).exists():
        pytest.skip(f"owned ROM not available at {ROM}")
    return mph.open_rom(ROM)


@pytest.fixture(scope="module")
def inv(rom_pair):
    return mph.inventory(rom_pair[1])


def test_cartridge_identity_is_measured(rom_pair):
    rom_path, rom = rom_pair
    assert len(rom.data) == mph.ROM_SIZE
    assert rom.title and rom.gamecode and len(rom.gamecode) == 4
    assert mph.sha256_file(rom_path) == mph.ROM_SHA256


def test_counts_come_from_the_file_table(inv):
    assert inv["path_count"] == sum(inv["extensions"].values())
    assert len(inv["model_files"]) == sum(1 for p in inv["model_files"] if p.endswith("_Model.bin"))
    assert len(inv["archives"]) == 104
    assert inv["narc_files"] == []          # the .arc container is the game's own, not a NARC
    assert inv["extensions"][".bin"] + inv["extensions"][".arc"] == inv["path_count"] - 99


def test_target_slot_is_the_selectable_samus_model(rom_pair, inv):
    _rom_path, rom = rom_pair
    target = mph.identify_target(rom, inv)
    assert target["model_path"] == "characterselect/samus_Model.bin"
    assert target["model_size"] > 0
    assert len(target["model_sha256"]) == 64
    assert target["animation_paths"], "the model slot must have its animation partners"
    assert all(p.startswith("characterselect/samus_") for p in target["animation_paths"])


def test_identify_target_needs_the_character():
    with pytest.raises(ValueError):
        mph.identify_target(None, {"character_select_models": ["characterselect/luigi_Model.bin"]})


def test_manifest_is_written_and_self_consistent(rom_pair, inv, tmp_path):
    rom_path, rom = rom_pair
    out = tmp_path / "manifest.json"
    assert mph.main([str(rom_path), "--out", str(out)]) == 0
    man = json.loads(out.read_text())
    assert man["game_id"] == "fe580e2ad4ec0052"
    assert man["source"]["sha256"] == mph.ROM_SHA256
    assert man["counts"]["paths"] == inv["path_count"]
    assert man["target_slot"]["model_path"] == "characterselect/samus_Model.bin"


def test_archive_route_yields_the_same_cartridge(rom_pair):
    if not Path(ARCHIVE).exists():
        pytest.skip("owned .7z not reachable from here")
    _rom_path, rom = rom_pair
    arch_path, arch_rom = mph.open_rom(ARCHIVE)
    assert len(arch_rom.data) == len(rom.data)
    assert mph.sha256_file(arch_path) == mph.ROM_SHA256
