"""Candidate-profile checks for SM64DS (#2253): encoding and honesty flags, not gameplay."""
from pathlib import Path

import pytest

from gbox import game_unlocks, sm64ds_unlock as S

CHT = Path("/home/ehm_eckx/gBox/system/gbox-data/cheatdb/libretro-database/cht/Nintendo - Nintendo DS/Super Mario 64 DS (USA).cht")


def test_ops_in_ram_and_unverified():
    for o in S.unlock_ops():
        assert S.in_main_ram(o["address"], o["width"])
        assert not o["gameplay_verified"] and not o["database_verified"]
    d = {o["field"]: o for o in S.unlock_ops()}
    assert d["course_stars_0"]["hex_bytes"] == "ffffffff"
    assert d["castle_doors_hi"]["hex_bytes"] == "ff"


def test_pre_launch_is_candidate_only():
    r = game_unlocks.pre_launch({"game_id": S.GAME_ID, "platform": "nds"}, None)
    assert r["state"] == "candidate_pending_verification" and r["applied"] is False


def test_plan_not_executed():
    p = S.live_acceptance_plan("w-1")
    assert p["executed"] is False and len(p["jobs"]) == len(S.UNLOCK_FIELDS)


@pytest.mark.skipif(not CHT.exists(), reason="cheat db not installed")
def test_matches_cheat_db():
    import hashlib
    assert hashlib.sha256(CHT.read_bytes()).hexdigest() == S.DATABASE_SHA256
    txt = CHT.read_text()
    for a in ("12094BA4+0000FFFF", "22094BA6+000000FF", "02094BB4+FFFFFFFF",
              "12094BC0+0000FFFF", "22094BC2+000000FF", "02094BE8+FFFFFFFF"):
        assert a in txt
