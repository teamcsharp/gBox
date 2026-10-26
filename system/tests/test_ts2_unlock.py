"""Focused tests for the TS2 (GameCube) unlock research register.

The profile is deliberately unverified, so these tests assert the safety
properties that matter today: exact-revision guarding, honest reporting, and
that no writer is reachable from the automatic pre_launch path.
"""

import pytest

from gbox import game_unlocks
from gbox import ts2_unlock

GAME = {"game_id": ts2_unlock.GAME_ID, "platform": ts2_unlock.PLATFORM}


def test_identity():
    assert ts2_unlock.GAME_ID == "7049196b853fb256"
    assert ts2_unlock.PLATFORM == "gamecube"


def test_revision_guard():
    assert ts2_unlock.matches_revision(ts2_unlock.EXECUTABLE_SHA256) is True
    assert ts2_unlock.matches_revision(ts2_unlock.EXECUTABLE_SHA256.upper()) is True
    assert ts2_unlock.matches_revision("0" * 64) is False
    assert ts2_unlock.matches_revision("") is False
    assert ts2_unlock.matches_revision(None) is False


def test_dol_map_translation():
    seg = ts2_unlock.segment_for_vaddr(0x80003100)
    assert seg is not None and seg["kind"] == "text"
    assert ts2_unlock.file_offset_for_vaddr(0x80003100) == seg["file_offset"]
    with pytest.raises(ValueError):
        ts2_unlock.file_offset_for_vaddr(0x04614360)


def test_profile_is_honest_and_unverified():
    prof = ts2_unlock.profile()
    assert prof["status"] == "pending_research"
    assert prof["verified"] is False
    assert prof["profile"] is None
    assert prof["scope"] == ts2_unlock.CATEGORIES
    assert prof["exclusions"]
    assert prof["evidence"]["executable_sha256"] == ts2_unlock.EXECUTABLE_SHA256
    assert prof["evidence"]["blockers"]
    assert prof["evidence"]["next_steps"]


def test_every_category_is_inventoried():
    prof = ts2_unlock.profile()
    cats = {i["category"] for i in prof["items"]}
    assert cats == set(ts2_unlock.CATEGORIES)
    for item in prof["items"]:
        assert item["state"] in {"unknown", "not_observed", "unlocked", "not_present"}
        assert item["evidence"]


def test_no_category_claims_unlocked():
    prof = ts2_unlock.profile()
    assert not [i for i in prof["items"] if i["state"] == "unlocked"]


def test_community_codes_are_not_write_targets():
    prof = ts2_unlock.profile()
    cands = prof["evidence"]["community_code_candidates"]
    assert cands
    for c in cands:
        assert c["status"] == "unverified_candidate"
        assert c["maps_into_owned_dol"] is False


def test_profile_for_routes_ts2():
    got = game_unlocks.profile_for(dict(GAME))
    assert got["status"] == "pending_research"
    assert got["verified"] is False
    assert got["game_id"] == ts2_unlock.GAME_ID
    assert "writer" not in got


def test_profile_for_does_not_match_other_games():
    got = game_unlocks.profile_for({"game_id": "deadbeef", "platform": "gamecube"})
    assert got.get("game_id") != ts2_unlock.GAME_ID
