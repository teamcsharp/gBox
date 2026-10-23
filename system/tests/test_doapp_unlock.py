"""Focused tests for the DOAPP unlock-on-load checkpoint (gbox.doapp_unlock)."""
import pytest
from gbox import doapp_unlock as D


def test_revision_guard_only_accepts_the_evidenced_build():
    assert D.revision_match(D.PROGRAM_SHA1, D.RAM_SHA256)
    assert not D.revision_match("0" * 40, D.RAM_SHA256)
    assert not D.revision_match(D.PROGRAM_SHA1, "1" * 64)


def test_profile_registration_returns_honest_research_state():
    from gbox.game_unlocks import profile_for, pre_launch
    game = {"game_id": D.GAME_ID, "platform": "arcade", "title": "Dead Or Alive ++ (Japan)"}
    p = profile_for(game)
    assert not p["verified"]
    out = pre_launch(game, None)
    assert out["state"] in ("research_pending", "unsupported")
    assert out["applied"] is False


def test_pre_launch_noop_never_writes():
    game = {"game_id": D.GAME_ID, "platform": "arcade"}
    out = D.pre_launch(game, None)
    assert out["applied"] is False
    assert out["profile"] == "doapp-jp-static-inventory-v1"
    assert out["inventory"]["characters"]["count"] == 11
    assert out["inventory"]["hidden_characters"]["status"] == "not_present"


def test_inventory_covers_required_categories():
    assert set(D.INVENTORY) >= {"characters", "hidden_characters", "modes", "levels",
                                "stages", "costumes", "items", "extras"}
    for cat, entry in D.INVENTORY.items():
        assert "status" in entry and "evidence" in entry


def test_modes_and_fighters_match_decoded_evidence():
    assert D.MODES == ["TOURNAMENT", "TIME ATTACK", "VERSUS", "SURVIVAL", "KUMITE",
                       "TRAINING", "TEAM BATTLE", "OPTION"]
    assert D.FIGHTERS[13] == "AYANE" and D.FIGHTERS[0] == "ZACK"
    assert set(D.FIGHTERS) == {0, 1, 2, 4, 5, 6, 8, 9, 11, 12, 13}
