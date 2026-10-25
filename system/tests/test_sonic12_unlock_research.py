"""Focused tests for the Sonic 1 & 2 in one (Genesis) unlock research (#2231).

Validates ROM identity binding, Nemesis stream verification, evidence
artifact structure, and the honest pending_research gate in game_unlocks.
These are static-analysis tests only — no gameplay verification.
"""
from pathlib import Path

import pytest

from gbox import sonic12_analysis as S12
from gbox import sonic12_unlock_research as U
from gbox import game_unlocks as GU

ROM = Path("/home/ehm_eckx/gBox_alt/gbox-hermes-tasks/9d74df1306eb4752/evidence/sonic12/sonic1and2.bin")
EVIDENCE_JSON = Path("/home/ehm_eckx/gBox_alt/gbox-hermes-tasks/9d74df1306eb4752/evidence/sonic12/unlock_research_evidence.json")

GAME = {"game_id": "48d757e779e88504", "platform": "genesis", "title": "Sonic the Hedgehog 2"}


def test_rom_sha256_and_size_match():
    assert S12.ROM_SHA256 == "a755e0ae96df4b881f52e347ac450ce2207f8403667e06de5da0ef9fb499d99d"
    assert S12.ROM_SIZE == 2_097_152


def test_verified_nemesis_offsets_count():
    assert len(S12.VERIFIED_NEMESIS) == 4
    assert set(S12.VERIFIED_NEMESIS.keys()) == {0x4B42, 0xD49A, 0x78AA2, 0x7BEB4}


@pytest.mark.skipif(not ROM.is_file(), reason="owned ROM not present on this host")
def test_check_rom_passes_on_owned_rom():
    rom = ROM.read_bytes()
    result = S12.check_rom(rom)
    assert result["sha256_ok"]
    assert result["size_ok"]
    assert result["console"] == "SEGA GENESIS"


@pytest.mark.skipif(not ROM.is_file(), reason="owned ROM not present on this host")
def test_all_nemesis_streams_decode():
    rom = ROM.read_bytes()
    for offset, expected_tiles in S12.VERIFIED_NEMESIS.items():
        tiles, size = S12.decode_at(rom, offset)
        assert len(tiles) // 32 == expected_tiles, f"offset {offset:#x}"


@pytest.mark.skipif(not ROM.is_file(), reason="owned ROM not present on this host")
def test_build_evidence_structure():
    ev = U.build_evidence(str(ROM))
    assert ev["game_id"] == "48d757e779e88504"
    assert ev["platform"] == "genesis"
    assert ev["rom"]["sha256"] == S12.ROM_SHA256
    assert ev["rom"]["check"]["sha256_ok"]
    # All 4 nemesis streams must decode and match
    assert len(ev["nemesis_streams"]) == 4
    for s in ev["nemesis_streams"]:
        assert s["match"], f"nemesis stream at {s['offset']} failed"
    # Category counts
    s = ev["unlock_summary"]
    assert s["characters"] == 3       # Sonic, Tails, Knuckles(unknown)
    assert s["levels_sonic2"] == 24   # 8 zones × 3 acts
    assert s["levels_sonic1"] == 9    # 3 zones × 3 acts
    assert s["modes"] >= 2
    assert ev["static_analysis_only"] is True
    assert len(ev["runtime_verification_required"]) > 0


def test_profile_for_returns_pending_research():
    p = GU.profile_for(GAME)
    assert p["status"] == "pending_research"
    assert p["verified"] is False
    assert "characters" in p["scope"]
    assert "levels_sonic2" in p["scope"]
    assert "Sonic" in p["reason"] or "sonic" in p["reason"].lower()


def test_pre_launch_returns_research_pending():
    class FakeCtx:
        pass
    r = GU.pre_launch(GAME, FakeCtx())
    assert r["state"] == "research_pending"
    assert r["applied"] is False
    assert r["nemesis_verified"] is True
    assert r["evidence"]["characters"] == 3
    assert r["evidence"]["levels_sonic2"] == 24
    assert len(r["runtime_checks_pending"]) > 0


@pytest.mark.skipif(not EVIDENCE_JSON.is_file(), reason="evidence JSON not yet generated")
def test_evidence_json_exists_and_is_valid():
    import json
    ev = json.loads(EVIDENCE_JSON.read_text())
    assert ev["kind"] == "sonic12_unlock_research"
    assert ev["game_id"] == "48d757e779e88504"
    assert ev["rom"]["sha256"] == S12.ROM_SHA256
