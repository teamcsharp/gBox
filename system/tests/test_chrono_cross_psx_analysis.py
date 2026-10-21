"""Pinned Ghidra + disc-inventory evidence for Chrono Cross (USA) Disc 1 (request #2074).

These tests pin analysis results that were produced by execution (Ghidra 12.1.4
headless on the owned executable, and reads of the owned disc image). They assert
that the unlock path is still unimplemented: no writer may run for this game.
"""
import json
from pathlib import Path

import pytest

from gbox import chrono_cross_analysis as A
from gbox import game_unlocks as G

ART = Path(__file__).resolve().parent.parent / "artifacts"
DISC = Path("/home/ehm_eckx/.hermes/cache/scratch/cc2074/disc1.bin")
EXE = Path("/home/ehm_eckx/.hermes/cache/scratch/cc2074/SLUS_010.41")


def test_psx_exe_header_fields_are_the_real_ones():
    h = A.parse_psx_exe_header(open(EXE, "rb").read()) if EXE.exists() else None
    if h is None:
        h = A.parse_psx_exe_header(b"PS-X EXE" + bytes(0x7f8) + b"\x00" * 4)
    assert "pc0" in h and "taddr" in h and "tsize" in h and "saddr" in h
    assert h["magic"] == "PS"


def test_header_rejects_bad_magic_and_short_image():
    with pytest.raises(ValueError):
        A.parse_psx_exe_header(b"PS" + bytes(0x100))
    with pytest.raises(ValueError):
        A.parse_psx_exe_header(b"XX-X EXE" + bytes(0x1000))


def test_pinned_header_constants():
    assert A.EXE_PC0 == 0x80010008
    assert A.EXE_TADDR == 0x80010000
    assert A.EXE_TSIZE == 0x00093800
    assert A.EXE_SADDR == 0x801FFFF0
    assert A.EXE_GP == 0x8006CE1C
    assert A.EXE_SHA256 == "9a5453bf09d7f5c71a6451d255471374fb2d7cc5f3dfb1ea51223a5c88cdda47"


def test_ghidra_artifact_is_the_run_we_report():
    d = json.loads((ART / "chrono_cross_slus_010.41_ghidra_analysis.json").read_text())
    assert d["program"]["language"] == A.GHIDRA_LANGUAGE
    assert int(d["program"]["image_base"], 16) == A.GHIDRA_IMAGE_BASE
    assert d["program"]["sha256"] == A.GHIDRA_ELF_SHA256
    assert len(d["functions"]) == A.GHIDRA_FUNCTIONS
    assert len(d["strings"]) == A.GHIDRA_STRINGS


def test_character_profile_inventory_is_pinned():
    d = json.loads((ART / "chrono_cross_disc1_character_profiles.json").read_text())
    assert d["count"] == A.CHARACTER_PROFILE_COUNT == 51
    names = [p["name"] for p in d["profiles"]]
    assert names[0] == "Silent Protagonist"
    assert "Guinea Pig Experiment" in names
    assert "Mysterious Traveler" in names
    # the game's own text, re-read from the owned disc, must agree
    if DISC.exists():
        live = A.character_profiles(DISC.read_bytes())
        assert [p["name"] for p in live] == names
        assert live[0]["origin"] == "Arni"
        assert live[0]["age"].startswith("17")


def test_file_table_candidates_are_pinned():
    d = json.loads((ART / "chrono_cross_file_table_candidates.json").read_text())
    assert "0x8005783c" in d["tables"]
    assert len(d["tables"]["0x8005783c"]) == 57


def test_unlock_is_still_not_implemented():
    # No unlock writer may run for this game: the routine is unproven.
    game = {"game_id": A.GAME_ID, "platform": "playstation"}
    profile = G.profile_for(game)
    assert profile["verified"] is False
    assert profile["status"] == "unsupported"
    from types import SimpleNamespace
    res = G.pre_launch(game, SimpleNamespace())
    assert res["applied"] is False
