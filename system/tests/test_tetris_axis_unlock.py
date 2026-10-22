import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gbox import game_unlocks
from gbox import tetris_axis_unlock as tau

CATEGORIES = ("characters", "hidden_characters", "modes", "levels", "stages",
              "costumes", "items", "extras")


def test_identity_is_pinned():
    assert tau.GAME_ID == "d6d1a0582e4c3b0b"
    assert tau.PLATFORM == "3ds"
    assert tau.GAME_CODE == "ATLE"
    assert len(tau.ROM_SHA256) == 64
    assert len(tau.CODE_SHA256) == 64
    assert tau.CODE_SIZE > 0
    assert tau.CODE_BASE == 0x100000


def test_profile_is_honest():
    prof = tau.profile()
    assert prof["gameplay_verified"] is False
    assert prof["complete_unlock_profile"] is False
    assert prof["verified"] == []
    assert prof["state"] == "static_evidence_only"
    assert prof["scope"] == list(CATEGORIES)
    assert prof["unlock_ops"] == []


def test_inventory_covers_every_required_category():
    inv = tau.inventory()
    assert set(inv["categories"]) == set(CATEGORIES)
    for row in inv["entries"]:
        assert row["lock_state"] in tau.LOCK_STATES
        assert row["evidence"]
        assert row["category"] in CATEGORIES
        assert row["name"]


def test_character_entries_use_exact_model_names():
    inv = tau.inventory()
    chars = [r["name"] for r in inv["entries"] if r["category"] == "characters"]
    assert chars, "expected the /co04/NW character model set"
    assert all(c.startswith("co04_ch_m") for c in chars)
    assert len(chars) == len(set(chars))


def test_stage_packs_are_inventoried():
    inv = tau.inventory()
    stages = [r["name"] for r in inv["entries"] if r["category"] == "stages"]
    assert stages, "expected stage packs sp00..sp17"
    assert all(s.startswith("sp") and s[2:].isdigit() for s in stages)


def test_rom_guard_accepts_owned_build_and_rejects_other_bytes(tmp_path):
    if not tau.rom_path().exists():
        pytest.skip("owned ROM not present in this environment")
    assert tau.rom_guard()["ok"] is True
    bogus = tmp_path / "bogus.3ds"
    bogus.write_bytes(b"not the owned revision")
    guard = tau.rom_guard(bogus)
    assert guard["ok"] is False
    assert guard["actual"] != tau.ROM_SHA256


def test_save_key_evidence_matches_the_decompressed_code():
    code = tau.code_path()
    if not code.exists():
        pytest.skip("decompressed code segment not present in this environment")
    data = code.read_bytes()
    assert len(data) == tau.CODE_SIZE
    for off, text, _role in tau.SAVE_KEY_STRINGS:
        assert data[off:off + len(text)] == text.encode("ascii")
    for off, text in tau.SAVE_SERVICE_STRINGS:
        assert data[off:off + len(text)] == text.encode("ascii")


def test_no_unproven_write_targets():
    assert tau.unlock_ops() == []
    assert tau.write_targets() == []


def test_game_unlocks_registration():
    prof = game_unlocks.profile_for({"game_id": tau.GAME_ID, "platform": "3ds"})
    assert prof["status"] == "pending_research"
    assert prof["verified"] is False
    assert prof["scope"] == list(CATEGORIES)
    assert prof["reason"]


def test_pre_launch_never_applies():
    res = game_unlocks.pre_launch({"game_id": tau.GAME_ID, "platform": "3ds"}, None)
    assert res["applied"] is False
    assert res["state"] == "research_pending"
    assert res["next"]
